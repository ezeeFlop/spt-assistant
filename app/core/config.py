from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "Voice Assistant Platform"
    API_V1_STR: str = "/api/v1"
    
    # Redis settings
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None
    AUDIO_STREAM_CHANNEL: str = "audio_stream_channel" # Channel to publish JSON audio messages with conversation_id
    TRANSCRIPT_CHANNEL: str = "transcript_channel"   # Channel VAD/STT worker publishes transcripts to
    CONVERSATION_CONFIG_PREFIX: str = "conversation_config:" # Redis key prefix for storing conversation configs
    LLM_TOKEN_CHANNEL: str = "llm_token_channel"       # Channel LLM Orchestrator publishes stream tokens to
    LLM_TOOL_CALL_CHANNEL: str = "llm_tool_call_channel" # Channel LLM Orchestrator publishes tool calls/status to
    AUDIO_OUTPUT_STREAM_CHANNEL_PATTERN: str = "audio_output_stream:{conversation_id}" # Pattern for TTS audio output
    BARGE_IN_CHANNEL: str = "barge_in_notifications"  # Channel VAD worker publishes barge-in events to
    CONNECTION_EVENTS_CHANNEL: str = "connection_events"  # New channel for connection lifecycle events
    VITE_API_BASE_URL: str = "ws://localhost:8000/api/v1/ws/audio"

    # JWT Settings (FR-Security)
    JWT_SECRET_KEY: str = "your-super-secret-key-please-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 # 24 hours

    # Environment file settings
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings() 