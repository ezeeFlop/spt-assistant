import asyncio
import json
import signal
import functools
import time # Added for timestamps and timeouts
from typing import Dict, Any, Tuple # Added Tuple

import redis.asyncio as redis
from redis.exceptions import ConnectionError as RedisConnectionError, RedisError

from vad_stt_worker.audio_processor import AudioProcessor # Assuming AudioProcessor is in this path
from vad_stt_worker.config import worker_settings
from vad_stt_worker.logging_config import get_logger

logger = get_logger(__name__)

# Dictionary to hold active AudioProcessor instances, keyed by conversation_id
active_processors: Dict[str, AudioProcessor] = {}
# Lock for safely accessing and modifying active_processors
processor_management_lock = asyncio.Lock()

# Global variable to signal shutdown
shutdown_event = asyncio.Event()

# For managing processor timeouts
last_activity_time: Dict[str, float] = {}
PROCESSOR_INACTIVITY_TIMEOUT_S = worker_settings.WORKER_PROCESSOR_INACTIVITY_TIMEOUT_S # e.g., 120 seconds

# For barge-in
BARGE_IN_CHANNEL = worker_settings.BARGE_IN_CHANNEL # e.g., "barge_in_notifications"
TTS_ACTIVE_STATE_PREFIX = worker_settings.TTS_ACTIVE_STATE_PREFIX # e.g., "tts_active:"

def handle_signal(sig, frame, loop):
    logger.info(f"Signal {sig} received, initiating graceful shutdown...")
    shutdown_event.set()
    # Attempt to stop the loop if it's provided and running
    # This part is tricky as we don't have direct access to the loop from here in all contexts
    # The main loop will check shutdown_event

async def check_tts_active(conversation_id: str, redis_client: redis.Redis) -> bool:
    """Checks if TTS is marked active for the given conversation_id in Redis."""
    tts_active_key = f"{TTS_ACTIVE_STATE_PREFIX}{conversation_id}"
    try:
        return await redis_client.exists(tts_active_key) > 0
    except RedisError as e:
        logger.error(f"Redis error checking TTS active state for conv_id {conversation_id}: {e}", exc_info=True)
        return False # Assume not active on error to be safe

async def publish_transcript(redis_client: redis.Redis, conversation_id: str, transcript: str, is_final: bool, timestamp_ms: float):
    """Publishes transcript to Redis with conversation_id, type, and final status."""
    logger.info(f"MAIN.PY: PUBLISH_TRANSCRIPT CALLED with transcript='{transcript}', final={is_final}, conv_id={conversation_id}") # DEBUG LOG
    if not transcript.strip() and not is_final: # Don't publish empty non-final transcripts
        # logger.debug(f"Skipping empty non-final transcript for conv_id {conversation_id}")
        return
    message_type = "final_transcript" if is_final else "partial_transcript"
    payload = {
        "type": message_type,
        "conversation_id": conversation_id,
        "transcript": transcript,
        "timestamp_ms": timestamp_ms,
        "is_final": is_final # Explicitly include is_final
    }
    try:
        await redis_client.publish(worker_settings.TRANSCRIPT_CHANNEL, json.dumps(payload))
        # logger.debug(f"Published {message_type} for conv_id {conversation_id}: {transcript[:50]}...")
    except RedisError as e:
        logger.error(f"Redis error publishing transcript for conv_id {conversation_id}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unexpected error publishing transcript for conv_id {conversation_id}: {e}", exc_info=True)

async def cleanup_inactive_processors_periodically():
    """Periodically clean up AudioProcessor instances that have been inactive for too long."""
    global last_activity_time, active_processors
    while not shutdown_event.is_set():
        try:
            await asyncio.sleep(30) # Check every 30 seconds
            current_time = time.time()
            conversations_to_cleanup = []
            
            async with processor_management_lock:
                for conv_id, last_activity in list(last_activity_time.items()):
                    if current_time - last_activity > worker_settings.WORKER_PROCESSOR_INACTIVITY_TIMEOUT_S:
                        conversations_to_cleanup.append(conv_id)
                        logger.info(f"Marking conv_id {conv_id} for cleanup due to inactivity (last activity: {current_time - last_activity:.1f}s ago)")
                
                for conv_id in conversations_to_cleanup:
                    if conv_id in active_processors:
                        try:
                            active_processors[conv_id].close()
                            logger.info(f"Cleaned up inactive AudioProcessor for conv_id {conv_id}")
                        except Exception as e:
                            logger.error(f"Error cleaning up AudioProcessor for conv_id {conv_id}: {e}", exc_info=True)
                        del active_processors[conv_id]
                    
                    if conv_id in last_activity_time:
                        del last_activity_time[conv_id]
                        
        except asyncio.CancelledError:
            logger.info("Periodic cleanup task cancelled")
            break
        except Exception as e:
            logger.error(f"Error in periodic cleanup task: {e}", exc_info=True)

