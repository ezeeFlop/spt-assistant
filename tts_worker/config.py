from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, Literal
import pathlib

# Define project root relative to this config file for the standalone service
# This config.py is in tts_service/, so its root is the parent directory.
SERVICE_ROOT = pathlib.Path(__file__).resolve().parent
PROJECT_ROOT = SERVICE_ROOT.parent # Assuming tts_worker is one level down from project root

class PiperSettings(BaseSettings):
    EXECUTABLE_PATH: str = str(PROJECT_ROOT / "piper_tts_install" / "piper_executable" / "piper" / "piper")
    VOICES_DIR: str = str(PROJECT_ROOT / "piper_tts_install" / "voices")
    DEFAULT_VOICE_MODEL: str = "fr_FR-siwis-medium.onnx"
    NATIVE_SAMPLE_RATE: int = 22050
    model_config = SettingsConfigDict(env_prefix='PIPER_')

class ElevenLabsSettings(BaseSettings):
    API_KEY: Optional[str] = "APIKEY"
    DEFAULT_VOICE_ID: str = "pNInz6obpgDQGcFmaJgB" # Example: Rachel
    # XI_API_BASE_URL: str = "https://api.elevenlabs.io/v1"
    model_config = SettingsConfigDict(env_prefix='ELEVENLABS_')

class CoquiSettings(BaseSettings):
    DEFAULT_MODEL_NAME: str = "tts_models/multilingual/multi-dataset/xtts_v2"
    DEFAULT_LANGUAGE: str = "fr"
    NATIVE_SAMPLE_RATE: int = 24000
    model_config = SettingsConfigDict(env_prefix='COQUI_')

class TTSServiceSettings(BaseSettings):
    # Service Operation
    LOG_LEVEL: str = "INFO"
    TTS_PROVIDER: Literal["piper", "elevenlabs", "coqui"] = "coqui"

    # Redis settings (for communication, not for the main app's Redis use)
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None
    TTS_REQUEST_CHANNEL: str = "tts_request_channel"
    AUDIO_OUTPUT_STREAM_CHANNEL_PATTERN: str = "audio_output_stream:{conversation_id}"
    TTS_ACTIVE_STATE_PREFIX: str = "tts_active_state:"
    TTS_CONTROL_CHANNEL: str = "tts_control_channel"
    AUDIO_STREAM_CHANNEL: str = "audio_stream_channel"    # Channel to receive audio chunks from API gateway
    TRANSCRIPT_CHANNEL: str = "transcript_channel"      # Channel to publish ASR results to
    BARGE_IN_CHANNEL: str = "barge_in_notifications"   # Channel to publish barge-in events to
 
    TTS_ACTIVE_STATE_TTL_SECONDS: int = 60

    # Audio output format from this service
    AUDIO_OUTPUT_SAMPLE_RATE: int = 24000
    AUDIO_OUTPUT_CHANNELS: int = 1
    AUDIO_OUTPUT_SAMPLE_WIDTH: int = 2 # Bytes per sample (16-bit PCM = 2 bytes)
    TTS_AUDIO_CHUNK_SIZE_MS: int = 100

    # Provider-specific settings
    piper: PiperSettings = PiperSettings()
    elevenlabs: ElevenLabsSettings = ElevenLabsSettings()
    coqui: CoquiSettings = CoquiSettings()
    model_config = SettingsConfigDict(
        env_file= str(SERVICE_ROOT / ".env"), # Expects .env in tts_service/ directory
        extra="ignore",
        env_nested_delimiter='__'
    )

tts_settings = TTSServiceSettings() 