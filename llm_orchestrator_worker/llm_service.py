# Service for interacting with Large Language Models (LLMs)
import json
from typing import AsyncIterator, Dict, List, Optional, Tuple, Union, Any

import litellm # Replaced OpenAI client with LiteLLM
# from openai import AsyncOpenAI, OpenAIError # Using openai as an example client
import httpx # For direct HTTP calls to Ollama for model management
import asyncio # Added for asyncio.Event
import structlog

from llm_orchestrator_worker.config import orchestrator_settings
from llm_orchestrator_worker.logging_config import get_logger

logger = get_logger(__name__)

# Register ollama models that support native function calling
# This prevents LiteLLM from falling back to JSON mode
litellm.register_model({
    "ollama/llama3.1": {
        "supports_function_calling": True
    },
    "ollama_chat/llama3.1": {
        "supports_function_calling": True
    },
    "ollama/llama3-groq-tool-use": {
        "supports_function_calling": True
    },
    "ollama_chat/llama3-groq-tool-use": {
        "supports_function_calling": True
    }
})

# Verify registration worked
logger.info(f"Function calling support check for ollama/llama3-groq-tool-use: {litellm.supports_function_calling('ollama/llama3-groq-tool-use')}")
logger.info(f"Function calling support check for ollama_chat/llama3-groq-tool-use: {litellm.supports_function_calling('ollama_chat/llama3-groq-tool-use')}")

class Message(Dict):
    role: str # "system", "user", "assistant", "tool"
    content: Optional[str] = None
    tool_calls: Optional[List[Dict]] = None # For assistant messages requesting tool calls
    tool_call_id: Optional[str] = None # For tool messages responding to a call

