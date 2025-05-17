import asyncio
import signal
import json
import redis.asyncio as redis
from typing import Dict, Optional, Tuple, Any, Coroutine

from tts_worker.config import tts_settings # Standalone service config
from tts_worker.logging_config import get_logger # Updated logger import
from tts_worker.core.tts_abc import AbstractTTSService # Updated ABC import
from tts_worker.providers.piper_tts_service import PiperTTSService # Updated Piper import
from tts_worker.providers.elevenlabs_tts_service import ElevenLabsTTSService # Updated ElevenLabs import

logger = get_logger(__name__)

running = True

# New state management for queuing TTS requests
tts_request_queues: Dict[str, asyncio.Queue] = {}
active_tts_processors: Dict[str, asyncio.Task] = {}

# Timeout for a conversation queue processor to wait for new items before shutting down
PROCESSOR_QUEUE_GET_TIMEOUT_SECONDS = 60 

def get_tts_service_instance() -> AbstractTTSService:
    logger.info(f"Selected TTS Provider: {tts_settings.TTS_PROVIDER}")

    if tts_settings.TTS_PROVIDER == "piper":
        logger.info(f"Initializing PiperTTS service with settings: {tts_settings.piper.model_dump()}")
        service_instance = PiperTTSService(
            executable_path=tts_settings.piper.EXECUTABLE_PATH,
            voices_dir=tts_settings.piper.VOICES_DIR,
            default_voice_model=tts_settings.piper.DEFAULT_VOICE_MODEL,
            native_sample_rate=tts_settings.piper.NATIVE_SAMPLE_RATE,
            target_sample_rate=tts_settings.AUDIO_OUTPUT_SAMPLE_RATE
        )
        return service_instance
    elif tts_settings.TTS_PROVIDER == "elevenlabs":
        logger.info(f"Initializing ElevenLabsTTS service with API key present: {bool(tts_settings.elevenlabs.API_KEY)}")
        if not tts_settings.elevenlabs.API_KEY:
            logger.error("ElevenLabs API key is not configured.")
            raise ValueError("ElevenLabs API key is missing in configuration for ElevenLabs provider.")
        service_instance = ElevenLabsTTSService(
            api_key=tts_settings.elevenlabs.API_KEY,
            default_voice_id=tts_settings.elevenlabs.DEFAULT_VOICE_ID,
            target_sample_rate=tts_settings.AUDIO_OUTPUT_SAMPLE_RATE
        )
        return service_instance
    else:
        logger.error(f"Unsupported TTS provider: {tts_settings.TTS_PROVIDER}")
        raise ValueError(f"Unsupported TTS provider: {tts_settings.TTS_PROVIDER}")

async def set_tts_active_state_for_conversation(conversation_id: str, redis_client: redis.Redis, active: bool):
    tts_active_key = f"{tts_settings.TTS_ACTIVE_STATE_PREFIX}{conversation_id}"
    try:
        if active:
            await redis_client.set(tts_active_key, "1", ex=tts_settings.TTS_ACTIVE_STATE_TTL_SECONDS)
            logger.info(f"TTS active state SET for conv_id {conversation_id}")
        else:
            await redis_client.delete(tts_active_key)
            logger.info(f"TTS active state CLEARED for conv_id {conversation_id}")
    except redis.RedisError as e:
        logger.error(f"Redis error setting TTS active state for {conversation_id}: {e}", exc_info=True)

