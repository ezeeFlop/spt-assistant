import asyncio
import uuid
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query, HTTPException, status
from app.core.logging_config import get_logger
from app.services.redis_service import redis_service, RedisService
from app.core.config import settings
from app.core.auth import get_current_user_ws
import json
from starlette.websockets import WebSocketState
from redis.exceptions import ConnectionError as RedisConnectionError
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError
from typing import Dict, List, Any
from logging import getLogger
logger = getLogger(__name__)

router = APIRouter()

# Store active WebSocket connections with their conversation_id
# This is a simplified in-memory approach. For multi-instance gateways, a shared store (e.g., Redis) would be needed.
active_connections: Dict[str, WebSocket] = {}

async def receive_audio_from_client(
    websocket: WebSocket, conversation_id: str, redis_service_instance: RedisService
):
    """
    Receives audio bytes from the client, packages them with conversation_id,
    and publishes to AUDIO_STREAM_CHANNEL.
    Client is expected to send audio data as raw PCM, 16-bit signed
    little-endian (s16le), 16kHz, 1-channel audio. (FR-01)
    """
    try:
        while True:
            data = await websocket.receive_bytes()
            if not data:
                logger.info(f"Receive_audio: Received empty bytes from client for conv_id {conversation_id}.")
                continue
            
            logger.debug(f"Gateway received {len(data)} bytes of audio data for conv_id {conversation_id}.")
            audio_message = {
                "conversation_id": conversation_id,
                "audio_data": data.hex() # Sending bytes as hex string in JSON
            }
            try:
                await redis_service_instance.publish_message(settings.AUDIO_STREAM_CHANNEL, json.dumps(audio_message))
                logger.debug(f"Gateway published audio message to {settings.AUDIO_STREAM_CHANNEL} for conv_id {conversation_id}")
            except Exception as e:
                logger.error(f"Gateway: Failed to publish audio data to Redis for conv_id {conversation_id}: {e}", exc_info=True)
    except WebSocketDisconnect:
        logger.info(f"receive_audio_from_client: WebSocket disconnected for conv_id {conversation_id}.")
    except Exception as e:
        logger.error(f"receive_audio_from_client: Unexpected error for conv_id {conversation_id}: {e}", exc_info=True)

async def forward_transcripts_to_client(websocket: WebSocket, conversation_id: str):
    """Subscribes to Redis transcript channel and forwards to specific client if conversation_id matches."""
    pubsub_client: Any = None # Using Any for redis pubsub client type
    try:
        r_client = await redis_service.get_redis_client()
        pubsub_client = r_client.pubsub()
        await pubsub_client.subscribe(settings.TRANSCRIPT_CHANNEL)
        logger.info(f"Gateway subscribed to {settings.TRANSCRIPT_CHANNEL} for potential msgs for conv_id {conversation_id}")

        while True:
            if websocket.client_state != WebSocketState.CONNECTED:
                 logger.warning(f"Forward_transcripts: WebSocket no longer connected for conv_id {conversation_id}. Stopping.")
                 break

            message = await pubsub_client.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if message and message["type"] == "message":
                transcript_payload_str = message["data"].decode('utf-8')
                logger.debug(f"Gateway received transcript payload from Redis: {transcript_payload_str}")
                try:
                    transcript_json = json.loads(transcript_payload_str)
                    if transcript_json.get("conversation_id") == conversation_id:
                        await websocket.send_json(transcript_json)
                        logger.debug(f"Gateway forwarded transcript to client for conv_id {conversation_id}: type '{transcript_json.get('type')}'")
                    else:
                        logger.debug(f"Gateway: Ignored transcript for conv_id {transcript_json.get('conversation_id')} (current: {conversation_id})")
                except json.JSONDecodeError as e:
                    logger.error(f"Gateway: Error decoding transcript JSON from Redis: {e} - Data: {transcript_payload_str}")
                except Exception as e:
                    logger.error(f"Gateway: Error forwarding transcript to client for conv_id {conversation_id}: {e}", exc_info=True)
                    break 
            elif message is None:
                await asyncio.sleep(0.01)

    except WebSocketDisconnect:
        logger.info(f"Forward_transcripts: WebSocket disconnected for conv_id {conversation_id}.")
    except RedisConnectionError as e:
        logger.error(f"Forward_transcripts: Redis connection error for conv_id {conversation_id}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Forward_transcripts: Unexpected error for conv_id {conversation_id}: {e}", exc_info=True)
    finally:
        if pubsub_client:
            try:
                logger.info(f"Gateway unsubscribing from {settings.TRANSCRIPT_CHANNEL} for conv_id {conversation_id}")
                await pubsub_client.unsubscribe(settings.TRANSCRIPT_CHANNEL)
                await pubsub_client.close()
            except Exception as e:
                logger.error(f"Gateway: Error during pubsub cleanup for {settings.TRANSCRIPT_CHANNEL} for conv_id {conversation_id}: {e}", exc_info=True)
        logger.info(f"forward_transcripts_to_client: Stopped for conv_id {conversation_id}")

