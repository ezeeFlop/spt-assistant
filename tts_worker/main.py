import asyncio
import signal
import json
import redis.asyncio as redis
from typing import Dict, Optional, Tuple, Any

from tts_worker.config import tts_settings # Standalone service config
from tts_worker.logging_config import get_logger # Updated logger import
from tts_worker.core.tts_abc import AbstractTTSService # Updated ABC import
from tts_worker.providers.piper_tts_service import PiperTTSService # Updated Piper import
from tts_worker.providers.elevenlabs_tts_service import ElevenLabsTTSService # Updated ElevenLabs import

logger = get_logger(__name__)

running = True

active_synthesis_tasks: Dict[str, Tuple[asyncio.Task, asyncio.Event]] = {}

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

async def set_tts_active_state(conversation_id: str, redis_client: redis.Redis, active: bool):
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

async def process_tts_request(request_data: Dict, synthesizer: AbstractTTSService, redis_client: redis.Redis):
    conversation_id = request_data.get("conversation_id")
    text_to_speak = request_data.get("text_to_speak")
    voice_id = request_data.get("voice_id")
    #voice_id = "pNInz6obpgDQGcFmaJgB"
    provider_options = request_data.get("options", {})

    if not conversation_id or not text_to_speak:
        logger.error(f"Missing conversation_id or text_to_speak in TTS request: {request_data}")
        return

    if conversation_id in active_synthesis_tasks:
        logger.warning(f"TTS Service: Overriding active synthesis for conv_id '{conversation_id}' due to new request.")
        existing_task, existing_event = active_synthesis_tasks[conversation_id]
        existing_event.set() 
        if not existing_task.done():
            existing_task.cancel()
            try: await existing_task
            except asyncio.CancelledError: logger.info(f"TTS Service: Previous synthesis task for conv_id '{conversation_id}' cancelled.")
        if conversation_id in active_synthesis_tasks and active_synthesis_tasks[conversation_id][0] is existing_task:
            del active_synthesis_tasks[conversation_id]

    logger.info(f"TTS Service: Request for conv_id '{conversation_id}', voice '{voice_id or 'default'}': '{text_to_speak[:50]}...'")
    output_channel = tts_settings.AUDIO_OUTPUT_STREAM_CHANNEL_PATTERN.format(conversation_id=conversation_id)
    logger.info(f"TTS Service provider_options: {provider_options}")
    await set_tts_active_state(conversation_id, redis_client, True)
    
    start_message_payload: Dict[str, Any] = {
        "type": "audio_stream_start", 
        "conversation_id": conversation_id,
    }

    if isinstance(synthesizer, ElevenLabsTTSService):
        # Determine output format for ElevenLabs
        # The default output_format in ElevenLabsTTSService.synthesize_stream is "mp3_44100_128"
        current_output_format = provider_options.get("output_format", "pcm_24000")
        
        sample_rate = 24000  # Default for pcm_24000
        audio_format = "pcm_s16le"
        channels = 1 # Default for ElevenLabs voices

        if "pcm_" in current_output_format:
            audio_format = "pcm_s16le" # Assuming 16-bit signed little-endian PCM if configured
            try:
                sample_rate = int(current_output_format.split('_')[-1])
            except ValueError:
                logger.warning(f"Could not parse sample rate from PCM format: {current_output_format}, using default {sample_rate}")
        elif "mp3_" in current_output_format:
            audio_format = "mp3"
            try:
                # e.g., mp3_44100_128 -> 44100
                sample_rate = int(current_output_format.split('_')[1])
            except (ValueError, IndexError):
                logger.warning(f"Could not parse sample rate from MP3 format: {current_output_format}, using default {sample_rate}")
        
        start_message_payload.update({
            "format": audio_format,
            "sample_rate": sample_rate,
            "channels": channels,
        })
        # sample_width is not applicable for MP3. For PCM, it's implied by pcm_s16le (2 bytes).
        if audio_format == "pcm_s16le":
            start_message_payload["sample_width"] = 2

    else: # For Piper (which is PCM) or other potential PCM providers
        start_message_payload.update({
            "format": "pcm_s16le", # Assuming signed 16-bit little-endian PCM
            "sample_rate": tts_settings.AUDIO_OUTPUT_SAMPLE_RATE,
            "channels": tts_settings.AUDIO_OUTPUT_CHANNELS,
            "sample_width": tts_settings.AUDIO_OUTPUT_SAMPLE_WIDTH
        })
    
    try:
        logger.info(f"TTS Service: Publishing start_message_payload: {start_message_payload}")
        await redis_client.publish(output_channel, json.dumps(start_message_payload))
    except redis.RedisError as e:
        logger.error(f"Redis error publishing start_message for {conversation_id}: {e}", exc_info=True)
        await set_tts_active_state(conversation_id, redis_client, False) 
        return

    stop_event = asyncio.Event()
    synthesis_coro = run_synthesis_and_publish(conversation_id, text_to_speak, voice_id, synthesizer, redis_client, output_channel, stop_event, **provider_options)
    task = asyncio.create_task(synthesis_coro)
    active_synthesis_tasks[conversation_id] = (task, stop_event)

    try:
        await task 
    except asyncio.CancelledError:
        logger.info(f"TTS synthesis task for conv_id '{conversation_id}' was explicitly cancelled.")
        await synthesizer.stop_synthesis()
    finally:
        await set_tts_active_state(conversation_id, redis_client, False)
        if conversation_id in active_synthesis_tasks and active_synthesis_tasks[conversation_id][0] is task:
            del active_synthesis_tasks[conversation_id]