async def _execute_single_tts_item(
    request_item: Dict,
    conversation_id: str,
    synthesizer: AbstractTTSService,
    redis_client: redis.Redis,
    stop_event_for_synth: asyncio.Event
):
    text_to_speak = request_item.get("text_to_speak")
    voice_id = request_item.get("voice_id")
    provider_options = request_item.get("options", {})

    logger.info(f"TTS Worker: Processing item for conv_id '{conversation_id}', voice '{voice_id or 'default'}': '{text_to_speak[:50]}...'")
    output_channel = tts_settings.AUDIO_OUTPUT_STREAM_CHANNEL_PATTERN.format(conversation_id=conversation_id)
    
    start_message_payload: Dict[str, Any] = {
        "type": "audio_stream_start",
        "conversation_id": conversation_id,
        "text_synthesized": text_to_speak # Optionally include the text being synthesized
    }

    if isinstance(synthesizer, ElevenLabsTTSService):
        current_output_format = provider_options.get("output_format", "pcm_24000") # Default from example
        sample_rate, audio_format, channels = 24000, "pcm_s16le", 1 # Defaults
        if "pcm_" in current_output_format:
            audio_format = "pcm_s16le"
            try: sample_rate = int(current_output_format.split('_')[-1])
            except ValueError: logger.warning(f"Could not parse sample rate from PCM format: {current_output_format}, using default {sample_rate}")
        elif "mp3_" in current_output_format:
            audio_format = "mp3"
            try: sample_rate = int(current_output_format.split('_')[1])
            except (ValueError, IndexError): logger.warning(f"Could not parse sample rate from MP3 format: {current_output_format}, using default {sample_rate}")
        
        start_message_payload.update({"format": audio_format, "sample_rate": sample_rate, "channels": channels})
        if audio_format == "pcm_s16le": start_message_payload["sample_width"] = 2
    else: # For Piper (which is PCM) or other potential PCM providers
        start_message_payload.update({
            "format": "pcm_s16le",
            "sample_rate": tts_settings.AUDIO_OUTPUT_SAMPLE_RATE,
            "channels": tts_settings.AUDIO_OUTPUT_CHANNELS,
            "sample_width": tts_settings.AUDIO_OUTPUT_SAMPLE_WIDTH
        })
    
    try:
        await redis_client.publish(output_channel, json.dumps(start_message_payload))
    except redis.RedisError as e:
        logger.error(f"Redis error publishing start_message for {conversation_id}: {e}", exc_info=True)
        return # Cannot proceed if start message fails

    chunk_count = 0
    try:
        async for audio_chunk in synthesizer.synthesize_stream(text_to_speak, voice_id=voice_id, stop_event=stop_event_for_synth, **provider_options):
            if stop_event_for_synth.is_set():
                logger.info(f"TTS _execute_single_tts_item: Stop event detected for conv_id '{conversation_id}', breaking publish loop.")
                await synthesizer.stop_synthesis() # Ask the synthesizer to stop if it has such a method
                break
            if audio_chunk:
                try:
                    await redis_client.publish(output_channel, audio_chunk)
                    chunk_count += 1
                except redis.RedisError as e:
                    logger.error(f"Redis error publishing audio chunk for {conversation_id}: {e}", exc_info=True)
                    stop_event_for_synth.set() # Signal stop if publish fails
                    break
        
        if not stop_event_for_synth.is_set():
            end_message = {"type": "audio_stream_end", "conversation_id": conversation_id, "chunk_count": chunk_count}
            try: await redis_client.publish(output_channel, json.dumps(end_message))
            except redis.RedisError as e: logger.error(f"Redis error publishing end_message for {conversation_id}: {e}", exc_info=True)
            logger.info(f"TTS Worker: Finished streaming {chunk_count} audio chunks for item in conv_id '{conversation_id}'.")
        else:
            logger.info(f"TTS Worker: Stream for item in conv_id '{conversation_id}' was stopped, normal end message suppressed.")

    except FileNotFoundError as e:
        logger.error(f"TTS Worker: Synthesizer file error for item in conv_id '{conversation_id}': {e}", exc_info=True)
        error_end_message = {"type": "audio_stream_error", "conversation_id": conversation_id, "error": str(e)}
        try: await redis_client.publish(output_channel, json.dumps(error_end_message))
        except redis.RedisError as re: logger.error(f"Redis error publishing FileNotFoundError for {conversation_id}: {re}", exc_info=True)
    except Exception as e:
        logger.error(f"TTS Worker: Unexpected error during TTS synthesis for item in conv_id '{conversation_id}': {e}", exc_info=True)
        error_end_message = {"type": "audio_stream_error", "conversation_id": conversation_id, "error": "TTS synthesis failed for item."}
        try: await redis_client.publish(output_channel, json.dumps(error_end_message))
        except redis.RedisError as re: logger.error(f"Redis error publishing generic synthesis error for {conversation_id}: {re}", exc_info=True)