async def forward_llm_tokens_to_client(websocket: WebSocket, conversation_id: str):
    """Subscribes to Redis LLM token channel and forwards to client if conversation_id matches."""
    pubsub_client: Any = None
    try:
        r_client = await redis_service.get_redis_client()
        pubsub_client = r_client.pubsub()
        await pubsub_client.subscribe(settings.LLM_TOKEN_CHANNEL)
        logger.info(f"Gateway subscribed to {settings.LLM_TOKEN_CHANNEL} for conv_id {conversation_id}")
        while True:
            if websocket.client_state != WebSocketState.CONNECTED:
                logger.warning(f"Forward_tokens: WS no longer connected for conv_id {conversation_id}.")
                break
            message = await pubsub_client.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if message and message["type"] == "message":
                payload_str = message["data"].decode('utf-8')
                try:
                    payload_json = json.loads(payload_str)
                    if payload_json.get("conversation_id") == conversation_id:
                        await websocket.send_json(payload_json) # type: "token", role: "assistant", content: "...", conv_id
                        logger.debug(f"Gateway forwarded LLM token to client for conv_id {conversation_id}: {payload_json.get('content')[:30]}...")
                except Exception as e:
                    logger.error(f"Gateway: Error processing/forwarding LLM token for conv_id {conversation_id}: {e} - Data: {payload_str}", exc_info=True)
            elif message is None: await asyncio.sleep(0.01)
    except Exception as e:
        logger.error(f"Forward_tokens: Unexpected error for conv_id {conversation_id}: {e}", exc_info=True)
    finally:
        if pubsub_client: # Ensure cleanup
            try: await pubsub_client.unsubscribe(settings.LLM_TOKEN_CHANNEL); await pubsub_client.close()
            except Exception: pass
        logger.info(f"forward_llm_tokens_to_client: Stopped for conv_id {conversation_id}")

async def forward_tool_calls_to_client(websocket: WebSocket, conversation_id: str):
    """Subscribes to Redis LLM tool call channel and forwards to client if conversation_id matches."""
    pubsub_client: Any = None
    try:
        r_client = await redis_service.get_redis_client()
        pubsub_client = r_client.pubsub()
        await pubsub_client.subscribe(settings.LLM_TOOL_CALL_CHANNEL)
        logger.info(f"Gateway subscribed to {settings.LLM_TOOL_CALL_CHANNEL} for conv_id {conversation_id}")
        while True:
            if websocket.client_state != WebSocketState.CONNECTED:
                logger.warning(f"Forward_tools: WS no longer connected for conv_id {conversation_id}.")
                break
            message = await pubsub_client.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if message and message["type"] == "message":
                payload_str = message["data"].decode('utf-8')
                try:
                    payload_json = json.loads(payload_str)
                    if payload_json.get("conversation_id") == conversation_id:
                        await websocket.send_json(payload_json) # type: "tool", name: "...", status: "running"/"completed"/"failed", conv_id, [result]
                        logger.debug(f"Gateway forwarded LLM tool status to client for conv_id {conversation_id}: Name: {payload_json.get('name')}, Status: {payload_json.get('status')}")
                except Exception as e:
                    logger.error(f"Gateway: Error processing/forwarding LLM tool status for conv_id {conversation_id}: {e} - Data: {payload_str}", exc_info=True)
            elif message is None: await asyncio.sleep(0.01)
    except Exception as e:
        logger.error(f"Forward_tools: Unexpected error for conv_id {conversation_id}: {e}", exc_info=True)
    finally:
        if pubsub_client: # Ensure cleanup
            try: 
                await pubsub_client.unsubscribe(settings.LLM_TOOL_CALL_CHANNEL)
                await pubsub_client.close()
            except Exception as e_cleanup: 
                 logger.error(f"Forward_tools: Error during pubsub cleanup for conv_id {conversation_id}: {e_cleanup}", exc_info=True)
        logger.info(f"forward_tool_calls_to_client: Stopped for conv_id {conversation_id}")

