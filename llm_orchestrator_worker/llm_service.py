# Service for interacting with Large Language Models (LLMs)
import json
from typing import AsyncIterator, Dict, List, Optional, Tuple, Union

from openai import AsyncOpenAI, OpenAIError # Using openai as an example client
import httpx # For direct HTTP calls if needed
import asyncio # Added for asyncio.Event

from llm_orchestrator_worker.config import orchestrator_settings
from llm_orchestrator_worker.logging_config import get_logger

logger = get_logger(__name__)

# Define a common structure for conversation history messages
class Message(Dict):
    role: str # "system", "user", "assistant", "tool"
    content: Optional[str] = None
    tool_calls: Optional[List[Dict]] = None # For assistant messages requesting tool calls
    tool_call_id: Optional[str] = None # For tool messages responding to a call

class LLMService:
    def __init__(self):
        self.default_provider = orchestrator_settings.LLM_PROVIDER
        self.default_model_name = orchestrator_settings.LLM_MODEL_NAME
        self.default_api_key = orchestrator_settings.LLM_API_KEY
        self.default_base_url = orchestrator_settings.LLM_BASE_URL
        self.default_max_tokens = orchestrator_settings.LLM_MAX_TOKENS
        self.default_temperature = orchestrator_settings.LLM_TEMPERATURE

        # Initialize a default client, it might be overridden or re-created if base_url/api_key changes per call
        # For providers like OpenAI, the client is lightweight to re-initialize if needed.
        self.aclient = AsyncOpenAI(
            api_key=self.default_api_key,
            base_url=self.default_base_url
        )
        logger.info(f"LLMService initialized with default provider: {self.default_provider}, model: {self.default_model_name}")
        
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

    async def generate_response_stream(
        self,
        conversation_id: str, # Added conversation_id for cancellation
        conversation_history: List[Message],
        model_name_override: Optional[str] = None,
        temperature_override: Optional[float] = None,
        max_tokens_override: Optional[int] = None,
    ) -> AsyncIterator[Union[str, Dict]]:

        current_model_name = model_name_override or self.default_model_name
        current_temperature = temperature_override if temperature_override is not None else self.default_temperature
        current_max_tokens = max_tokens_override or self.default_max_tokens

        cancellation_event = self._get_cancellation_event(conversation_id)
        cancellation_event.clear() # Clear event at the start of new generation

        # TODO: Load actual tool definitions based on conversation_id or global config
        # These would come from MCP client capabilities, translated to LLM tool format.
        # Example tool schema (OpenAI format):
        example_tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get the current weather in a given location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "The city and state, e.g. San Francisco, CA",
                            },
                            "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
                        },
                        "required": ["location"],
                    },
                },
            }
        ]
        # End TODO for tool definitions

        logger.debug(f"Generating LLM response for conv_id {conversation_id} with model: {current_model_name}, temp: {current_temperature}, max_tokens: {current_max_tokens}")
        logger.debug(f"Conversation history for LLM ({conversation_id}): {conversation_history}")

        # Assuming OpenAI compatible API for now
        # if self.default_provider == "openai" or current_base_url:
        try:
            stream = await self.aclient.chat.completions.create(
                model=current_model_name,
                messages=conversation_history,
                temperature=current_temperature,
                max_tokens=current_max_tokens,
                stream=True,
                tools=example_tools, # Pass tool definitions (FR-06)
                tool_choice="auto"   # Let LLM decide if it needs tools (FR-06)
            )
            async for chunk in stream:
                if cancellation_event.is_set():
                    logger.info(f"LLM stream for conv_id {conversation_id} cancelled.")
                    break # Stop iterating if cancellation is signaled

                if not chunk.choices:
                    continue
                
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content
                
                if delta.tool_calls:
                    # Accumulate tool call chunks if they are split
                    # For simplicity here, assume each tool_call in delta.tool_calls is relatively complete
                    # or that the orchestrator will handle further accumulation if needed.
                    for tool_call_chunk in delta.tool_calls:
                        # This structure might need to be built incrementally if function name/args stream separately
                        # For now, send what we have if ID and function name are present
                        if tool_call_chunk.id and tool_call_chunk.function and tool_call_chunk.function.name:
                            tool_call_obj = {
                                "id": tool_call_chunk.id,
                                "type": "function", 
                                "function": {
                                    "name": tool_call_chunk.function.name,
                                    # Arguments might stream. Accumulate if tool_call_chunk.function.arguments is partial.
                                    "arguments": tool_call_chunk.function.arguments or "" 
                                }
                            }
                            yield tool_call_obj 
                        # elif tool_call_chunk.id and tool_call_chunk.function and tool_call_chunk.function.arguments:
                            # This would be a case where only arguments are streaming for an already identified tool call
                            # Needs more complex state management to map argument chunks to the correct tool_call_id
                            # logger.debug(f"Streaming arguments for tool_call_id {tool_call_chunk.id}: {tool_call_chunk.function.arguments}")
                            # yield {"id": tool_call_chunk.id, "type": "function_args_chunk", "arguments_chunk": tool_call_chunk.function.arguments}
                            
        except OpenAIError as e:
            logger.error(f"OpenAI API error for conv_id {conversation_id}: {e}", exc_info=True)
            if not cancellation_event.is_set(): # Don't yield error if cancelled
                yield f"[LLM Error: {str(e)}]"
        except Exception as e:
            logger.error(f"Error during LLM stream generation for conv_id {conversation_id}: {e}", exc_info=True)
            if not cancellation_event.is_set(): # Don't yield error if cancelled
                yield "[LLM Error: An unexpected error occurred]"
        # else:
        #     logger.error(f"LLM provider '{self.default_provider}' not supported or misconfigured for dynamic overrides.")
        #     yield "[LLM Error: Provider not supported for overrides]"
        finally:
            # Clean up the event for this conversation_id if it exists
            if conversation_id in self._cancellation_events:
                del self._cancellation_events[conversation_id]
            logger.debug(f"LLM stream finished or cancelled for conv_id {conversation_id}")

# Example Usage (for testing)
async def _test_llm_service():
    logger.info("Testing LLM Service...")
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
#     from dotenv import load_dotenv
#     load_dotenv(dotenv_path="llm_orchestrator/.env") # Ensure .env is loaded
#     asyncio.run(_test_llm_service()) 