async def _process_conversation_tts_queue(
    conversation_id: str,
    synthesizer: AbstractTTSService,
    redis_client: redis.Redis
):
    logger.info(f"TTS Worker: Starting processor for conv_id '{conversation_id}'.")
    queue = tts_request_queues.get(conversation_id)
    if not queue:
        logger.error(f"TTS Worker: No queue found for conv_id '{conversation_id}' in processor. Exiting.")
        if conversation_id in active_tts_processors: del active_tts_processors[conversation_id] # Cleanup
        return

    current_sentence_stop_event: Optional[asyncio.Event] = None
    is_active_for_redis = False

    try:
        while True:
            try:
                request_item = await asyncio.wait_for(queue.get(), timeout=PROCESSOR_QUEUE_GET_TIMEOUT_SECONDS)
                if not is_active_for_redis : # First item, or becoming active again
                    await set_tts_active_state_for_conversation(conversation_id, redis_client, True)
                    is_active_for_redis = True
                
                current_sentence_stop_event = asyncio.Event()
                logger.debug(f"TTS Worker: Got item from queue for conv_id '{conversation_id}': {request_item['text_to_speak'][:30]}...")
                
                await _execute_single_tts_item(
                    request_item,
                    conversation_id,
                    synthesizer,
                    redis_client,
                    current_sentence_stop_event
                )
                current_sentence_stop_event = None 
                queue.task_done()
                logger.debug(f"TTS Worker: Finished item for conv_id '{conversation_id}'. Queue size: {queue.qsize()}")

            except asyncio.TimeoutError:
                logger.info(f"TTS Worker: Queue for conv_id '{conversation_id}' timed out. Processor shutting down.")
                break 
            except asyncio.CancelledError: # This task itself was cancelled (e.g., by barge-in)
                logger.info(f"TTS Worker: Processor for conv_id '{conversation_id}' was cancelled.")
                if current_sentence_stop_event:
                    logger.info(f"TTS Worker: Signalling current sentence to stop for conv_id '{conversation_id}'.")
                    current_sentence_stop_event.set() # Signal current synthesis to stop

                # Clear the rest of the queue for this conversation
                logger.info(f"TTS Worker: Clearing remaining {queue.qsize()} items from queue for conv_id '{conversation_id}'.")
                while not queue.empty():
                    try: queue.get_nowait()
                    except asyncio.QueueEmpty: break
                    queue.task_done() # Important to call task_done for each item removed
                raise # Re-raise to ensure task is properly cancelled by asyncio
    
    except Exception as e: # Catch any other unexpected error in the processor loop
        logger.error(f"TTS Worker: Unexpected error in processor for conv_id '{conversation_id}': {e}", exc_info=True)
    finally:
        logger.info(f"TTS Worker: Cleaning up processor for conv_id '{conversation_id}'.")
        if is_active_for_redis:
             await set_tts_active_state_for_conversation(conversation_id, redis_client, False)
        if conversation_id in active_tts_processors:
            del active_tts_processors[conversation_id]
        if conversation_id in tts_request_queues:
            # Ensure queue is empty if processor exits normally after timeout or due to other reasons
            # If cancelled, it should have been cleared in the CancelledError block
            q = tts_request_queues[conversation_id]
            if q and not q.empty():
                 logger.warning(f"TTS Worker: Processor for conv_id '{conversation_id}' exiting, but queue still has {q.qsize()} items. Clearing.")
                 while not q.empty():
                    try: q.get_nowait()
                    except asyncio.QueueEmpty: break
                    q.task_done()
            del tts_request_queues[conversation_id]
        logger.info(f"TTS Worker: Processor for conv_id '{conversation_id}' fully shut down.")


