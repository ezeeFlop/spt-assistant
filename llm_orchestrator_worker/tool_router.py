# Service for routing tool calls to the MCP client library (FR-06)

import json
import asyncio
import time
from typing import Dict, Any, Optional, Set, List
import redis.asyncio as redis
from llm_orchestrator_worker.config import orchestrator_settings
from llm_orchestrator_worker.logging_config import get_logger

logger = get_logger(__name__)

class ToolRouter:
    def __init__(self):
        # TODO: Initialize MCP client library here based on orchestrator_settings.MCP_CLIENT_CONFIG_PATH
        # For now, this is a placeholder.
        self.mcp_client = None # Replace with actual MCP client instance
        
        # Client tool management
        self.client_tool_registry: Dict[str, Dict[str, Any]] = {}  # tool_name -> tool_info
        self.pending_client_tools: Dict[str, Dict[str, Any]] = {}  # tool_call_id -> request_info
        self.client_capabilities: Dict[str, Dict[str, Any]] = {}   # conversation_id -> capabilities
        
        if orchestrator_settings.MCP_CLIENT_CONFIG_PATH:
            logger.info(f"MCP Client config path specified: {orchestrator_settings.MCP_CLIENT_CONFIG_PATH}. (Actual client init TBD)")
        else:
            logger.warning("MCP Client config path not specified. Tool calls will not be dispatched.")
        logger.info("ToolRouter initialized (placeholder for MCP client, with client tool support).")

    def register_client_capabilities(self, conversation_id: str, capabilities: Dict[str, Any], client_id: str, platform: str):
        """Register capabilities for a specific client."""
        self.client_capabilities[conversation_id] = {
            "capabilities": capabilities,
            "client_id": client_id,
            "platform": platform,
            "registered_at": time.time()
        }
        
        # Update tool registry with client tools
        for tool_name, tool_info in capabilities.items():
            self.client_tool_registry[tool_name] = {
                "conversation_id": conversation_id,
                "client_id": client_id,
                "platform": platform,
                "info": tool_info
            }
        
        logger.info(f"Registered client capabilities for conv_id {conversation_id}: {list(capabilities.keys())}")

    def is_client_tool(self, tool_name: str) -> bool:
        """Check if a tool is a client-specific tool."""
        return tool_name in self.client_tool_registry

    async def dispatch_tool_call(self, tool_call_id: str, tool_name: str, tool_arguments: str, conversation_id: str = None) -> Dict[str, Any]:
        """
        Dispatches a tool call via the MCP client library or to a client.
        Enhanced to support client-specific tools while maintaining backward compatibility.
        """
        logger.info(f"Dispatching tool call ID '{tool_call_id}': Name='{tool_name}', Args='{tool_arguments}', ConvID='{conversation_id}'")

        # Check if it's a client-specific tool
        if self.is_client_tool(tool_name) and conversation_id:
            return await self.dispatch_client_tool(tool_call_id, tool_name, tool_arguments, conversation_id)
        
        # Fall back to existing MCP client logic
        return await self.dispatch_mcp_tool(tool_call_id, tool_name, tool_arguments)

    async def dispatch_client_tool(self, tool_call_id: str, tool_name: str, tool_arguments: str, conversation_id: str) -> Dict[str, Any]:
        """Dispatch a tool call to a connected client."""
        try:
            # Get Redis client (we'll need to pass this in or get it from a service)
            # For now, create a new connection - this should be optimized later
            redis_client = redis.Redis(
                host=orchestrator_settings.REDIS_HOST,
                port=orchestrator_settings.REDIS_PORT,
                db=orchestrator_settings.REDIS_DB,
                password=orchestrator_settings.REDIS_PASSWORD
            )
            
            # Prepare tool request
            request = {
                "type": "tool_request",
                "conversation_id": conversation_id,
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "arguments": tool_arguments,
                "timeout_ms": 30000,
                "timestamp": time.time()
            }
            
            # Store pending request
            self.pending_client_tools[tool_call_id] = {
                "request": request,
                "start_time": time.time(),
                "conversation_id": conversation_id
            }
            
            # Publish tool request to client
            await redis_client.publish(orchestrator_settings.CLIENT_TOOL_REQUEST_CHANNEL, json.dumps(request))
            logger.info(f"Published client tool request for '{tool_name}' to conv_id {conversation_id}")
            
            # Wait for response with timeout
            response = await self.wait_for_client_response(tool_call_id, redis_client, timeout=30)
            
            # Clean up
            await redis_client.close()
            
            return response
            
        except Exception as e:
            logger.error(f"Error dispatching client tool '{tool_name}': {e}", exc_info=True)
            # Clean up pending request
            if tool_call_id in self.pending_client_tools:
                del self.pending_client_tools[tool_call_id]
            
            return {
                "tool_call_id": tool_call_id,
                "role": "tool",
                "name": tool_name,
                "content": json.dumps({"error": f"Failed to execute client tool '{tool_name}': {str(e)}"})
            }

    async def wait_for_client_response(self, tool_call_id: str, redis_client: redis.Redis, timeout: int = 30) -> Dict[str, Any]:
        """Wait for a client tool response with timeout."""
        pubsub = redis_client.pubsub()
        try:
            await pubsub.subscribe(orchestrator_settings.CLIENT_TOOL_RESPONSE_CHANNEL)
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message["type"] == "message":
                    try:
                        response_data = json.loads(message["data"].decode('utf-8'))
                        if response_data.get("tool_call_id") == tool_call_id:
                            # Found our response
                            if tool_call_id in self.pending_client_tools:
                                del self.pending_client_tools[tool_call_id]
                            
                            # Format response for LLM
                            if response_data.get("success", False):
                                content = json.dumps(response_data.get("result", {}))
                            else:
                                content = json.dumps({"error": response_data.get("error", "Unknown error")})
                            
                            return {
                                "tool_call_id": tool_call_id,
                                "role": "tool",
                                "name": self.pending_client_tools.get(tool_call_id, {}).get("request", {}).get("tool_name", "unknown"),
                                "content": content
                            }
                    except json.JSONDecodeError as e:
                        logger.error(f"Error decoding client tool response: {e}")
                        continue
                
                await asyncio.sleep(0.1)
            
            # Timeout reached
            logger.warning(f"Client tool call {tool_call_id} timed out after {timeout} seconds")
            if tool_call_id in self.pending_client_tools:
                tool_name = self.pending_client_tools[tool_call_id].get("request", {}).get("tool_name", "unknown")
                del self.pending_client_tools[tool_call_id]
            else:
                tool_name = "unknown"
            
            return {
                "tool_call_id": tool_call_id,
                "role": "tool",
                "name": tool_name,
                "content": json.dumps({"error": f"Client tool call timed out after {timeout} seconds"})
            }
            
        finally:
            await pubsub.unsubscribe(orchestrator_settings.CLIENT_TOOL_RESPONSE_CHANNEL)
            await pubsub.close()

    async def dispatch_mcp_tool(self, tool_call_id: str, tool_name: str, tool_arguments: str) -> Dict[str, Any]:
        """Original MCP tool dispatch logic - unchanged for backward compatibility."""
        if self.mcp_client is None:
            logger.warning(f"MCP client not available. Cannot dispatch tool call '{tool_name}'. Simulating error response.")
            return {
                "tool_call_id": tool_call_id,
                "role": "tool",
                "name": tool_name,
                "content": json.dumps({"error": "MCP client not configured or available."})
            }
        
        try:
            # Placeholder for actual MCP client interaction
            # mcp_result = await self.mcp_client.execute(tool_name, json.loads(tool_arguments))
            # For now, simulate a successful result or an error for testing
            if tool_name == "get_weather": # Example tool name
                args_dict = json.loads(tool_arguments)
                location = args_dict.get("location", "unknown")
                simulated_result = {"temperature": "25C", "condition": "sunny", "location": location}
                logger.info(f"Simulated MCP result for '{tool_name}': {simulated_result}")
                return {
                    "tool_call_id": tool_call_id,
                    "role": "tool",
                    "name": tool_name,
                    "content": json.dumps(simulated_result) # Content MUST be a JSON string for OpenAI tools
                }
            else:
                logger.warning(f"Unknown tool '{tool_name}' requested. Simulating tool not found.")
                return {
                    "tool_call_id": tool_call_id,
                    "role": "tool",
                    "name": tool_name,
                    "content": json.dumps({"error": f"Tool '{tool_name}' not found or not implemented."})
                }

        except json.JSONDecodeError as e:
            logger.error(f"Error decoding tool arguments for '{tool_name}': {e}. Arguments: '{tool_arguments}'")
            return {
                "tool_call_id": tool_call_id,
                "role": "tool",
                "name": tool_name,
                "content": json.dumps({"error": "Invalid JSON arguments for tool."})
            }
        except Exception as e:
            logger.error(f"Error dispatching tool call '{tool_name}' via MCP (or simulation): {e}", exc_info=True)
            return {
                "tool_call_id": tool_call_id,
                "role": "tool",
                "name": tool_name,
                "content": json.dumps({"error": f"An unexpected error occurred while executing tool '{tool_name}'."})
            }

    def get_client_tools_for_conversation(self, conversation_id: str) -> List[Dict[str, Any]]:
        """Get client tools for a conversation in LLM-compatible format."""
        if conversation_id not in self.client_capabilities:
            return []
        
        capabilities = self.client_capabilities[conversation_id]["capabilities"]
        llm_tools = []
        
        for tool_name, tool_info in capabilities.items():
            # Convert client tool info to LLM tool format (OpenAI format)
            # The client sends parameters in the format: {"type": "object", "properties": {...}, "required": [...]}
            parameters = tool_info.get("parameters", {})
            
            # Handle both old and new parameter formats for backward compatibility
            if isinstance(parameters, dict) and "properties" in parameters:
                # New format: parameters already contains type, properties, required
                tool_parameters = parameters
            else:
                # Old format: parameters IS the properties
                tool_parameters = {
                    "type": "object",
                    "properties": parameters,
                    "required": tool_info.get("required", [])
                }
            
            tool_def = {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_info.get("description", f"Execute {tool_name} on the client"),
                    "parameters": tool_parameters
                }
            }
            llm_tools.append(tool_def)
        
        logger.info(f"Generated {len(llm_tools)} LLM tool definitions for conversation {conversation_id}")
        return llm_tools

    def cleanup_expired_requests(self, max_age_seconds: int = 300):
        """Clean up expired pending tool requests."""
        current_time = time.time()
        expired_ids = [
            tool_call_id for tool_call_id, info in self.pending_client_tools.items()
            if current_time - info["start_time"] > max_age_seconds
        ]
        
        for tool_call_id in expired_ids:
            logger.warning(f"Cleaning up expired client tool request: {tool_call_id}")
            del self.pending_client_tools[tool_call_id]