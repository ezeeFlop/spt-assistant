import asyncio
import signal
import json
import time
import redis.asyncio as redis
from dotenv import load_dotenv
from typing import Dict, List, Optional, Union, Any
import nltk
import nltk.tokenize

from llm_orchestrator_worker.config import orchestrator_settings
from llm_orchestrator_worker.logging_config import get_logger
from llm_orchestrator_worker.llm_service import LLMService, Message
from llm_orchestrator_worker.tool_router import ToolRouter

nltk.download('punkt')
# Load .env file
load_dotenv(dotenv_path="llm_orchestrator/.env")

logger = get_logger(__name__)
running = True

# In-memory store for conversation histories removed
# conversation_histories: Dict[str, List[Message]] = {}

async def get_conversation_config(conversation_id: str, redis_client: redis.Redis) -> Dict[str, Any]:
    """Fetches conversation-specific configuration from Redis."""
    config_key = f"{orchestrator_settings.CONVERSATION_CONFIG_PREFIX}{conversation_id}"
    config_json = await redis_client.get(config_key)
    if config_json:
        return json.loads(config_json)
    return {} # Return empty dict if no specific config found

async def get_conversation_history(conversation_id: str, redis_client: redis.Redis) -> List[Message]:
    """Fetches conversation history from Redis."""
    history_key = f"{orchestrator_settings.CONVERSATION_HISTORY_PREFIX}{conversation_id}"
    history_json = await redis_client.get(history_key)
    if history_json:
        try:
            # Ensure messages are loaded as Message type (or dicts that conform)
            # Since Message is a class inheriting from Dict, direct instantiation is fine.
            return [Message(**msg) for msg in json.loads(history_json)]
        except json.JSONDecodeError:
            logger.error(f"Failed to decode conversation history for {conversation_id} from Redis.")
            return [] # Return empty list on decode error
    return []

async def save_conversation_history(conversation_id: str, history: List[Dict], redis_client: redis.Redis):
    """Saves conversation history to Redis with TTL."""
    history_key = f"{orchestrator_settings.CONVERSATION_HISTORY_PREFIX}{conversation_id}"
    # History should now be a list of dicts, ready for JSON serialization.
    await redis_client.set(history_key, json.dumps(history), ex=orchestrator_settings.CONVERSATION_DATA_TTL_SECONDS)