async def process_tts_request(request_data: Dict, synthesizer: AbstractTTSService, redis_client: redis.Redis):
    conversation_id = request_data.get("conversation_id")
    text_to_speak = request_data.get("text_to_speak")
    voice_id = request_data.get("voice_id")
    provider_options = request_data.get("options", {})

    if not conversation_id or not text_to_speak:
        logger.error(f"Missing conversation_id or text_to_speak in TTS request: {request_data}")
        return

    logger.info(f"TTS Worker: Received request for conv_id '{conversation_id}': '{text_to_speak[:50]}...' Adding to queue.")

    if conversation_id not in tts_request_queues:
        tts_request_queues[conversation_id] = asyncio.Queue()
        logger.info(f"TTS Worker: Created new queue for conv_id '{conversation_id}'.")

    queue_item = {
        "text_to_speak": text_to_speak,
        "voice_id": voice_id,
        "options": provider_options
    }
    await tts_request_queues[conversation_id].put(queue_item)
    logger.debug(f"TTS Worker: Item added to queue for conv_id '{conversation_id}'. Queue size: {tts_request_queues[conversation_id].qsize()}")

    # Check if a processor is running for this conversation_id, if not, start one.
    if conversation_id not in active_tts_processors or active_tts_processors[conversation_id].done():
        logger.info(f"TTS Worker: No active processor for conv_id '{conversation_id}' or previous one done. Starting new processor.")
        processor_task = asyncio.create_task(
            _process_conversation_tts_queue(conversation_id, synthesizer, redis_client)
        )
        active_tts_processors[conversation_id] = processor_task
    else:
        logger.debug(f"TTS Worker: Active processor already running for conv_id '{conversation_id}'.")


async def subscribe_to_tts_requests(redis_client: redis.Redis, synthesizer: AbstractTTSService):
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(tts_settings.TTS_REQUEST_CHANNEL)
    logger.info(f"TTS Service subscribed to Redis channel: {tts_settings.TTS_REQUEST_CHANNEL}")
    global running
    while running:
        try:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if message and message["type"] == "message":
                request_data_str = message["data"].decode('utf-8')
                try:
                    request_data = json.loads(request_data_str)
                    # process_tts_request is now async as it puts to a queue
                    asyncio.create_task(process_tts_request(request_data, synthesizer, redis_client))
                except json.JSONDecodeError:
                    logger.error(f"TTS Service: Error decoding TTS request JSON: {request_data_str}", exc_info=True)
            elif message is None: await asyncio.sleep(0.01)
        except redis.RedisError as e:
            logger.error(f"TTS Service: Redis error in TTS request subscription loop: {e}", exc_info=True)
            await asyncio.sleep(5) 
        except Exception as e:
            logger.error(f"TTS Service: Error in TTS request subscription loop: {e}", exc_info=True)
            await asyncio.sleep(1)
    try: await pubsub.unsubscribe(tts_settings.TTS_REQUEST_CHANNEL)
    except redis.RedisError: pass # nosec
    try: await pubsub.close()
    except redis.RedisError: pass # nosec