async def run_synthesis_and_publish(conversation_id: str, text_to_speak:str, voice_id: Optional[str], synthesizer: AbstractTTSService, redis_client: redis.Redis, output_channel: str, stop_event: asyncio.Event, **kwargs):
    chunk_count = 0
    try:
        async for audio_chunk in synthesizer.synthesize_stream(text_to_speak, voice_id=voice_id, stop_event=stop_event, **kwargs):
            if stop_event.is_set():
                logger.info(f"TTS run_synthesis: Stop event detected for conv_id '{conversation_id}', breaking publish loop.")
                break
            if audio_chunk:
                try: 
                    await redis_client.publish(output_channel, audio_chunk)
                    logger.debug(f"TTS Service: Published audio chunk {chunk_count} for conv_id '{conversation_id}'")
                    chunk_count += 1
                except redis.RedisError as e:
                    logger.error(f"Redis error publishing audio chunk for {conversation_id}: {e}", exc_info=True)
                    stop_event.set()
                    break 
        
        if not stop_event.is_set():
            end_message = {"type": "audio_stream_end", "conversation_id": conversation_id, "chunk_count": chunk_count}
            try: await redis_client.publish(output_channel, json.dumps(end_message))
            except redis.RedisError as e: logger.error(f"Redis error publishing end_message for {conversation_id}: {e}", exc_info=True)
            logger.info(f"TTS Service: Finished streaming {chunk_count} audio chunks to {output_channel} for conv_id '{conversation_id}'.")
        else:
            logger.info(f"TTS Service: Stream for conv_id '{conversation_id}' was stopped, normal end message suppressed.")

    except FileNotFoundError as e:
        logger.error(f"TTS Service: Synthesizer file error for conv_id '{conversation_id}': {e}", exc_info=True)
        error_end_message = {"type": "audio_stream_error", "conversation_id": conversation_id, "error": str(e)}
        try: await redis_client.publish(output_channel, json.dumps(error_end_message))
        except redis.RedisError as re: logger.error(f"Redis error publishing FileNotFoundError for {conversation_id}: {re}", exc_info=True)
    except Exception as e:
        logger.error(f"TTS Service: Unexpected error during TTS synthesis for conv_id '{conversation_id}': {e}", exc_info=True)
        error_end_message = {"type": "audio_stream_error", "conversation_id": conversation_id, "error": "TTS synthesis failed."}
        try: await redis_client.publish(output_channel, json.dumps(error_end_message))
        except redis.RedisError as re: logger.error(f"Redis error publishing generic synthesis error for {conversation_id}: {re}", exc_info=True)

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
    except redis.RedisError: pass
    try: await pubsub.close()
    except redis.RedisError: pass