class LLMService:
    def __init__(self):
        self.default_provider = orchestrator_settings.LLM_PROVIDER
        self.default_model_name = orchestrator_settings.LLM_MODEL_NAME
        # API keys for providers like OpenAI, Anthropic, etc., are typically set as environment variables
        # which LiteLLM automatically picks up. For Ollama, API key is often not needed or is a placeholder.
        self.default_api_key = orchestrator_settings.LLM_API_KEY # May be used by LiteLLM if set or for specific configurations
        self.default_base_url = orchestrator_settings.LLM_BASE_URL # Crucial for Ollama and other self-hosted models
        self.default_max_tokens = orchestrator_settings.LLM_MAX_TOKENS
        self.default_temperature = orchestrator_settings.LLM_TEMPERATURE

        # No explicit client initialization here; LiteLLM handles it.
        # However, LiteLLM can be configured globally, e.g., for routing or custom logger
        # litellm.set_verbose = True # Example: Enable verbose logging for LiteLLM if needed for debugging
        self._ollama_model_pull_locks: Dict[str, asyncio.Lock] = {} # Lock per model name

        logger.info(f"LLMService initialized to use LiteLLM. Default provider hint: {self.default_provider}, default model: {self.default_model_name}")
        
        # For managing cancellation of streams
        self._cancellation_events: Dict[str, asyncio.Event] = {}

    def _get_cancellation_event(self, conversation_id: str) -> asyncio.Event:
        if conversation_id not in self._cancellation_events:
            self._cancellation_events[conversation_id] = asyncio.Event()
        return self._cancellation_events[conversation_id]

    def cancel_generation(self, conversation_id: str):
        """Signals the LLM stream for the given conversation_id to stop generating."""
        if conversation_id in self._cancellation_events:
            logger.info(f"LLMService: Setting cancellation event for conversation_id: {conversation_id}")
            self._cancellation_events[conversation_id].set()
        else:
            logger.warning(f"LLMService: No active generation found to cancel for conversation_id: {conversation_id}")

    async def _ensure_ollama_model_available(self, model_name: str, api_base: Optional[str]):
        """Checks if an Ollama model is available, and pulls it if not."""
        if not api_base:
            logger.warning(f"Ollama API base URL not configured. Cannot ensure model '{model_name}' is available.")
            return

        ollama_model_name = model_name.replace("ollama/", "") # Ensure we use the plain name for Ollama API

        # Get or create a lock for this model name
        if ollama_model_name not in self._ollama_model_pull_locks:
            self._ollama_model_pull_locks[ollama_model_name] = asyncio.Lock()
        
        model_lock = self._ollama_model_pull_locks[ollama_model_name]

        async with model_lock: # Ensure only one pull attempt per model at a time
            try:
                async with httpx.AsyncClient(timeout=60.0) as client: # Increased timeout for show
                    # 1. Check if model exists
                    logger.debug(f"Checking if Ollama model '{ollama_model_name}' exists at {api_base}...")
                    try:
                        response_show = await client.post(f"{api_base.rstrip('/')}/api/show", json={"name": ollama_model_name})
                        if response_show.status_code == 200:
                            logger.info(f"Ollama model '{ollama_model_name}' found locally.")
                            return # Model exists
                        elif response_show.status_code == 404:
                            logger.info(f"Ollama model '{ollama_model_name}' not found locally. Attempting to pull.")
                        else:
                            logger.warning(f"Unexpected status code {response_show.status_code} when checking for Ollama model '{ollama_model_name}': {response_show.text}")
                            # Proceed to pull as a fallback, or could error out
                    except httpx.RequestError as e:
                        logger.error(f"Error checking Ollama model '{ollama_model_name}': {e}. Assuming not found and attempting pull.", exc_info=True)
                        # Fallthrough to pull

                    # 2. If model not found (404 or error during check), try to pull it
                    logger.info(f"Pulling Ollama model '{ollama_model_name}' from {api_base}. This might take a while...")
                    # Use a longer timeout for pull, as it can download large files
                    pull_timeout = httpx.Timeout(300.0, connect=60.0) # 5 minutes total, 1 min connect
                    async with httpx.AsyncClient(timeout=pull_timeout) as pull_client:
                        pull_payload = {"name": ollama_model_name, "stream": False} # Stream false to wait for completion
                        response_pull = await pull_client.post(f"{api_base.rstrip('/')}/api/pull", json=pull_payload)

                        if response_pull.status_code == 200:
                            # In non-streaming pull, Ollama returns a final status message.
                            # Example: {"status":"success"} or messages indicating download progress then success.
                            # We assume success if 200 OK.
                            logger.info(f"Successfully pulled Ollama model '{ollama_model_name}'. Response: {response_pull.text[:200]}")
                        else:
                            logger.error(f"Failed to pull Ollama model '{ollama_model_name}'. Status: {response_pull.status_code}, Response: {response_pull.text}")
                            # Decide if to raise an error or let acompletion fail
                            # For now, log and let LiteLLM handle the subsequent failure if model is still not there.
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP Status Error during Ollama model management for '{ollama_model_name}': {e.response.status_code} - {e.response.text}", exc_info=True)
            except httpx.RequestError as e:
                logger.error(f"Request Error during Ollama model management for '{ollama_model_name}': {e}", exc_info=True)
            except Exception as e:
                logger.error(f"Unexpected error during Ollama model management for '{ollama_model_name}': {e}", exc_info=True)
            finally:
                # Clean up the lock if no other tasks are waiting for it.
                # This is a simple cleanup; more sophisticated lock management might be needed if tasks are cancelled.
                if ollama_model_name in self._ollama_model_pull_locks and model_lock.locked() is False:
                    # Check if anyone is waiting. This is tricky as Lock doesn't expose waiters directly.
                    # For simplicity, we might just leave the lock object. Or, if we know no other calls for THIS model
                    # are pending in this service instance, we could del it.
                    # A simpler approach: locks are per service instance and model. They will be GC'd with the service.
                    pass

    async def generate_response_stream(
        self,
        conversation_id: str, # Added conversation_id for cancellation
        conversation_history: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,  # Add tools parameter
        model_name_override: Optional[str] = None,
        temperature_override: Optional[float] = None,
        max_tokens_override: Optional[int] = None,
        # provider_override: Optional[str] = None, # Consider if explicit provider override is needed
        # base_url_override: Optional[str] = None, # Consider for dynamic base URLs
        # api_key_override: Optional[str] = None, # Consider for dynamic API keys
    ) -> AsyncIterator[Union[str, Dict]]:

        current_model_name = model_name_override or self.default_model_name
        current_temperature = temperature_override if temperature_override is not None else self.default_temperature
        current_max_tokens = max_tokens_override or self.default_max_tokens
        
        # Determine provider and potentially adjust model name for LiteLLM
        # For Ollama, LiteLLM expects model names like "ollama/modelname"
        # If default_provider is ollama, or if model_name_override implies ollama.
        effective_provider = self.default_provider # Could be enhanced with provider_override
        
        llm_call_params = {
            "model": current_model_name,
            "messages": conversation_history,
            "temperature": current_temperature,
            "max_tokens": current_max_tokens,
            "stream": True,
            "tools": tools,
            # "tool_choice": "auto"  # FR-06: Let LLM decide if it needs tools
        }

        # Handle provider-specific adjustments, especially for Ollama
        # LiteLLM uses model prefix "ollama/" or custom_llm_provider="ollama"
        # It can also pick up OLLAMA_API_BASE from environment.
        # If orchestrator_settings.LLM_PROVIDER is "ollama", ensure model name is prefixed or pass api_base.
        
        # For clarity, explicitly prepare model string and api_base for Ollama if specified
        # This assumes orchestrator_settings.LLM_PROVIDER can be 'ollama'
        # and orchestrator_settings.LLM_BASE_URL is the Ollama server URL.
        
        effective_api_base = self.default_base_url # Start with default

        # A more robust way to handle model prefixing for LiteLLM:
        if effective_provider == "ollama":
             # Handle both ollama/ and ollama_chat/ prefixes
             if current_model_name.startswith("ollama_chat/"):
                # Already has the correct prefix for chat API, use as-is
                llm_call_params["model"] = current_model_name
             elif not current_model_name.startswith("ollama/"): 
                # No prefix, add ollama/ prefix (for generate API)
                llm_call_params["model"] = f"ollama/{current_model_name}"
             else: 
                # Already has ollama/ prefix, use as-is
                llm_call_params["model"] = current_model_name

             # ensure_model_is_pulled=True was not effective, using manual check and pull
             # llm_call_params["ensure_model_is_pulled"] = True 
             if effective_api_base: # Make sure we have a base URL for Ollama
                # Extract the plain model name for Ollama API calls
                plain_model_name = current_model_name.replace("ollama_chat/", "").replace("ollama/", "")
                await self._ensure_ollama_model_available(plain_model_name, effective_api_base)
             else:
                logger.warning(f"Ollama provider selected but no OLLAMA_BASE_URL configured. Model pulling and completions may fail for '{current_model_name}'.")

        
        # If a specific base_url is configured for the default provider (especially for ollama/self-hosted)
        # LiteLLM can take 'api_base' directly in the acompletion call.
        # Or, ensure OLLAMA_API_BASE (for Ollama) or other relevant env vars are set.
        if effective_api_base: # and (effective_provider == "ollama" or other self-hosted):
            llm_call_params["api_base"] = effective_api_base
        
        # If there's a default API key and it's relevant (e.g., not for local Ollama but for a hosted one)
        if self.default_api_key:
            llm_call_params["api_key"] = self.default_api_key


        cancellation_event = self._get_cancellation_event(conversation_id)
        cancellation_event.clear() # Clear event at the start of new generation

        logger.debug(f"Generating LLM response for conv_id {conversation_id} using LiteLLM with params: {llm_call_params}")
        logger.debug(f"Conversation history for LLM ({conversation_id}): {conversation_history}")
        if tools:
            logger.info(f"LLM using {len(tools)} tools for conversation {conversation_id}: {[t['function']['name'] for t in tools]}")
            # Debug: Check function calling support for the actual model being used
            actual_model = llm_call_params["model"]
            logger.info(f"Checking function calling support for actual model being used: {actual_model}")
            logger.info(f"Function calling support for {actual_model}: {litellm.supports_function_calling(actual_model)}")
            logger.info(f"LiteLLM call params: {llm_call_params}")

        _tool_call_assembler: Dict[int, Dict[str, any]] = {} # index -> {id, type, function_name, function_args_buffer}
        _tool_calls_yielded_this_turn: set[str] = set() # Store IDs of tool calls yielded during this assistant turn

        try:
            # Configure tools if provided
            if tools:
                llm_call_params["tools"] = tools
                llm_call_params["tool_choice"] = "auto"

            response_stream:litellm.ModelResponseStream = await litellm.acompletion(**llm_call_params)
            
            async for chunk in response_stream:
                logger.debug(f"LLM Service Raw Chunk: {chunk}") # LOG RAW CHUNK
                if cancellation_event.is_set():
                    logger.info(f"LLM stream for conv_id {conversation_id} cancelled.")
                    if hasattr(response_stream, 'aclose'):
                         await response_stream.aclose()
                    break

                if not chunk.choices:
                    continue
                
                choice = chunk.choices[0]
                delta = choice.delta
                finish_reason = choice.finish_reason
                logger.debug(f"LLM Service Delta: {delta}, Finish Reason: {finish_reason}") # LOG DELTA
                
                # Phase 1: Accumulate tool call parts from the current delta
                if delta.tool_calls:
                    logger.debug(f"LLM Service Delta HAS tool_calls: {delta.tool_calls}") # LOG TOOL_CALLS in DELTA
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in _tool_call_assembler:
                            _tool_call_assembler[idx] = {
                                "id": None, 
                                "type": "function", # Default, can be overridden by tc_delta.type
                                "function": {"name": None, "arguments": ""}
                            }
                        
                        assembler_entry = _tool_call_assembler[idx]
                        if tc_delta.id:
                            assembler_entry["id"] = tc_delta.id
                        if tc_delta.type:
                            assembler_entry["type"] = tc_delta.type
                        
                        if tc_delta.function:
                            if tc_delta.function.name:
                                assembler_entry["function"]["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                assembler_entry["function"]["arguments"] += tc_delta.function.arguments

                # Phase 2: Yield completed tool calls IF the stream indicates a terminal state for them
                # The primary signal for this is finish_reason == 'tool_calls'.
                # Also process if the entire generation is stopping ('stop', 'length'),
                # to catch any fully formed tools that might not have been explicitly
                # signalled by 'tool_calls' (e.g. if model directly goes to 'stop' after tools).
                if finish_reason in ["tool_calls", "stop", "length"]:
                    sorted_indices = sorted(_tool_call_assembler.keys())
                    for idx in sorted_indices:
                        assembled_call = _tool_call_assembler[idx]
                        # Check if essential parts are present and not already yielded this turn
                        if assembled_call["id"] and \
                           assembled_call["function"]["name"] is not None and \
                           assembled_call["id"] not in _tool_calls_yielded_this_turn:
                            
                            # Attempt to parse arguments if they are supposed to be JSON
                            # But keep them as strings for OpenAI compatibility
                            try:
                                # Validate that arguments are valid JSON, but keep as string
                                json.loads(assembled_call["function"]["arguments"])
                                # Arguments are valid JSON - keep as string for OpenAI compatibility
                            except json.JSONDecodeError:
                                # If arguments are not valid JSON, pass them as a raw string.
                                # This might happen if the LLM doesn't format them correctly or if they aren't meant to be JSON.
                                logger.warning(f"Tool call arguments for {assembled_call['function']['name']} (id: {assembled_call['id']}) are not valid JSON. Yielding as raw string: {assembled_call['function']['arguments']}")

                            to_yield = assembled_call.copy() # Yield a copy
                            logger.debug(f"LLM Service YIELDING (assembled tool call - dict): {type(to_yield)} {to_yield}") # LOG YIELDED DICT
                            yield to_yield
                            _tool_calls_yielded_this_turn.add(assembled_call["id"])
                    
                    # Clear the assembler and yielded set after processing for this terminal event,
                    # preparing for a potential next turn of tool calls or end of interaction.
                    _tool_call_assembler.clear()
                    _tool_calls_yielded_this_turn.clear()
                
                # Phase 3: Yield content if any
                # This will handle text responses that might follow tool calls (after 'tool_calls' finish_reason)
                # or direct text responses.
                if delta.content:
                    logger.debug(f"LLM Service Delta HAS content: {delta.content}") # LOG CONTENT in DELTA
                    logger.debug(f"LLM Service YIELDING (content - str): {type(delta.content)} {delta.content}") # LOG YIELDED STR
                    yield delta.content
                            
        except litellm.exceptions.APIConnectionError as e: # Example of specific LiteLLM exception
            logger.error(f"LiteLLM API Connection Error for conv_id {conversation_id}: {e}", exc_info=True)
            if not cancellation_event.is_set():
                yield f"[LLM Error: Connection issues - {str(e)}]"
        except litellm.exceptions.RateLimitError as e: # Example of specific LiteLLM exception
            logger.error(f"LiteLLM Rate Limit Error for conv_id {conversation_id}: {e}", exc_info=True)
            if not cancellation_event.is_set():
                yield f"[LLM Error: Rate limit exceeded - {str(e)}]"
        except litellm.exceptions.ServiceUnavailableError as e: # Example of specific LiteLLM exception
            logger.error(f"LiteLLM Service Unavailable Error for conv_id {conversation_id}: {e}", exc_info=True)
            if not cancellation_event.is_set():
                yield f"[LLM Error: Service unavailable - {str(e)}]"
        except litellm.exceptions.OpenAIError as e: # LiteLLM can also re-raise OpenAI errors
            logger.error(f"Underlying OpenAI API error via LiteLLM for conv_id {conversation_id}: {e}", exc_info=True)
            if not cancellation_event.is_set():
                yield f"[LLM Error: OpenAI API Error - {str(e)}]"
        except Exception as e: # Catch-all for other LiteLLM errors or unexpected issues
            logger.error(f"Error during LiteLLM stream generation for conv_id {conversation_id}: {e}", exc_info=True)
            if not cancellation_event.is_set(): # Don't yield error if cancelled
                yield "[LLM Error: An unexpected error occurred]"
        finally:
            # Clean up the event for this conversation_id if it exists
            if conversation_id in self._cancellation_events:
                del self._cancellation_events[conversation_id]
            logger.debug(f"LLM stream finished or cancelled for conv_id {conversation_id}")

# Example Usage (for testing)
async def _test_llm_service():
    logger.info("Testing LLM Service with LiteLLM...")
    # Mock orchestrator_settings or ensure .env provides necessary LiteLLM configs
    # For Ollama, you might need to set OLLAMA_API_BASE environment variable
    # or ensure default_base_url is correctly picked up if testing Ollama.
    # Example: os.environ["OLLAMA_API_BASE"] = "http://localhost:11434"
    
    # For testing with Ollama, you might set:
    # orchestrator_settings.LLM_PROVIDER = "ollama"
    # orchestrator_settings.LLM_MODEL_NAME = "mistral" # or any model you have pulled in Ollama
    # orchestrator_settings.LLM_BASE_URL = "http://localhost:11434" # LiteLLM uses this as api_base

    service = LLMService()
    history = [
        Message(role="system", content="You are a helpful assistant."),
        Message(role="user", content="Hello, who are you?")
    ]
    async for response_part in service.generate_response_stream("test_conversation", history):
        if isinstance(response_part, str):
            print(f"Token: {response_part}", end="", flush=True)
        elif isinstance(response_part, dict):
            print(f"\nTool Call: {response_part}")
    print("\nLLM Service test finished.")

# if __name__ == "__main__":
#     import asyncio
#     import os # For setting env vars for testing if needed
#     from dotenv import load_dotenv
#     # load_dotenv(dotenv_path="llm_orchestrator/.env") # Ensure .env is loaded
#     # Ensure your .env or environment has OPENAI_API_KEY for OpenAI tests,
#     # or OLLAMA_API_BASE for Ollama tests.
#     # Example for Ollama testing:
#     # os.environ["OLLAMA_API_BASE"] = "http://localhost:11434" 
#     # orchestrator_settings.LLM_PROVIDER = "ollama" # This would need actual setting modification
#     # orchestrator_settings.LLM_MODEL_NAME = "mistral"
#     # orchestrator_settings.LLM_BASE_URL = "http://localhost:11434" 


#     asyncio.run(_test_llm_service()) 