async def subscribe_to_tts_control(redis_client: redis.Redis):
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(tts_settings.BARGE_IN_CHANNEL) # Using BARGE_IN_CHANNEL from tts_settings
    logger.info(f"TTS Service subscribed to control/barge-in channel: {tts_settings.BARGE_IN_CHANNEL}")
    global running
    while running:
        try:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if message and message["type"] == "message":
                control_data_str = message["data"].decode('utf-8')
                logger.info(f"TTS Service: Received control data: {control_data_str}")
                try:
                    control_data = json.loads(control_data_str)
                    conv_id_to_stop = control_data.get("conversation_id")
                    
                    should_stop = False
                    if control_data.get("command") == "stop_tts" and conv_id_to_stop:
                        logger.info(f"TTS Service: Received 'stop_tts' command for conv_id '{conv_id_to_stop}'.")
                        should_stop = True
                    elif control_data.get("type") == "barge_in_detected" and conv_id_to_stop: # Assuming barge_in messages also use this key
                        logger.info(f"TTS Service: Received 'barge_in_detected' event for conv_id '{conv_id_to_stop}'.")
                        should_stop = True
                    
                    if should_stop and conv_id_to_stop:
                        if conv_id_to_stop in active_tts_processors:
                            task_to_cancel = active_tts_processors[conv_id_to_stop]
                            if not task_to_cancel.done():
                                logger.info(f"TTS Service: Cancelling processor task for conv_id '{conv_id_to_stop}'.")
                                task_to_cancel.cancel()
                                # The task's CancelledError handler will do queue clearing and resource cleanup.
                            else:
                                logger.info(f"TTS Service: Processor task for conv_id '{conv_id_to_stop}' already done. No action to cancel.")
                                # Ensure cleanup if task is done but somehow still in active_tts_processors
                                del active_tts_processors[conv_id_to_stop]
                                if conv_id_to_stop in tts_request_queues:
                                    del tts_request_queues[conv_id_to_stop]

                        else:
                            logger.info(f"TTS Service: No active processor task found to stop for conv_id '{conv_id_to_stop}'.")
                            # If no processor, still ensure any orphaned queue is cleared.
                            if conv_id_to_stop in tts_request_queues:
                                q = tts_request_queues[conv_id_to_stop]
                                logger.info(f"TTS Service: Clearing orphaned queue for conv_id '{conv_id_to_stop}' with {q.qsize()} items.")
                                while not q.empty():
                                    try: q.get_nowait()
                                    except asyncio.QueueEmpty: break
                                    q.task_done()
                                del tts_request_queues[conv_id_to_stop]
                                
                except json.JSONDecodeError:
                    logger.error(f"TTS Service: Error decoding control/barge-in JSON: {control_data_str}", exc_info=True)
            elif message is None: await asyncio.sleep(0.01)
        except redis.RedisError as e:
            logger.error(f"TTS Service: Redis error in control subscription loop: {e}. Retrying...", exc_info=True)
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"TTS Service: Error in control subscription loop: {e}", exc_info=True)
            await asyncio.sleep(1)
    
    try: await pubsub.unsubscribe(tts_settings.BARGE_IN_CHANNEL)
    except redis.RedisError: pass # nosec
    try: await pubsub.close()
    except redis.RedisError: pass # nosec
    logger.info(f"TTS Service unsubscribed and closed pubsub for control channel: {tts_settings.BARGE_IN_CHANNEL}.")


def signal_handler_tts(signum, frame):
    global running
    logger.info(f"Signal {signum} received by TTS Worker, initiating shutdown...")
    running = False