async def process_llm_interaction(transcript_data: Dict, llm_service: LLMService, tool_router: ToolRouter, redis_client: redis.Redis):
    conversation_id = transcript_data.get("conversation_id")
    user_text = transcript_data.get("transcript")

    if not conversation_id or not user_text:
        logger.warning(f"Received transcript data without conversation_id or text: {transcript_data}")
        return

    logger.info(f"Processing transcript for conv_id '{conversation_id}': '{user_text}'")

    conv_config = await get_conversation_config(conversation_id, redis_client)
    history = await get_conversation_history(conversation_id, redis_client)

    current_llm_model = conv_config.get("llm_model_name", orchestrator_settings.LLM_MODEL_NAME)
    # Get other overrides or use defaults
    current_temperature = conv_config.get("llm_temperature", orchestrator_settings.LLM_TEMPERATURE) # Assuming llm_temperature can be in config
    current_max_tokens = conv_config.get("llm_max_tokens", orchestrator_settings.LLM_MAX_TOKENS) # Assuming llm_max_tokens can be in config
    
    logger.debug(f"Using LLM params for conv_id '{conversation_id}': Model={current_llm_model}, Temp={current_temperature}, MaxTokens={current_max_tokens}")

    # Check for cancellation before starting LLM stream
    # This is a soft check; the primary cancellation is within the LLM stream itself.
    cancellation_event_for_llm = llm_service._get_cancellation_event(conversation_id) # Accessing 'private' for direct check
    if cancellation_event_for_llm.is_set():
        logger.info(f"LLM interaction for conv_id '{conversation_id}' was cancelled before starting stream.")
        return

    if not history:
        history.append(Message(role="system", content="You are a helpful French voice assistant, your name is TARA. Make sure to NEVER generate MARKDOWN or HTML code in your responses."))
    history.append(Message(role="user", content=user_text))

    if len(history) > orchestrator_settings.MAX_CONVERSATION_HISTORY * 2:
        history = [history[0]] + history[-(orchestrator_settings.MAX_CONVERSATION_HISTORY * 2 - 1):]

    max_tool_recursion = 5
    current_tool_recursion = 0

    # Helper function to send sentences to TTS
    async def _send_sentence_to_tts(sentence: str, conv_id: str, config: Dict, client: redis.Redis):
        if sentence and sentence.strip():
            tts_req_message = {
                "text_to_speak": sentence.strip(),
                "conversation_id": conv_id,
                "voice_id": config.get("tts_voice_id", orchestrator_settings.DEFAULT_TTS_VOICE_ID if hasattr(orchestrator_settings, 'DEFAULT_TTS_VOICE_ID') else None)
            }
            await client.publish(orchestrator_settings.TTS_REQUEST_CHANNEL, json.dumps(tts_req_message))
            logger.info(f"Published TTS request for conv_id '{conv_id}': '{sentence.strip()}'")

    # Attempt to download nltk.punkt if not available, with a flag to prevent repeated attempts per run
    if not hasattr(process_llm_interaction, '_punkt_download_attempted'):
        try:
            nltk.data.find('tokenizers/punkt')
        except nltk.downloader.DownloadError:
            logger.warning("NLTK 'punkt' tokenizer not found. Attempting to download...")
            try:
                nltk.download('punkt', quiet=True)
                logger.info("NLTK 'punkt' tokenizer downloaded successfully.")
            except Exception as e:
                logger.error(f"Failed to download NLTK 'punkt' tokenizer: {e}. Sentence tokenization for TTS might fail.", exc_info=True)
        except LookupError: # Handles cases where nltk.data.find itself fails if punkt is missing from default paths
            logger.warning("NLTK 'punkt' tokenizer not found (LookupError). Attempting to download...")
            try:
                nltk.download('punkt', quiet=True)
                logger.info("NLTK 'punkt' tokenizer downloaded successfully.")
            except Exception as e:
                logger.error(f"Failed to download NLTK 'punkt' tokenizer: {e}. Sentence tokenization for TTS might fail.", exc_info=True)
        setattr(process_llm_interaction, '_punkt_download_attempted', True)

    while current_tool_recursion < max_tool_recursion:
        assistant_response_content = ""
        active_tool_calls: List[Dict] = []
        sentence_buffer = ""
        punkt_available = True # Assume available unless a LookupError occurs

        try:
            nltk.data.find('tokenizers/punkt')
        except (nltk.downloader.DownloadError, LookupError):
            logger.warning("NLTK 'punkt' tokenizer not available during LLM interaction. TTS will be sent at the end of the full response if no tool calls are made, or not at all for intermediate text before tool calls if 'punkt' is missing.")
            punkt_available = False
        
        async for response_part in llm_service.generate_response_stream(
            conversation_id, # Pass conversation_id
            history,
            model_name_override=current_llm_model,
            temperature_override=current_temperature,
            max_tokens_override=current_max_tokens
        ):
            if isinstance(response_part, str): # Token
                assistant_response_content += response_part # Accumulate full response for history
                
                if punkt_available:
                    sentence_buffer += response_part
                    try:
                        sentences = nltk.tokenize.sent_tokenize(sentence_buffer)
                        if sentences:
                            for i, sentence in enumerate(sentences):
                                if i < len(sentences) - 1: # It's a complete sentence
                                    await _send_sentence_to_tts(sentence, conversation_id, conv_config, redis_client)
                                    sentence_buffer = sentence_buffer.replace(sentence, "", 1).lstrip() # Remove sent part
                                else: # Last part, might be incomplete
                                    # If the original buffer ended with sentence-ending punctuation,
                                    # this last part is also a complete sentence.
                                    if sentence_buffer.strip() == sentence.strip() and any(sentence_buffer.endswith(p) for p in ['.', '!', '?']):
                                        await _send_sentence_to_tts(sentence, conversation_id, conv_config, redis_client)
                                        sentence_buffer = ""
                                    else: # It's a fragment, keep it
                                        sentence_buffer = sentence 
                    except LookupError:
                        # This should ideally be caught by the check before the loop,
                        # but as a safeguard if punkt disappears mid-process or initial check fails.
                        if punkt_available: # Log only once per interaction if it becomes unavailable
                           logger.warning(f"NLTK 'punkt' tokenizer not found during streaming for conv_id '{conversation_id}'. Will accumulate response and send to TTS at the end if no tools, or not for partials.")
                        punkt_available = False
                        # Fallback: just accumulate if punkt is not available.
                        # No sentence-by-sentence TTS if punkt is missing.
                else: # punkt not available, just accumulate
                    sentence_buffer += response_part

                # Publish token to Redis (existing logic)
                token_message = {"type": "token", "role": "assistant", "content": response_part, "conversation_id": conversation_id}
                await redis_client.publish(orchestrator_settings.LLM_TOKEN_CHANNEL, json.dumps(token_message))

            elif isinstance(response_part, dict): # Tool call
                logger.info(f"LLM requested tool call for conv_id '{conversation_id}': {response_part}")
                # Flush any remaining text in sentence_buffer to TTS before tool call
                if sentence_buffer.strip():
                    await _send_sentence_to_tts(sentence_buffer, conversation_id, conv_config, redis_client)
                    sentence_buffer = "" # Clear buffer after flushing

                active_tool_calls.append(response_part)
                tool_status_msg = {
                    "type": "tool", "name": response_part.get("function", {})["name"], 
                    "status": "running", "conversation_id": conversation_id
                }
                await redis_client.publish(orchestrator_settings.LLM_TOOL_CALL_CHANNEL, json.dumps(tool_status_msg))
        
        # After stream, if there's remaining text in sentence_buffer and no tool calls, send it to TTS
        if sentence_buffer.strip() and not active_tool_calls:
            await _send_sentence_to_tts(sentence_buffer, conversation_id, conv_config, redis_client)
            sentence_buffer = "" # Clear buffer

        if assistant_response_content.strip() or active_tool_calls:
            assistant_message = Message(role="assistant", content=assistant_response_content.strip() or None)
            if active_tool_calls:
                assistant_message["tool_calls"] = active_tool_calls
            history.append(assistant_message)

        if not active_tool_calls:
            if assistant_response_content.strip():
                # TTS request is now handled by sentence-by-sentence logic or final buffer flush above.
                # The original full response TTS publish is removed from here.
                # tts_req_message = {
                #     "text_to_speak": assistant_response_content.strip(), 
                #     "conversation_id": conversation_id,
                #     "voice_id": conv_config.get("tts_voice_id", orchestrator_settings.DEFAULT_TTS_VOICE_ID if hasattr(orchestrator_settings, 'DEFAULT_TTS_VOICE_ID') else None) 
                # }
                # await redis_client.publish(orchestrator_settings.TTS_REQUEST_CHANNEL, json.dumps(tts_req_message))
                # logger.info(f"Published TTS request for conv_id '{conversation_id}': '{assistant_response_content.strip()}'")
                pass # Ensure this block doesn't cause syntax error if all content is removed.
            break

        tool_results: List[Message] = []
        for tool_call_request in active_tool_calls:
            tool_call_id = tool_call_request["id"]
            function_spec = tool_call_request.get("function", {})
            tool_name = function_spec.get("name")
            tool_args_str = function_spec.get("arguments", "{}")
            if not tool_name:
                logger.error(f"Tool call request missing function name for conv_id '{conversation_id}': {tool_call_request}")
                tool_results.append(Message(tool_call_id=tool_call_id, role="tool", name="unknown", content=json.dumps({"error": "Missing tool name."})))
                continue
            tool_dispatch_result = await tool_router.dispatch_tool_call(tool_call_id, tool_name, tool_args_str)
            tool_results.append(Message(**tool_dispatch_result))
            tool_status_msg = {
                "type": "tool", "name": tool_name, 
                "status": "completed" if "error" not in json.loads(tool_dispatch_result["content"]) else "failed",
                "conversation_id": conversation_id, "tool_id": tool_call_id, 
                "result": json.loads(tool_dispatch_result["content"])
            }
            await redis_client.publish(orchestrator_settings.LLM_TOOL_CALL_CHANNEL, json.dumps(tool_status_msg))
        history.extend(tool_results)
        current_tool_recursion += 1
        if current_tool_recursion >= max_tool_recursion:
            logger.warning(f"Max tool recursion depth for conv_id '{conversation_id}'")
            error_summary = "[Tool processing limit reached]"
            # Send this specific error summary to TTS
            await _send_sentence_to_tts(error_summary, conversation_id, conv_config, redis_client)
            # Original TTS publish for error_summary removed as it's handled by _send_sentence_to_tts
            # tts_req_message = {"text_to_speak": error_summary, "conversation_id": conversation_id, "voice_id": conv_config.get("tts_voice_id", orchestrator_settings.DEFAULT_TTS_VOICE_ID if hasattr(orchestrator_settings, 'DEFAULT_TTS_VOICE_ID') else None)}
            # await redis_client.publish(orchestrator_settings.TTS_REQUEST_CHANNEL, json.dumps(tts_req_message))
            break
    # Ensure history is saved with Message model instances or dicts that can be serialized
    serializable_history = []
    for item in history:
        if isinstance(item, Message):
            # Message inherits from Dict, so it's already dict-like.
            # To be absolutely sure it's a plain dict for JSON serialization:
            serializable_history.append(dict(item))
        elif isinstance(item, dict): # Already a dict, ensure it's suitable
            serializable_history.append(item)
        else:
            logger.warning(f"Unexpected item type in history for conv_id '{conversation_id}': {type(item)}. Skipping serialization for this item.")

    await save_conversation_history(conversation_id, serializable_history, redis_client)

