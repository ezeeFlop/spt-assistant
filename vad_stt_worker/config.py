from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field # Import Field
from typing import Optional
import torch # Import torch at the top

class WorkerSettings(BaseSettings):
    # Redis settings (should match the gateway's publishing channel)
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None
    
    AUDIO_STREAM_CHANNEL: str = "audio_stream_channel"    # Channel to receive audio chunks from API gateway
    TRANSCRIPT_CHANNEL: str = "transcript_channel"      # Channel to publish ASR results to
    BARGE_IN_CHANNEL: str = "barge_in_notifications"   # Channel to publish barge-in events to
    TTS_ACTIVE_STATE_PREFIX: str = "tts_active_state:"  # Redis key prefix to check if TTS is active (align with tts_service)

    # VAD Settings (Silero)
    VAD_MODEL_REPO: str = "snakers4/silero-vad"
    VAD_MODEL_NAME: str = "silero_vad"
    VAD_ONNX: bool = False # Whether to use ONNX version of VAD model
    VAD_SAMPLING_RATE: int = 16000 # Expected sample rate by VAD model (and Whisper)
    VAD_THRESHOLD: float = 0.7 # Speech probability threshold
    VAD_MIN_SILENCE_DURATION_MS: int = 2500 # Min silence duration (ms) to break speech segment. Increased from 100ms.
    VAD_SPEECH_PAD_MS: int = 300 # Pad speech segment (ms)

    # STT Settings (faster-whisper)
    # FR-03: faster-whisper with openai/whisper-large-v3 French fine-tune
    STT_MODEL_NAME: str = "brandenkmurray/faster-whisper-large-v3-french-distil-dec16"
    
    # User can set STT_DEVICE in .env to override auto-detection
    STT_DEVICE_FROM_ENV: Optional[str] = Field(default=None, alias='STT_DEVICE')

    # This is the field the application code should use. It's determined in __init__.
    # Provide a default that passes initial validation.
    # detect device from environment or auto-detect if not set.
    FINAL_STT_DEVICE: str = "cpu"

    STT_COMPUTE_TYPE: str = "int8" # e.g., float16, int8 for faster-whisper. Adjust based on available hardware and desired trade-off.
    STT_BEAM_SIZE: int = 5
    STT_LANGUAGE: str = "fr" # FR-03: French fine-tune
    STT_PARTIAL_TRANSCRIPT_INTERVAL_MS: int = 300 # FR-03: Emit partials every <=300ms

    LOG_LEVEL: str = "INFO"

    WORKER_PROCESSOR_INACTIVITY_TIMEOUT_S: int = 120 # Timeout for inactive AudioProcessors

    model_config = SettingsConfigDict(env_file="vad_stt_worker/.env", env_file_encoding='utf-8', extra="ignore")

    def __init__(self, **kwargs):
        super().__init__(**kwargs) # Initialize from .env and defaults from BaseSettings

        detected_device = "cpu" # Default to CPU

        if self.STT_DEVICE_FROM_ENV:
            env_device = self.STT_DEVICE_FROM_ENV.lower()
            if env_device in ["cpu", "cuda", "mps"]:
                detected_device = env_device
                # print(f"VAD Worker: Using STT_DEVICE from environment: {detected_device}") # For debugging
            # else:
                # print(f"VAD Worker: Invalid STT_DEVICE='{self.STT_DEVICE_FROM_ENV}' in .env. Falling back to auto-detection.") # For debugging
                # Fall through to auto-detection logic below if invalid value from env

        # If not set via env or if env value was invalid and resulted in 'cpu' (or we just want to auto-detect anyway)
        # Re-evaluate only if detected_device is still "cpu" (meaning not a valid cuda/mps from env)
        # or if STT_DEVICE_FROM_ENV was not set at all.
        if detected_device == "cpu": # Only auto-detect if current choice is CPU (either default or invalid env)
            try:
                if torch.cuda.is_available():
                    detected_device = "cuda"
                # Remove MPS check as faster-whisper/ctranslate2 doesn't support it
                # elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available() and torch.backends.mps.is_built():
                #     detected_device = "mps"
                # print(f"VAD Worker: Auto-detected STT_DEVICE: {detected_device}") # For debugging
            except ImportError:
                # print("VAD Worker: PyTorch not found. STT_DEVICE defaulting to 'cpu'.") # For debugging
                detected_device = "cpu" 
            except Exception: # Catch any other error during detection
                # print(f"VAD Worker: Error during STT device auto-detection: {e}. Defaulting to CPU.") # For debugging
                detected_device = "cpu"
        
        # Use super().__setattr__ to assign to the field in the Pydantic model
        # This is necessary because Pydantic models might be frozen or have other protections
        super().__setattr__('FINAL_STT_DEVICE', detected_device)

worker_settings = WorkerSettings() 