async def handle_connection_disconnect_event(conversation_id: str, reason: str):
    """
    Handles connection disconnect events by cleaning up resources for the specified conversation.
    This ensures that when a WebSocket connection is closed, all associated audio processing
    resources are properly cleaned up.
    """
    logger.info(f"VAD/STT Worker: Handling connection disconnect for conv_id {conversation_id}, reason: {reason}")
    
    async with processor_management_lock:
        # Clean up audio processor if it exists
        if conversation_id in active_processors:
            try:
                processor = active_processors[conversation_id]
                processor.close()
                del active_processors[conversation_id]
                logger.info(f"VAD/STT Worker: Cleaned up AudioProcessor for disconnected conv_id {conversation_id}")
            except Exception as e:
                logger.error(f"VAD/STT Worker: Error cleaning up AudioProcessor for conv_id {conversation_id}: {e}", exc_info=True)
        
        # Clean up activity tracking
        if conversation_id in last_activity_time:
            del last_activity_time[conversation_id]
            logger.debug(f"VAD/STT Worker: Removed activity tracking for conv_id {conversation_id}")

async def subscribe_to_connection_events(redis_client: redis.Redis):
    """
    Subscribes to connection events channel to handle connection disconnects.
    This allows the worker to clean up resources when connections are closed.
    """
    pubsub: Any = None
    try:
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(worker_settings.CONNECTION_EVENTS_CHANNEL)
        logger.info(f"VAD/STT Worker subscribed to connection events channel: {worker_settings.CONNECTION_EVENTS_CHANNEL}")

        while not shutdown_event.is_set():
            try:
                # Check for shutdown event
                await asyncio.wait_for(shutdown_event.wait(), timeout=0.001)
                if shutdown_event.is_set():
                    logger.info("Shutdown event detected in connection events listener, exiting...")
                    break
            except asyncio.TimeoutError:
                pass # Normal timeout, continue listening

            try:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
                if message and message["type"] == "message":
                    message_data_str = message["data"].decode('utf-8')
                    logger.debug(f"VAD/STT Worker: Received connection event: {message_data_str}")
                    
                    try:
                        event_data = json.loads(message_data_str)
                        event_type = event_data.get("type")
                        conversation_id = event_data.get("conversation_id")
                        reason = event_data.get("reason", "unknown")
                        
                        if event_type == "connection_disconnected" and conversation_id:
                            await handle_connection_disconnect_event(conversation_id, reason)
                        else:
                            logger.debug(f"VAD/STT Worker: Ignoring connection event type: {event_type}")
                            
                    except json.JSONDecodeError as e:
                        logger.error(f"VAD/STT Worker: Error decoding connection event JSON: {e} - Data: {message_data_str}")
                    except Exception as e:
                        logger.error(f"VAD/STT Worker: Error processing connection event: {e}", exc_info=True)
                elif message is None:
                    await asyncio.sleep(0.01)
                    
            except asyncio.TimeoutError:
                await asyncio.sleep(0.01)
                continue
            except RedisError as e:
                logger.error(f"VAD/STT Worker: Redis error in connection events loop: {e}", exc_info=True)
                if isinstance(e, RedisConnectionError):
                    await asyncio.sleep(5)
                else:
                    shutdown_event.set()
                    break
            except Exception as e:
                logger.error(f"VAD/STT Worker: Unexpected error in connection events loop: {e}", exc_info=True)
                await asyncio.sleep(1)
                
    except Exception as e:
        logger.error(f"VAD/STT Worker: Error setting up connection events subscription: {e}", exc_info=True)
    finally:
        if pubsub:
            try:
                logger.info(f"VAD/STT Worker: Unsubscribing from {worker_settings.CONNECTION_EVENTS_CHANNEL}")
                await pubsub.unsubscribe(worker_settings.CONNECTION_EVENTS_CHANNEL)
                await pubsub.close()
                logger.info("VAD/STT Worker: Connection events pubsub unsubscribed and closed.")
            except Exception as e_pubsub_close:
                logger.error(f"VAD/STT Worker: Error closing connection events pubsub: {e_pubsub_close}", exc_info=True)