async def main_async_tts():
    global running # Declare global at the beginning of the function scope
    signal.signal(signal.SIGINT, signal_handler_tts)
    signal.signal(signal.SIGTERM, signal_handler_tts)
    logger.info("Starting TTS Worker...")
    redis_client_tts = None
    synthesizer_instance = None
    
    # For graceful shutdown of processor tasks
    active_tasks_to_await: List[Coroutine] = []

    try:
        redis_client_tts = redis.Redis(
            host=tts_settings.REDIS_HOST,
            port=tts_settings.REDIS_PORT,
            db=tts_settings.REDIS_DB,
            password=tts_settings.REDIS_PASSWORD,
            auto_close_connection_pool=False # Keep pool open for tasks
        )
        await redis_client_tts.ping()
        logger.info("TTS Worker connected to Redis.")

        synthesizer_instance = get_tts_service_instance()
        logger.info(f"TTS Synthesizer instance ({type(synthesizer_instance).__name__}) created.")

        # Start the main subscription loops
        request_subscriber_task = asyncio.create_task(
            subscribe_to_tts_requests(redis_client_tts, synthesizer_instance)
        )
        control_subscriber_task = asyncio.create_task(
            subscribe_to_tts_control(redis_client_tts)
        )
        
        active_tasks_to_await.extend([request_subscriber_task, control_subscriber_task])
        logger.info("TTS Worker has started successfully and is now processing requests and control commands.")

        # Keep main alive while `running` is true, checking periodically
        while running:
            await asyncio.sleep(0.5)
        
        logger.info("TTS Worker: Shutdown initiated. `running` is False.")

    except ConnectionRefusedError as e:
        logger.critical(f"TTS Worker could not connect to Redis: {e}. Service cannot start.", exc_info=True)
    except ValueError as e: # For config errors like missing API key or unsupported provider
         logger.critical(f"TTS Worker configuration error: {e}. Service cannot start.", exc_info=True)
    except RuntimeError as e: # E.g., if event loop is already running in a different way
        logger.critical(f"TTS Worker runtime error during initialization: {e}. Service cannot start.", exc_info=True)
    except Exception as e:
        logger.critical(f"Unexpected critical error in TTS Worker: {e}", exc_info=True)
    finally:
        logger.info("TTS Worker shutting down...")
        running = False # Ensure it's false for all loops

        # 1. Cancel main subscriber tasks first
        if 'request_subscriber_task' in locals() and request_subscriber_task: request_subscriber_task.cancel()
        if 'control_subscriber_task' in locals() and control_subscriber_task: control_subscriber_task.cancel()

        # 2. Cancel all active TTS processor tasks
        logger.info(f"Cancelling {len(active_tts_processors)} active TTS processor tasks...")
        for conv_id, task in list(active_tts_processors.items()): # Iterate over a copy
            if task and not task.done():
                logger.info(f"Cancelling processor for conv_id {conv_id}")
                task.cancel()
                active_tasks_to_await.append(task) # Add to list to await its completion/cancellation
        
        # 3. Await cancellation/completion of all critical tasks
        if active_tasks_to_await:
            logger.info(f"Awaiting completion of {len(active_tasks_to_await)} tasks...")
            # Use gather with return_exceptions=True to ensure all tasks are awaited even if some fail
            results = await asyncio.gather(*active_tasks_to_await, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                    logger.error(f"Error/Exception during task shutdown: {result}", exc_info=isinstance(result, BaseException))
            logger.info("All critical tasks awaited.")
            
        # Cleanup synthesizer resources if it has a method
        if synthesizer_instance and hasattr(synthesizer_instance, 'close') and asyncio.iscoroutinefunction(synthesizer_instance.close):
            try:
                logger.info("Closing synthesizer resources...")
                await synthesizer_instance.close() # Assuming an async close method
                logger.info("Synthesizer resources closed.")
            except Exception as e:
                logger.error(f"Error closing synthesizer resources: {e}", exc_info=True)

        if redis_client_tts:
            logger.info("Closing TTS Worker Redis client...")
            await redis_client_tts.close() # Close the main client pool
            logger.info("TTS Worker Redis client closed.")
        
        logger.info("TTS Worker has shut down.")

def main():
    try:
        asyncio.run(main_async_tts())
    except KeyboardInterrupt: # Should be caught by signal handler, but as a fallback
        logger.info("TTS Worker KeyboardInterrupt. Forcing exit.")
    except Exception as e: # Catch-all for any unexpected error during run that wasn't handled
        logger.critical(f"TTS Worker main() caught unhandled exception: {e}", exc_info=True)


if __name__ == "__main__":
    main() 