async def subscribe_to_transcripts(redis_client: redis.Redis, llm_service: LLMService, tool_router: ToolRouter):
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(orchestrator_settings.TRANSCRIPT_CHANNEL)
    logger.info(f"LLM Orchestrator subscribed to Redis channel: {orchestrator_settings.TRANSCRIPT_CHANNEL}")

    global running
    while running:
        try:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if message and message["type"] == "message":
                transcript_data_str = message["data"].decode('utf-8')
                logger.debug(f"Orchestrator received transcript data: {transcript_data_str}")
                try:
                    transcript_data = json.loads(transcript_data_str)
                    if transcript_data.get("type") == "final_transcript" and transcript_data.get("conversation_id"):
                        asyncio.create_task(process_llm_interaction(transcript_data, llm_service, tool_router, redis_client))
                    elif not transcript_data.get("conversation_id"):
                        logger.warning(f"Transcript message missing conversation_id: {transcript_data_str}")
                    else: # Partial transcript
                        logger.debug(f"Skipping partial transcript for LLM: {transcript_data_str}")
                except json.JSONDecodeError:
                    logger.error(f"Error decoding transcript JSON: {transcript_data_str}", exc_info=True)
            elif message is None: 
                await asyncio.sleep(0.01)
        except redis.exceptions.ConnectionError as e:
            logger.error(f"Redis connection error in orchestrator: {e}. Retrying...", exc_info=True)
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Error in orchestrator subscription loop: {e}", exc_info=True)
            await asyncio.sleep(1)
    
    await pubsub.unsubscribe(orchestrator_settings.TRANSCRIPT_CHANNEL)
    await pubsub.close()
    logger.info("Orchestrator unsubscribed and closed pubsub for transcripts.")