async def forward_tts_audio_to_client(websocket: WebSocket, conversation_id: str):
    """Subscribes to Redis TTS audio output channel and streams audio bytes to client."""
    pubsub_client: Any = None
    audio_output_channel = settings.AUDIO_OUTPUT_STREAM_CHANNEL_PATTERN.format(conversation_id=conversation_id)
    try:
        r_client = await redis_service.get_redis_client()
        pubsub_client = r_client.pubsub()
        await pubsub_client.subscribe(audio_output_channel)
        logger.info(f"Gateway subscribed to {audio_output_channel} for TTS audio for conv_id {conversation_id}")

        first_chunk_received = False
        while True:
            if websocket.client_state != WebSocketState.CONNECTED:
                logger.warning(f"Forward_tts_audio: WS no longer connected for conv_id {conversation_id}.")
                break
            
            message = await pubsub_client.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if message and message["type"] == "message":
                logger.info(f"Gateway RAW MSG from Redis for conv {conversation_id} on {audio_output_channel}: TYPE={type(message['data'])}, DATA='{str(message['data'])[:200]}...'") # Modified log for brevity

                data_from_redis = message["data"]
                is_control_message = False
                parsed_control_message = None # Renamed to avoid conflict with outer scope if any

                if isinstance(data_from_redis, bytes):
                    try:
                        decoded_data = data_from_redis.decode('utf-8')
                        # Try to parse it as JSON directly. If it's not JSON, it's an audio chunk or error.
                        parsed_control_message = json.loads(decoded_data)
                        # If parsing succeeded, it's a control message.
                        is_control_message = True
                        logger.info(f"Gateway DECODED AND PARSED byte message from Redis as JSON control message for conv {conversation_id}: {parsed_control_message}")
                    except UnicodeDecodeError:
                        # Not valid UTF-8, treat as a raw audio chunk (will be handled by the later `isinstance(data_from_redis, bytes)` check)
                        logger.debug(f"Gateway received bytes from Redis (not UTF-8 decodable), treating as audio chunk for conv {conversation_id}.")
                    except json.JSONDecodeError:
                        # Decoded to string, but not valid JSON. Treat as raw audio chunk.
                        logger.debug(f"Gateway received bytes from Redis (UTF-8 decodable but not JSON), treating as audio chunk for conv {conversation_id}: {decoded_data[:100]}...")
                
                elif isinstance(data_from_redis, str):
                    try:
                        parsed_control_message = json.loads(data_from_redis)
                        is_control_message = True
                        logger.info(f"Gateway PARSED string message from Redis as JSON control message for conv {conversation_id}: {parsed_control_message}")
                    except json.JSONDecodeError:
                        logger.error(f"Gateway: Could not decode string message from Redis as JSON: {data_from_redis[:100]} for conv {conversation_id}")
                        # This is an error, it was a string but not the JSON we expected.

                if is_control_message and parsed_control_message:
                    msg_type = parsed_control_message.get("type")
                    # Log the full parsed_control_message IF it's an audio_stream_start
                    if msg_type == "audio_stream_start":
                        logger.info(f"Gateway: Preparing to forward AUDIO_STREAM_START: {parsed_control_message}")

                    if msg_type in ["audio_stream_start", "audio_stream_end", "audio_stream_error"]:
                        if parsed_control_message.get("conversation_id") == conversation_id:
                            await websocket.send_json(parsed_control_message)
                            # logger.info(f"Gateway forwarded TTS control message to client for conv_id {conversation_id}: {parsed_control_message}") # This log is a bit redundant now with the one above
                        # else: No log here, conversation_id mismatch handled by tts-worker or ignored by client
                    else:
                        logger.warning(f"Gateway received known JSON, but unknown control message type: {msg_type} for conv_id {conversation_id}. Original data: {str(data_from_redis)[:100]}")
                
                elif isinstance(data_from_redis, bytes): # Only if it wasn't successfully parsed as a control message above
                    if not first_chunk_received: # For logging the first actual audio chunk
                        logger.info(f"Gateway: Sending first audio chunk ({len(data_from_redis)} bytes) for conv_id {conversation_id} to client.")
                        first_chunk_received = True
                    await websocket.send_bytes(data_from_redis)
                    logger.debug(f"Gateway forwarded TTS audio chunk ({len(data_from_redis)} bytes) to client for conv_id {conversation_id}")
                
                else: # Neither a successfully parsed control message nor raw bytes.
                    logger.warning(f"Gateway received unexpected data type from Redis on TTS audio channel for conv_id {conversation_id}: {type(data_from_redis)}, Data: {str(data_from_redis)[:100]}")

            elif message is None: 
                await asyncio.sleep(0.01)

    except Exception as e:
        logger.error(f"Forward_tts_audio: Unexpected error for conv_id {conversation_id}: {e}", exc_info=True)
    finally:
        if pubsub_client:
            try: 
                await pubsub_client.unsubscribe(audio_output_channel)
                await pubsub_client.close()
            except Exception as e_cleanup: 
                 logger.error(f"Forward_tts_audio: Error during pubsub cleanup for conv_id {conversation_id}: {e_cleanup}", exc_info=True)
        logger.info(f"forward_tts_audio_to_client: Stopped for conv_id {conversation_id}")