async def process_audio_messages_from_redis(redis_client: redis.Redis):
    pubsub: Any = None
    has_signaled_barge_in_for_conv: Dict[str, bool] = {} # Track per-conversation
    try:
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(worker_settings.AUDIO_STREAM_CHANNEL)
        logger.info(f"VAD/STT Subscribed to Redis channel: {worker_settings.AUDIO_STREAM_CHANNEL}")

        while not shutdown_event.is_set():
            try:
                # Check for shutdown event more frequently
                await asyncio.wait_for(shutdown_event.wait(), timeout=0.001)
                if shutdown_event.is_set():
                    logger.info("Shutdown event detected in Redis listener loop, exiting...")
                    break
            except asyncio.TimeoutError:
                pass # Normal timeout, continue listening

            try:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
                if message and message["type"] == "message":

                    message_data_str = message["data"].decode('utf-8')
                    # logger.debug(f"Received raw message from Redis: {message_data_str[:100]}...")
                    
                    try:
                        payload = json.loads(message_data_str)
                        conversation_id = payload.get("conversation_id")
                        audio_data_hex = payload.get("audio_data")

                        if not conversation_id or not audio_data_hex:
                            logger.warning(f"Missing conversation_id or audio_data in payload: {message_data_str}")
                            continue

                        audio_chunk_bytes = bytes.fromhex(audio_data_hex)
                        if not audio_chunk_bytes:
                            # logger.debug(f"Received empty audio chunk for conv_id {conversation_id}. Skipping.")
                            continue
                        
                        # logger.debug(f"Received audio chunk for conv_id {conversation_id}, {len(audio_chunk_bytes)} bytes.")

                        processor: AudioProcessor | None = None
                        async with processor_management_lock:
                            if conversation_id not in active_processors:
                                logger.info(f"No active AudioProcessor for conv_id {conversation_id}. Creating new instance.")
                                try:
                                    active_processors[conversation_id] = AudioProcessor()
                                    logger.info(f"Created AudioProcessor for conv_id {conversation_id}.")
                                    has_signaled_barge_in_for_conv[conversation_id] = False # Initialize barge-in flag
                                except Exception as e_proc_create:
                                    logger.error(f"Failed to create AudioProcessor for conv_id {conversation_id}: {e_proc_create}", exc_info=True)
                                    if conversation_id in last_activity_time: del last_activity_time[conversation_id] # Clean up if create failed
                                    continue # Skip this message if processor creation failed
                            processor = active_processors.get(conversation_id)

                        if processor:
                            try:
                                for event in processor.process_audio_chunk(audio_chunk_bytes):
                                    logger.info(f"VAD/STT Worker: Received event: {event}")
                                    if event["event_type"] == "transcript":
                                        await publish_transcript(redis_client, conversation_id, event["transcript"], event["is_final"], event["timestamp_ms"])
                                        if has_signaled_barge_in_for_conv.get(conversation_id, False):
                                            logger.debug(f"Resetting barge-in signaled flag for conv_id {conversation_id} after final transcript.")
                                        has_signaled_barge_in_for_conv[conversation_id] = False
                                        
                                        # Update last activity time upon final transcript, good signal of active processing
                                        last_activity_time[conversation_id] = time.time()
                                    # Barge-in Logic:
                                    # If a transcript (even partial) is produced, it means speech is detected.
                                    if event["event_type"] == "vad_event" and (event["status"] == "proper_speech_start" or event["status"] == "barge_in_start"): # Check if there's actual speech text
                                        if not has_signaled_barge_in_for_conv.get(conversation_id, False):
                                            logger.info(f"Barge-in detected for conv_id {conversation_id}.")
                                            tts_is_currently_active = True #await check_tts_active(conversation_id, redis_client)
                                            logger.info(f"TTS is currently active for conv_id {conversation_id}: {tts_is_currently_active}")
                                            if tts_is_currently_active:
                                                barge_in_payload = {
                                                    "type": "barge_in_detected", # Clearer type for the event
                                                    "conversation_id": conversation_id,
                                                    "timestamp_ms": time.time() * 1000
                                                }
                                                try:
                                                    await redis_client.publish(BARGE_IN_CHANNEL, json.dumps(barge_in_payload))
                                                    logger.info(f"Published BARGE-IN signal for conv_id {conversation_id} as TTS was active.")
                                                    has_signaled_barge_in_for_conv[conversation_id] = True
                                                except RedisError as e_barge_pub:
                                                    logger.error(f"Redis error publishing barge-in signal for conv_id {conversation_id}: {e_barge_pub}", exc_info=True)
                                                except Exception as e_barge_generic:
                                                    logger.error(f"Unexpected error publishing barge-in signal for conv_id {conversation_id}: {e_barge_generic}", exc_info=True)
                                    

                            except Exception as e_process_chunk:
                                logger.error(f"Error processing audio chunk for conv_id {conversation_id}: {e_process_chunk}", exc_info=True)
                                # Consider if we need to close/remove the processor on certain errors
                        else:
                            logger.error(f"AudioProcessor instance not found or created for conv_id {conversation_id} after lock. This shouldn't happen.")
                            
                    except json.JSONDecodeError:
                        logger.error(f"Error decoding JSON from Redis message: {message_data_str}", exc_info=True)
                    except Exception as e_inner:
                        logger.error(f"Inner loop error processing Redis message: {e_inner}", exc_info=True)
                    finally: # Ensure last activity time is updated even if only audio comes with no transcript (e.g. silence)
                        if conversation_id and audio_chunk_bytes : # check conversation_id not None
                             last_activity_time[conversation_id] = time.time()
                
                # TODO: Implement processor cleanup for inactive conversations
                # For now, processors are cleaned up on shutdown.

            except asyncio.TimeoutError: # From pubsub.get_message timeout
                await asyncio.sleep(0.01) # Small sleep to prevent tight loop on no messages
                continue 
            except RedisError as e:
                logger.error(f"Redis error in main processing loop: {e}. Attempting to reconnect or shutdown...", exc_info=True)
                # Basic retry/shutdown for Redis errors
                if isinstance(e, RedisConnectionError):
                    logger.info("Attempting to re-establish Redis connection shortly...")
                    await asyncio.sleep(5) # Wait before trying to let Redis recover
                    # The loop will attempt to re-subscribe on next iteration if connection is back
                else: # For other Redis errors, maybe better to shutdown
                    logger.error("Non-connection Redis error, setting shutdown event.")
                    shutdown_event.set()
                    break
            except Exception as e: # Catch-all for unexpected errors in the loop
                logger.error(f"Unexpected error in Redis message loop: {e}", exc_info=True)
                await asyncio.sleep(1) # Brief pause before continuing or shutting down

    except Exception as e: # Catch errors during pubsub setup
        logger.error(f"Error setting up Redis pubsub or in outer loop: {e}", exc_info=True)
        shutdown_event.set() # Signal shutdown if pubsub can't be set up
    finally:
        logger.info("Redis listener loop is finishing.")
        if pubsub:
            try:
                logger.info(f"Unsubscribing from {worker_settings.AUDIO_STREAM_CHANNEL}.")
                await pubsub.unsubscribe(worker_settings.AUDIO_STREAM_CHANNEL)
                await pubsub.close() # Close the pubsub connection
                logger.info("Redis pubsub unsubscribed and closed.")
            except Exception as e_pubsub_close:
                logger.error(f"Error closing Redis pubsub: {e_pubsub_close}", exc_info=True)
        
        # Cleanup active processors
        async with processor_management_lock:
            logger.info(f"Cleaning up {len(active_processors)} active AudioProcessor instances...")
            for conv_id, processor_instance in list(active_processors.items()): # Use list to allow modification
                logger.info(f"Closing AudioProcessor for conv_id {conv_id}...")
                try:
                    processor_instance.close() # Ensure AudioProcessor.close() is robust
                    logger.info(f"Closed AudioProcessor for conv_id {conv_id}.")
                except Exception as e_proc_close:
                    logger.error(f"Error closing AudioProcessor for conv_id {conv_id}: {e_proc_close}", exc_info=True)
                del active_processors[conv_id]
            logger.info("All active AudioProcessor instances processed for cleanup.")