async def subscribe_to_barge_in_notifications(redis_client: redis.Redis, llm_service: LLMService):
    """Subscribes to barge-in notifications and triggers cancellations."""
    pubsub = redis_client.pubsub()
    # Note: BARGE_IN_CHANNEL should come from vad_stt_worker settings if distinct, or be a shared config.
    # Using orchestrator_settings assuming it's defined there for listening.
    barge_in_channel = orchestrator_settings.BARGE_IN_CHANNEL 
    await pubsub.subscribe(barge_in_channel)
    logger.info(f"LLM Orchestrator subscribed to Barge-in channel: {barge_in_channel}")

    global running
    while running:
        try:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if message and message["type"] == "message":
                barge_in_data_str = message["data"].decode('utf-8')
                logger.info(f"Orchestrator received barge-in data: {barge_in_data_str}")
                try:
                    barge_in_data = json.loads(barge_in_data_str)
                    conversation_id = barge_in_data.get("conversation_id")
                    if barge_in_data.get("type") == "barge_in_detected" and conversation_id:
                        logger.info(f"User interruption (barge-in) detected for conv_id: {conversation_id}. Cancelling LLM and TTS.")
                        
                        # 1. Cancel LLM generation stream for this conversation_id
                        llm_service.cancel_generation(conversation_id)
                        
                        # 2. Signal TTS Service to stop playback for this conversation_id
                        tts_stop_message = {
                            "command": "stop_tts",
                            "conversation_id": conversation_id
                        }
                        await redis_client.publish(orchestrator_settings.TTS_CONTROL_CHANNEL, json.dumps(tts_stop_message))
                        logger.info(f"Published stop_tts command to {orchestrator_settings.TTS_CONTROL_CHANNEL} for conv_id {conversation_id}")
                        
                        # Optional: Clear last user message that led to interrupted TTS? Or parts of history?
                        # For now, just stopping generation and playback.
                                                
                except json.JSONDecodeError:
                    logger.error(f"Error decoding barge-in JSON: {barge_in_data_str}", exc_info=True)
            elif message is None: 
                await asyncio.sleep(0.01)
        except redis.exceptions.ConnectionError as e:
            logger.error(f"Redis connection error in orchestrator (barge-in sub): {e}. Retrying...", exc_info=True)
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Error in orchestrator barge-in subscription loop: {e}", exc_info=True)
            await asyncio.sleep(1)
    
    await pubsub.unsubscribe(barge_in_channel)
    await pubsub.close()
    logger.info(f"Orchestrator unsubscribed and closed pubsub for barge-in channel: {barge_in_channel}.")