async def forward_barge_in_notifications_to_client(websocket: WebSocket, conversation_id: str):
    """Subscribes to Redis barge-in channel and forwards notifications to client if conversation_id matches."""
    pubsub_client: Any = None
    try:
        r_client = await redis_service.get_redis_client()
        pubsub_client = r_client.pubsub()
        await pubsub_client.subscribe(settings.BARGE_IN_CHANNEL)
        logger.info(f"Gateway subscribed to {settings.BARGE_IN_CHANNEL} for barge-in events for conv_id {conversation_id}")

        while True:
            if websocket.client_state != WebSocketState.CONNECTED:
                logger.warning(f"Forward_barge_in: WS no longer connected for conv_id {conversation_id}.")
                break
            
            message = await pubsub_client.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if message and message["type"] == "message":
                payload_str = message["data"].decode('utf-8')
                logger.debug(f"Gateway received barge-in payload from Redis: {payload_str} for conv_id {conversation_id}")
                try:
                    payload_json = json.loads(payload_str)
                    if payload_json.get("conversation_id") == conversation_id:
                        # Forward a specific message type for barge-in
                        barge_in_message = {
                            "type": "barge_in_notification",
                            "conversation_id": conversation_id,
                            "timestamp_ms": payload_json.get("timestamp_ms") # Forward original timestamp
                        }
                        await websocket.send_json(barge_in_message)
                        logger.info(f"Gateway forwarded barge_in_notification to client for conv_id {conversation_id}")
                    # else: No need to log ignored messages for other conversations, handled by Redis distribution
                except json.JSONDecodeError as e:
                    logger.error(f"Gateway: Error decoding barge-in JSON from Redis: {e} - Data: {payload_str} for conv_id {conversation_id}")
                except Exception as e:
                    logger.error(f"Gateway: Error processing/forwarding barge-in for conv_id {conversation_id}: {e}", exc_info=True)
                    # Potentially break or continue based on error severity
            elif message is None:
                await asyncio.sleep(0.01)
    except Exception as e:
        logger.error(f"Forward_barge_in: Unexpected error for conv_id {conversation_id}: {e}", exc_info=True)
    finally:
        if pubsub_client:
            try:
                await pubsub_client.unsubscribe(settings.BARGE_IN_CHANNEL)
                await pubsub_client.close()
            except Exception as e_cleanup:
                logger.error(f"Forward_barge_in: Error during pubsub cleanup for conv_id {conversation_id}: {e_cleanup}", exc_info=True)
        logger.info(f"forward_barge_in_notifications_to_client: Stopped for conv_id {conversation_id}")