async def subscribe_to_tts_control(redis_client: redis.Redis):
    pubsub = redis_client.pubsub()

    await pubsub.subscribe(tts_settings.BARGE_IN_CHANNEL)
    logger.info(f"TTS Service subscribed to control/barge-in channel: {tts_settings.BARGE_IN_CHANNEL}")
    global running
    while running:
        try:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.1)
            if message and message["type"] == "message":
                control_data_str = message["data"].decode('utf-8')
                try:
                    control_data = json.loads(control_data_str)
                    conv_id_to_stop = control_data.get("conversation_id")

                    # Handle both "stop_tts" command and "barge_in_detected" type
                    should_stop = False
                    if control_data.get("command") == "stop_tts" and conv_id_to_stop:
                        logger.info(f"TTS Service: Received 'stop_tts' command for conv_id '{conv_id_to_stop}'.")
                        should_stop = True
                    elif control_data.get("type") == "barge_in_detected" and conv_id_to_stop:
                        logger.info(f"TTS Service: Received 'barge_in_detected' event for conv_id '{conv_id_to_stop}'.")
                        should_stop = True
                    
                    if should_stop and conv_id_to_stop:
                        if conv_id_to_stop in active_synthesis_tasks:
                            task, stop_event = active_synthesis_tasks[conv_id_to_stop]
                            stop_event.set() # Signal the synthesis loop to stop
                            if not task.done():
                                task.cancel() # Cancel the task
                                try:
                                    await task # Await cancellation to propagate
                                except asyncio.CancelledError:
                                    logger.info(f"TTS Service: Synthesis task for conv_id '{conv_id_to_stop}' cancelled due to control/barge-in event.")
                                except Exception as e_task_await:
                                    logger.error(f"TTS Service: Error awaiting cancelled task for '{conv_id_to_stop}': {e_task_await}", exc_info=True)

                            # Clean up from active_synthesis_tasks is handled in process_tts_request's finally block
                            # or can be done here if immediate removal is desired post-cancellation.
                            # For safety, let the original finally block in process_tts_request handle it.
                            logger.info(f"TTS Service: Signaled stop and cancelled task for conv_id '{conv_id_to_stop}'.")
                        else:
                            logger.info(f"TTS Service: No active synthesis task found to stop for conv_id '{conv_id_to_stop}'.")
                    elif not conv_id_to_stop and (control_data.get("command") == "stop_tts" or control_data.get("type") == "barge_in_detected"):
                        logger.warning(f"TTS Service: Received stop/barge-in event without conversation_id: {control_data_str}")

                except json.JSONDecodeError:
                    logger.error(f"TTS Service: Error decoding TTS control/barge-in JSON: {control_data_str}", exc_info=True)
            elif message is None: await asyncio.sleep(0.01)
        except redis.RedisError as e:
            logger.error(f"TTS Service: Redis error in TTS control subscription loop: {e}", exc_info=True)
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"TTS Service: Error in TTS control subscription loop: {e}", exc_info=True)
            await asyncio.sleep(1)
    try: await pubsub.unsubscribe(tts_settings.TTS_CONTROL_CHANNEL)
    except redis.RedisError: pass
    try: await pubsub.close()
    except redis.RedisError: pass

def signal_handler_tts(signum, frame):
    global running
    if running:
        logger.info(f"Signal {signum} received by TTS service, initiating shutdown...")
        running = False
    else:
        logger.info(f"Signal {signum} received by TTS service, shutdown already in progress.")