def signal_handler_orchestrator(signum, frame):
    global running
    logger.info(f"Signal {signum} received by orchestrator, shutting down...")
    running = False

async def main_async_orchestrator():
    signal.signal(signal.SIGINT, signal_handler_orchestrator)
    signal.signal(signal.SIGTERM, signal_handler_orchestrator)
    logger.info("Starting LLM Orchestrator...")
    redis_client = None
    transcript_subscriber_task = None # Added for tracking
    barge_in_subscriber_task = None # Added for tracking
    try:
        redis_client = redis.Redis(
            host=orchestrator_settings.REDIS_HOST,
            port=orchestrator_settings.REDIS_PORT,
            db=orchestrator_settings.REDIS_DB,
            password=orchestrator_settings.REDIS_PASSWORD,
            auto_close_connection_pool=False # Keep pool open for tasks
        )
        await redis_client.ping()
        logger.info("Orchestrator connected to Redis.")
        llm_service_instance = LLMService()
        tool_router_instance = ToolRouter()
        
        transcript_subscriber_task = asyncio.create_task(
            subscribe_to_transcripts(redis_client, llm_service_instance, tool_router_instance)
        )
        barge_in_subscriber_task = asyncio.create_task(
            subscribe_to_barge_in_notifications(redis_client, llm_service_instance)
        )
        
        logger.info("LLM Orchestrator has started successfully and is now processing.")

        await asyncio.gather(
            transcript_subscriber_task,
            barge_in_subscriber_task
        )

    except ConnectionRefusedError as e:
        logger.critical(f"Orchestrator could not connect to Redis: {e}. Service cannot start.", exc_info=True)
    except RuntimeError as e:
        logger.critical(f"Orchestrator runtime error during initialization: {e}. Service cannot start.", exc_info=True)
    except Exception as e:
        logger.critical(f"Unexpected critical error in orchestrator: {e}", exc_info=True)
    finally:
        logger.info("LLM Orchestrator shutting down...")
        global running # Ensure running is set to false to stop loops
        running = False
        if transcript_subscriber_task: transcript_subscriber_task.cancel()
        if barge_in_subscriber_task: barge_in_subscriber_task.cancel()
        # Wait for tasks to cancel (optional, depends on task cleanup needs)
        # if transcript_subscriber_task or barge_in_subscriber_task:
        #    await asyncio.sleep(0.5) 
            
        # LLMService active stream cancellations are handled by its own logic (event set, then del on finally)
        # but good to log if any events remain, though unlikely if tasks are cancelled.
        if hasattr(llm_service_instance, '_cancellation_events') and llm_service_instance._cancellation_events:
            logger.info(f"LLM Orchestrator shutdown: {len(llm_service_instance._cancellation_events)} cancellation events still registered. This is unexpected if tasks were properly cancelled.")

        if redis_client:
            # Ensure tasks spawned by process_llm_interaction have a chance to complete or be cancelled gracefully.
            # This might involve tracking tasks or using a more sophisticated shutdown.
            # For now, we just close the client.
            logger.info("Closing orchestrator Redis client...")
            await redis_client.close()
            logger.info("Orchestrator Redis client closed.")
        logger.info("LLM Orchestrator has shut down.")

def main():
    try:
        asyncio.run(main_async_orchestrator())
    except KeyboardInterrupt:
        logger.info("Orchestrator KeyboardInterrupt. Exiting.")

if __name__ == "__main__":
    main() 