@router.websocket("/ws/audio")
async def websocket_audio_endpoint(websocket: WebSocket):
    user_identifier = "anonymous_websocket_user" 
    
    try:
        await websocket.accept()
        logger.info(f"Gateway: WebSocket accepted from {websocket.client.host}:{websocket.client.port}")
    except Exception as e_accept:
        logger.error(f"Gateway: EXCEPTION during websocket.accept(): {e_accept}", exc_info=True)
        if websocket.client_state != WebSocketState.DISCONNECTED:
            try:
                await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
            except RuntimeError:
                pass # Already closed or in a bad state
        return 

    conversation_id = str(uuid.uuid4())
    active_connections[conversation_id] = websocket
    logger.info(f"Gateway: WebSocket connection assigned conv_id: {conversation_id}")
    
    if websocket.client_state != WebSocketState.CONNECTED:
        logger.warning(f"Gateway: Client for conv_id {conversation_id} disconnected BEFORE first send. State: {websocket.client_state.name}")
        if conversation_id in active_connections: 
            del active_connections[conversation_id]
        return

    try:
        await websocket.send_json({"type": "system_event", "event": "conversation_started", "conversation_id": conversation_id})
        logger.info(f"Gateway: Sent conversation_started event for conv_id {conversation_id}")

    except ConnectionClosedOK as e_cco:
        # Underlying 'websockets' library saw a clean close (e.g., code 1000/1001 from peer)
        logger.info(f"Gateway: Initial message for conv_id {conversation_id} not sent: Client connection closed cleanly by peer (code {e_cco.code}, reason: '{e_cco.reason or ''}').")
        if conversation_id in active_connections: del active_connections[conversation_id]
        return

    except WebSocketDisconnect as e_wsd:
        # Starlette's wrapper for a disconnection.
        log_func = logger.info
        log_message_prefix = f"Gateway: Initial message for conv_id {conversation_id} not sent: Client WebSocket disconnected"
        
        if e_wsd.code not in [status.WS_1000_NORMAL_CLOSURE, status.WS_1001_GOING_AWAY]:
            log_func = logger.warning
            log_message_prefix = f"Gateway: Failed to send initial message for conv_id {conversation_id}: Client WebSocket disconnected abnormally"
        
        log_func(f"{log_message_prefix} (code {e_wsd.code}, reason: '{e_wsd.reason or 'N/A'}').")
        if conversation_id in active_connections: del active_connections[conversation_id]
        return

    except ConnectionClosedError as e_cce:
        # Underlying 'websockets' library indicated an error during close or already closed state.
        logger.warning(f"Gateway: Failed to send initial message for conv_id {conversation_id}: Connection error (code {e_cce.code}, reason: '{e_cce.reason or ''}').")
        if conversation_id in active_connections: del active_connections[conversation_id]
        return
        
    except Exception as e_send_event: # Catch other unexpected errors during send
        logger.error(f"Gateway: Unexpected error while sending conversation_started for conv_id {conversation_id}: {e_send_event}", exc_info=True)
        if conversation_id in active_connections: 
            del active_connections[conversation_id]
        if websocket.client_state == WebSocketState.CONNECTED: # Check state before attempting to close
            try:
                await websocket.close(code=status.WS_1011_INTERNAL_ERROR) 
            except RuntimeError: 
                pass
            except (ConnectionClosedOK, ConnectionClosedError): 
                logger.debug(f"Gateway: Attempted to close an already closed socket for conv_id {conversation_id} after send_json failed (general exception).")
            except Exception as e_close_after_send_fail:
                 logger.error(f"Gateway: Further error when trying to close socket for conv_id {conversation_id} after send_json failed (general exception): {e_close_after_send_fail}", exc_info=True)
        return

    all_managed_tasks: List[asyncio.Task] = [] 
    try:
        receive_task = asyncio.create_task(receive_audio_from_client(websocket, conversation_id, redis_service))
        all_managed_tasks.append(receive_task)
        
        transcript_task = asyncio.create_task(forward_transcripts_to_client(websocket, conversation_id))
        all_managed_tasks.append(transcript_task)
        
        llm_token_task = asyncio.create_task(forward_llm_tokens_to_client(websocket, conversation_id))
        all_managed_tasks.append(llm_token_task)
        
        llm_tool_task = asyncio.create_task(forward_tool_calls_to_client(websocket, conversation_id))
        all_managed_tasks.append(llm_tool_task)
        
        tts_audio_task = asyncio.create_task(forward_tts_audio_to_client(websocket, conversation_id))
        all_managed_tasks.append(tts_audio_task)
        
        barge_in_task = asyncio.create_task(forward_barge_in_notifications_to_client(websocket, conversation_id))
        all_managed_tasks.append(barge_in_task)
        
        logger.info(f"Gateway: All ({len(all_managed_tasks)}) listener tasks created for conv_id {conversation_id}.")
        done, pending = await asyncio.wait(all_managed_tasks, return_when=asyncio.FIRST_COMPLETED)
        
        logger.info(f"Gateway: A task completed or failed for conv_id {conversation_id}. Done: {len(done)}, Pending: {len(pending)}. Initiating shutdown for other tasks.")

        for task_obj in pending:
            if not task_obj.done():
                task_obj.cancel()
        
        if pending:
            results = await asyncio.gather(*pending, return_exceptions=True)
            for i, result in enumerate(results):
                # To get task name, we need to iterate over original list if using gather like this
                # For simplicity, just log index or use a dict if names are critical here
                task_name = f"PendingTask-{i}" 
                try:
                    task_name = pending.pop().get_name() #This is not safe if gather changes order or if set changes during iteration
                except: pass # Fallback

                if isinstance(result, asyncio.CancelledError):
                    logger.info(f"Gateway: Task '{task_name}' for conv_id {conversation_id} was cancelled successfully.")
                elif isinstance(result, Exception):
                    logger.error(f"Gateway: Task '{task_name}' for conv_id {conversation_id} raised an exception during gather: {result}", exc_info=result)
        
        for task_obj in done:
            task_name = "DoneTask"
            try: task_name = task_obj.get_name()
            except: pass
            try:
                result = task_obj.result()
                logger.info(f"Gateway: Task '{task_name}' for conv_id {conversation_id} completed. Result type: {type(result).__name__}")
            except asyncio.CancelledError:
                logger.info(f"Gateway: Task '{task_name}' for conv_id {conversation_id} (from done set) was cancelled.")
            except Exception as e_task_done:
                logger.error(f"Gateway: Task '{task_name}' for conv_id {conversation_id} (from done set) failed: {e_task_done}", exc_info=True)

    except WebSocketDisconnect as e_disconnect_main:
        logger.info(f"Gateway: WebSocket disconnected by client for conv_id {conversation_id} (main handler). Code: {e_disconnect_main.code}")
    except Exception as e_main_handler:
        logger.error(f"Gateway: Error in main WebSocket handler for conv_id {conversation_id}: {e_main_handler}", exc_info=True)
    finally:
        logger.info(f"Gateway: Cleaning up WebSocket connection for conv_id {conversation_id}.")
        if conversation_id in active_connections:
            del active_connections[conversation_id]
        
        for task_obj in all_managed_tasks:
            if task_obj and not task_obj.done():
                task_obj.cancel()
        if all_managed_tasks:
            logger.info(f"Gateway: Gathering all ({len(all_managed_tasks)}) tasks for conv_id {conversation_id} to ensure cancellation.")
            await asyncio.gather(*all_managed_tasks, return_exceptions=True)
            logger.info(f"Gateway: All tasks gathered for conv_id {conversation_id}.")
        
        if websocket.client_state == WebSocketState.CONNECTED:
            logger.info(f"Gateway: Closing WebSocket from server-side for conv_id {conversation_id}.")
            try:
                await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
            except RuntimeError:
                 logger.warning(f"Gateway: Tried to close already closed/broken WebSocket for conv_id {conversation_id}.")
            except Exception as e_close:
                logger.error(f"Gateway: Error during server-side close for conv_id {conversation_id}: {e_close}", exc_info=True)
        logger.info(f"Gateway: WebSocket connection fully processed for conv_id {conversation_id}.") 