async def main():
    logger.info("Starting VAD & STT Worker...")
    logger.info(f"Using STT model: {worker_settings.STT_MODEL_NAME}")
    logger.info(f"Audio input channel: {worker_settings.AUDIO_STREAM_CHANNEL}")
    logger.info(f"Transcript output channel: {worker_settings.TRANSCRIPT_CHANNEL}")
    logger.info(f"Processor inactivity timeout: {PROCESSOR_INACTIVITY_TIMEOUT_S}s")
    logger.info(f"TTS Active State Prefix: {TTS_ACTIVE_STATE_PREFIX}")
    logger.info(f"Barge-in Channel: {BARGE_IN_CHANNEL}")
    logger.info(f"STT Device: {worker_settings.FINAL_STT_DEVICE}")

    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, functools.partial(handle_signal, sig, None, loop))
        # For Windows, signal.CTRL_C_EVENT and signal.CTRL_BREAK_EVENT might be needed
        # but add_signal_handler is not available. Consider alternative for Windows if needed.

    redis_client: redis.Redis | None = None
    cleanup_task: asyncio.Task | None = None
    connection_events_task: asyncio.Task | None = None
    try:
        redis_client = redis.Redis(
            host=worker_settings.REDIS_HOST,
            port=worker_settings.REDIS_PORT,
            password=worker_settings.REDIS_PASSWORD,
            decode_responses=False # We handle decoding of message data manually
        )
        await redis_client.ping()
        logger.info("Successfully connected to Redis for worker.")
        
        # Start the periodic cleanup task
        cleanup_task = asyncio.create_task(cleanup_inactive_processors_periodically())
        logger.info("Inactive processor cleanup task started.")
        
        # Start the connection events listener task
        connection_events_task = asyncio.create_task(subscribe_to_connection_events(redis_client))
        logger.info("Connection events listener task started.")

        logger.info("VAD/STT Worker has started successfully and is now processing audio.")
        await process_audio_messages_from_redis(redis_client)

    except RedisConnectionError as e:
        logger.error(f"Could not connect to Redis: {e}. Worker cannot start.", exc_info=True)
    except Exception as e:
        logger.error(f"An unexpected error occurred during worker startup or main processing: {e}", exc_info=True)
    finally:
        logger.info("VAD/STT Worker is shutting down...")
        if cleanup_task and not cleanup_task.done():
            logger.info("Cancelling inactive processor cleanup task...")
            cleanup_task.cancel()
            try:
                await cleanup_task
                logger.info("Inactive processor cleanup task cancelled and finished.")
            except asyncio.CancelledError:
                logger.info("Inactive processor cleanup task confirmed cancelled.")
            except Exception as e_cleanup_task:
                logger.error(f"Error during cleanup task shutdown: {e_cleanup_task}", exc_info=True)
        
        if connection_events_task and not connection_events_task.done():
            logger.info("Cancelling connection events listener task...")
            connection_events_task.cancel()
            try:
                await connection_events_task
                logger.info("Connection events listener task cancelled and finished.")
            except asyncio.CancelledError:
                logger.info("Connection events listener task confirmed cancelled.")
            except Exception as e_connection_events_task:
                logger.error(f"Error during connection events task shutdown: {e_connection_events_task}", exc_info=True)
        
        if redis_client:
            try:
                await redis_client.close() # Close the main Redis client connection
                await redis_client.connection_pool.disconnect() # Ensure pool is disconnected
                logger.info("Redis client connection closed.")
            except Exception as e_redis_close:
                logger.error(f"Error closing main Redis client: {e_redis_close}", exc_info=True)
        
        # Ensure all processors are cleaned up even if process_audio_messages_from_redis didn't finish its finally block
        # This is a secondary cleanup, primary is in process_audio_messages_from_redis's finally block
        if active_processors:
            logger.warning(f"Performing secondary cleanup of {len(active_processors)} AudioProcessors in main finally block.")
            async with processor_management_lock: # Ensure lock is used for this access too
                for conv_id, processor_instance in list(active_processors.items()):
                    logger.info(f"Force closing AudioProcessor for conv_id {conv_id} from main finally...")
                    try:
                        processor_instance.close()
                    except Exception as e_force_close:
                        logger.error(f"Error force closing AudioProcessor for conv_id {conv_id}: {e_force_close}", exc_info=True)
                    if conv_id in active_processors: # Check if still present before del
                        del active_processors[conv_id]
                    if conv_id in last_activity_time: # Also clean up from activity tracking
                        del last_activity_time[conv_id]
            logger.info("Secondary cleanup of AudioProcessors complete.")

        logger.info("VAD/STT Worker has shut down.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt caught in __main__, worker shutting down.")
    except Exception as e_run:
        logger.critical(f"Critical error running main: {e_run}", exc_info=True) 