async def main_async_tts():
    global running
    signal.signal(signal.SIGINT, signal_handler_tts)
    signal.signal(signal.SIGTERM, signal_handler_tts)
    logger.info("Starting TTS Service...")
    redis_client = None
    request_subscriber_task = None
    control_subscriber_task = None
    synthesizer_instance: Optional[AbstractTTSService] = None

    try:
        synthesizer_instance = get_tts_service_instance()
        logger.info(f"TTS Synthesizer '{tts_settings.TTS_PROVIDER}' initialized.")

        redis_client = redis.Redis(
            host=tts_settings.REDIS_HOST, port=tts_settings.REDIS_PORT,
            db=tts_settings.REDIS_DB, password=tts_settings.REDIS_PASSWORD,
            auto_close_connection_pool=False, 
            decode_responses=False
        )
        await redis_client.ping()
        logger.info("TTS Service connected to Redis.")
        
        request_subscriber_task = asyncio.create_task(subscribe_to_tts_requests(redis_client, synthesizer_instance))
        control_subscriber_task = asyncio.create_task(subscribe_to_tts_control(redis_client))
        
        logger.info("TTS Service has started successfully and is now processing requests.")
        
        while running:
            await asyncio.sleep(0.5)
            if request_subscriber_task and request_subscriber_task.done():
                logger.error("TTS request subscriber task ended prematurely.")
                running = False
                break
            if control_subscriber_task and control_subscriber_task.done():
                logger.error("TTS control subscriber task ended prematurely.")
                running = False
                break
        
    except (FileNotFoundError, ValueError, NotImplementedError) as e: 
        logger.critical(f"TTS Service: Synthesizer initialization error: {e}. Cannot start.", exc_info=True)
    except redis.exceptions.ConnectionError as e:
        logger.critical(f"TTS Service: Redis connection error: {e}. Cannot start.", exc_info=True)
    except Exception as e:
        logger.critical(f"TTS Service: Unexpected critical error in main_async_tts: {e}", exc_info=True)
    finally:
        logger.info("TTS Service shutting down...")
        running = False

        tasks_to_cancel = []
        if request_subscriber_task and not request_subscriber_task.done(): tasks_to_cancel.append(request_subscriber_task)
        if control_subscriber_task and not control_subscriber_task.done(): tasks_to_cancel.append(control_subscriber_task)
        
        for conv_id, (task, stop_event) in list(active_synthesis_tasks.items()):
            logger.info(f"TTS Service: Cleaning up active synthesis for conv_id '{conv_id}' on shutdown.")
            if not stop_event.is_set(): stop_event.set()
            if not task.done(): tasks_to_cancel.append(task)
        
        if tasks_to_cancel:
            logger.info(f"Cancelling {len(tasks_to_cancel)} tasks...")
            for task in tasks_to_cancel:
                task.cancel()
            results = await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, asyncio.CancelledError):
                    logger.info(f"Task {tasks_to_cancel[i].get_name()} was cancelled successfully.")
                elif isinstance(result, Exception):
                    logger.error(f"Error during task {tasks_to_cancel[i].get_name()} cancellation/cleanup: {result}", exc_info=result)

        if redis_client:
            try: 
                await redis_client.close()
                logger.info("TTS Service Redis client closed.")
            except redis.RedisError as e:
                logger.error(f"Error closing Redis client: {e}", exc_info=True)
        
        logger.info("TTS Service has shut down.")

def main():
    logger.info(f"TTS Service configured to use LOG_LEVEL: {tts_settings.LOG_LEVEL}") 

    try: 
        asyncio.run(main_async_tts())
    except KeyboardInterrupt: 
        logger.info("TTS Service main: KeyboardInterrupt received. Shutdown should be in progress via signal handler.")

if __name__ == "__main__":
    main() 