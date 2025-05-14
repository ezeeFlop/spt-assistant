import asyncio
from typing import AsyncIterator, List, Dict, Optional, Any
from elevenlabs.client import AsyncElevenLabs
from elevenlabs import Voice, VoiceSettings
# pydub and io are no longer needed for direct PCM output
# from pydub import AudioSegment
# from pydub.utils import mediainfo
# import io

from tts_worker.core.tts_abc import AbstractTTSService
from tts_worker.logging_config import get_logger

logger = get_logger(__name__)

# ELEVENLABS_API_BASE_URL is not strictly needed when using the SDK client directly,
# but can be kept for reference or if other direct API calls were ever needed.
ELEVENLABS_API_BASE_URL = "https://api.elevenlabs.io/v1"

class ElevenLabsTTSService(AbstractTTSService):
    def __init__(
        self,
        api_key: str,
        default_voice_id: str, # This will map to a voice name or ID in ElevenLabs
        target_sample_rate: int = 16000, # Default to 16kHz PCM s16le as per FR-01 and frontend capability
        # api_base_url is handled by the SDK client
    ):
        if not api_key:
            logger.error("ElevenLabs API key is required.")
            raise ValueError("ElevenLabs API key is required.")
        
        self.client = AsyncElevenLabs(api_key=api_key)
        self.default_voice_id = default_voice_id
        self.target_sample_rate = target_sample_rate
        # Determine the PCM output format string based on the target sample rate
        # Assuming s16le is implicitly handled by requesting pcm_<rate>
        self.pcm_output_format = f"pcm_{self.target_sample_rate}"
        logger.info(f"ElevenLabsTTSService initialized. Default voice ID: {default_voice_id}. Requesting PCM format: {self.pcm_output_format}")

    async def synthesize_stream(self, text: str, voice_id: Optional[str] = None, stop_event: Optional[asyncio.Event] = None, **kwargs: Any) -> AsyncIterator[bytes]:
        selected_voice_id = voice_id or self.default_voice_id
        
        model_id = kwargs.get("model_id", "eleven_multilingual_v2")
        stability = kwargs.get("stability", 0.75)
        similarity_boost = kwargs.get("similarity_boost", 0.75)
        style = kwargs.get("style", 0.0)
        use_speaker_boost = kwargs.get("use_speaker_boost", True)

        # Use the PCM output format determined in __init__
        # Allow override via kwargs if necessary for specific calls, though generally we'll stick to the initialized target.
        current_output_format = kwargs.get("output_format", self.pcm_output_format)

        voice_settings_obj = VoiceSettings(
            stability=stability,
            similarity_boost=similarity_boost,
            style=style,
            use_speaker_boost=use_speaker_boost
        )

        logger.info(f"ElevenLabs SDK: Synthesizing text for voice '{selected_voice_id}' ('{text[:30]}...') with model '{model_id}'. Output format: {current_output_format}. Settings: {voice_settings_obj}")

        try:
            audio_stream = self.client.text_to_speech.convert_as_stream(
                text=text,
                voice_id=selected_voice_id,
                model_id=model_id,
                #voice_settings=voice_settings_obj, # Note: SDK might take VoiceSettings instance directly
                output_format=current_output_format # Request direct PCM output
            )
            
            async for chunk in audio_stream:
                if stop_event and stop_event.is_set():
                    logger.info("ElevenLabs SDK stream: Stop event received, breaking from stream.")
                    break
                if chunk:
                    yield chunk # Yield PCM chunk directly
            
            logger.info(f"ElevenLabs SDK: PCM Stream finished for voice '{selected_voice_id}'.")

        except Exception as e:
            logger.error(f"ElevenLabs SDK error during synthesis stream: {e}", exc_info=True)
            # Re-raise to allow higher-level error handling
            raise

    async def get_available_voices(self) -> List[Dict[str, Any]]:
        voices_list: List[Dict[str, Any]] = []
        try:
            logger.info("ElevenLabs SDK: Fetching available voices.")
            response = await self.client.voices.get_all()
            if response and response.voices:
                for voice_obj in response.voices: # voice_obj is of type Voice from the SDK
                    labels = voice_obj.labels if voice_obj.labels else {}
                    voices_list.append({
                        "id": voice_obj.voice_id,
                        "name": voice_obj.name,
                        "gender": labels.get("gender"),
                        "accent": labels.get("accent"),
                        "age": labels.get("age"),
                        "description": labels.get("description"),
                        "category": voice_obj.category, # e.g., 'cloned', 'premade'
                        "provider": "elevenlabs"
                    })
                logger.info(f"Retrieved {len(voices_list)} voices from ElevenLabs using SDK.")
            else:
                logger.warning("ElevenLabs SDK /voices endpoint did not return expected voice list structure.")
        except Exception as e:
            logger.error(f"ElevenLabs SDK error fetching voices: {e}", exc_info=True)
        return voices_list

    async def stop_synthesis(self) -> None:
        # The SDK's stream is an async iterator. Stopping consumption (by breaking the loop
        # in synthesize_stream when stop_event is set) is the primary way to stop.
        # There isn't a direct 'stop' method on the client for an ongoing stream in the same
        # way one might manage a subprocess.
        logger.info("ElevenLabsTTSService (SDK): stop_synthesis called. Relies on stop_event in synthesize_stream to break iteration.")
        pass 