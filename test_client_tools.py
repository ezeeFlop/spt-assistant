#!/usr/bin/env python3
"""
Test script for client tool integration.
This script simulates a client registering capabilities and responding to tool requests.
"""

import asyncio
import json
import time
import redis.asyncio as redis
from typing import Dict, Any

# Configuration
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_PASSWORD = None

# Channels (should match config)
CLIENT_TOOL_REQUEST_CHANNEL = "client_tool_request"
CLIENT_TOOL_RESPONSE_CHANNEL = "client_tool_response"
CLIENT_CAPABILITIES_CHANNEL = "client_capabilities"

class MockClient:
    def __init__(self, client_id: str, platform: str):
        self.client_id = client_id
        self.platform = platform
        self.redis_client = None
        self.running = False
        
        # Mock capabilities
        self.capabilities = {
            "take_screenshot": {
                "description": "Captures a screenshot of the current screen",
                "parameters": {
                    "format": {"type": "string", "description": "Image format (png, jpg)", "required": False, "default": "png"}
                }
            },
            "get_system_info": {
                "description": "Gets basic system information",
                "parameters": {}
            }
        }
    
    async def connect(self):
        """Connect to Redis."""
        self.redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD
        )
        await self.redis_client.ping()
        print(f"Mock client {self.client_id} connected to Redis")
    
    async def register_capabilities(self, conversation_id: str):
        """Register client capabilities."""
        registration = {
            "type": "client_capability_registration",
            "conversation_id": conversation_id,
            "client_id": self.client_id,
            "platform": self.platform,
            "capabilities": self.capabilities,
            "timestamp": time.time()
        }
        
        await self.redis_client.publish(
            CLIENT_CAPABILITIES_CHANNEL,
            json.dumps(registration)
        )
        print(f"Mock client {self.client_id} registered capabilities for conversation {conversation_id}")
    
    async def listen_for_tool_requests(self):
        """Listen for tool requests and respond."""
        pubsub = self.redis_client.pubsub()
        await pubsub.subscribe(CLIENT_TOOL_REQUEST_CHANNEL)
        print(f"Mock client {self.client_id} listening for tool requests...")
        
        self.running = True
        while self.running:
            try:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message["type"] == "message":
                    await self.handle_tool_request(message["data"].decode('utf-8'))
                await asyncio.sleep(0.1)
            except Exception as e:
                print(f"Error in tool request listener: {e}")
                break
        
        await pubsub.unsubscribe(CLIENT_TOOL_REQUEST_CHANNEL)
        await pubsub.close()
    
    async def handle_tool_request(self, request_data: str):
        """Handle a tool request."""
        try:
            request = json.loads(request_data)
            tool_call_id = request.get("tool_call_id")
            tool_name = request.get("tool_name")
            conversation_id = request.get("conversation_id")
            arguments = request.get("arguments", "{}")
            
            print(f"Mock client {self.client_id} received tool request: {tool_name} (call_id: {tool_call_id})")
            
            # Simulate tool execution
            result = await self.execute_mock_tool(tool_name, json.loads(arguments))
            
            # Send response
            response = {
                "type": "tool_response",
                "tool_call_id": tool_call_id,
                "conversation_id": conversation_id,
                "success": True,
                "result": result,
                "error": None,
                "timestamp": time.time()
            }
            
            await self.redis_client.publish(
                CLIENT_TOOL_RESPONSE_CHANNEL,
                json.dumps(response)
            )
            print(f"Mock client {self.client_id} sent response for tool {tool_name}")
            
        except Exception as e:
            print(f"Error handling tool request: {e}")
            # Send error response
            try:
                error_response = {
                    "type": "tool_response",
                    "tool_call_id": request.get("tool_call_id", "unknown"),
                    "conversation_id": request.get("conversation_id", "unknown"),
                    "success": False,
                    "result": None,
                    "error": str(e),
                    "timestamp": time.time()
                }
                await self.redis_client.publish(
                    CLIENT_TOOL_RESPONSE_CHANNEL,
                    json.dumps(error_response)
                )
            except Exception as send_error:
                print(f"Failed to send error response: {send_error}")
    
    async def execute_mock_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a mock tool and return results."""
        if tool_name == "take_screenshot":
            format_type = arguments.get("format", "png")
            return {
                "success": True,
                "image_data": "mock_base64_image_data_here",
                "format": format_type,
                "width": 1920,
                "height": 1080,
                "size_bytes": 12345
            }
        elif tool_name == "get_system_info":
            return {
                "success": True,
                "system": {
                    "os_name": "MockOS",
                    "os_version": "1.0.0",
                    "host_name": "mock-host",
                    "processor_count": 8,
                    "physical_memory": 16000000000
                },
                "client": {
                    "client_id": self.client_id,
                    "platform": self.platform,
                    "available_tools": list(self.capabilities.keys())
                }
            }
        else:
            raise ValueError(f"Unknown tool: {tool_name}")
    
    async def stop(self):
        """Stop the client."""
        self.running = False
        if self.redis_client:
            await self.redis_client.close()
        print(f"Mock client {self.client_id} stopped")

async def test_tool_request():
    """Test sending a tool request directly."""
    redis_client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        db=REDIS_DB,
        password=REDIS_PASSWORD
    )
    
    # Simulate a tool request from the LLM orchestrator
    tool_request = {
        "type": "tool_request",
        "conversation_id": "test_conversation_123",
        "tool_call_id": "call_test_123",
        "tool_name": "take_screenshot",
        "arguments": json.dumps({"format": "png"}),
        "timeout_ms": 30000,
        "timestamp": time.time()
    }
    
    print("Sending test tool request...")
    await redis_client.publish(
        CLIENT_TOOL_REQUEST_CHANNEL,
        json.dumps(tool_request)
    )
    
    # Listen for response
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(CLIENT_TOOL_RESPONSE_CHANNEL)
    
    print("Waiting for tool response...")
    start_time = time.time()
    while time.time() - start_time < 10:  # 10 second timeout
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
        if message and message["type"] == "message":
            response_data = json.loads(message["data"].decode('utf-8'))
            if response_data.get("tool_call_id") == "call_test_123":
                print(f"Received tool response: {response_data}")
                break
        await asyncio.sleep(0.1)
    else:
        print("Tool response timeout!")
    
    await pubsub.unsubscribe(CLIENT_TOOL_RESPONSE_CHANNEL)
    await pubsub.close()
    await redis_client.close()

async def main():
    """Main test function."""
    print("Starting client tool integration test...")
    
    # Create mock client
    client = MockClient("test_client_001", "TestPlatform")
    
    try:
        # Connect client
        await client.connect()
        
        # Register capabilities
        await client.register_capabilities("test_conversation_123")
        
        # Start listening for tool requests
        listen_task = asyncio.create_task(client.listen_for_tool_requests())
        
        # Wait a bit for setup
        await asyncio.sleep(1)
        
        # Send a test tool request
        await test_tool_request()
        
        # Wait a bit more to see results
        await asyncio.sleep(2)
        
        # Stop client
        await client.stop()
        listen_task.cancel()
        
        try:
            await listen_task
        except asyncio.CancelledError:
            pass
        
        print("Test completed!")
        
    except Exception as e:
        print(f"Test failed: {e}")
        await client.stop()

if __name__ == "__main__":
    asyncio.run(main()) 