"""Configuration settings for the SPT Assistant Python client."""

import os
from typing import Optional
from pydantic_settings import BaseSettings


class ClientSettings(BaseSettings):
    """Client configuration settings."""
    
    # WebSocket connection
    WEBSOCKET_URL: str = "ws://localhost:8000/api/v1/ws/audio"
    
    # Audio settings (matching frontend)
    SAMPLE_RATE: int = 16000  # Target sample rate for audio input (matches frontend)
    CHANNELS: int = 1  # Mono audio
    CHUNK_SIZE: int = 4096  # Audio chunk size (256ms at 16kHz)
    FORMAT_BITS: int = 16  # 16-bit audio
    
    # TTS audio settings (server may send different rates)
    EXPECTED_TTS_SAMPLE_RATE: int = 24000  # Common TTS output rate (XTTS v2 default)
    
    # Audio device settings
    INPUT_DEVICE_INDEX: Optional[int] = None  # None = default device
    OUTPUT_DEVICE_INDEX: Optional[int] = None  # None = default device
    
    # Volume settings
    OUTPUT_VOLUME: float = 1.0  # 0.0 to 2.0 (200% max)
    
    # Processing settings
    AUDIO_BUFFER_SIZE: int = 8192  # Internal buffer size
    MAX_RECONNECT_ATTEMPTS: int = 5
    RECONNECT_DELAY: float = 5.0  # seconds
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # Audio processing - relies on system's built-in features (like browser getUserMedia)
    # echoCancellation: true, noiseSuppression: true, autoGainControl: true
    # These are handled at the system/driver level, not in application code
    
    class Config:
        env_file = ".env"
        env_prefix = "SPT_CLIENT_"


# Global settings instance
settings = ClientSettings() 