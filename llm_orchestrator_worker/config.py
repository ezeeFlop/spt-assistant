from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List, Dict
import pathlib

SERVICE_ROOT = pathlib.Path(__file__).resolve().parent
PROJECT_ROOT = SERVICE_ROOT.parent # Assuming llm_orchestrator_worker is one level down from project root

class OrchestratorSettings(BaseSettings):
    # Redis settings
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None
    TRANSCRIPT_CHANNEL: str = "transcript_channel"     # Channel to subscribe to for ASR results
    LLM_TOKEN_CHANNEL: str = "llm_token_channel"       # Channel to publish LLM stream tokens to
    LLM_TOOL_CALL_CHANNEL: str = "llm_tool_call_channel" # Channel to publish LLM tool calls to
    TTS_REQUEST_CHANNEL: str = "tts_request_channel"   # Channel to publish TTS synthesis requests to
    TTS_CONTROL_CHANNEL: str = "tts_control_channel"   # Channel to publish TTS control commands (e.g., stop)
    BARGE_IN_CHANNEL: str = "barge_in_notifications"  # Channel to subscribe to for barge-in events
    CONVERSATION_CONFIG_PREFIX: str = "conversation_config:" # Redis key prefix for storing conversation configs
    CONVERSATION_HISTORY_PREFIX: str = "conversation_history:" # Redis key prefix for history
    CONVERSATION_DATA_TTL_SECONDS: int = 24 * 60 * 60 # TTL for conversation data in Redis (e.g., 1 day)

    # LLM Settings (FR-05)
    LLM_PROVIDER: str = "ollama" # e.g., "openai", "anthropic", "ollama"
    LLM_API_KEY: Optional[str] = "your_openai_api_key_here" # Keep sensitive keys out of code
    LLM_MODEL_NAME: str = "gemma3" # Default model
    LLM_BASE_URL: Optional[str] = "http://localhost:11434" # For self-hosted LLMs like Ollama or VLLM
    LLM_MAX_TOKENS: int = 1000
    
    LLM_TEMPERATURE: float = 0.7
    # Define a default conversation history length
    MAX_CONVERSATION_HISTORY: int = 10 # Number of turns (user + assistant) to keep
    SYSTEM_PROMPT: str = "You are a helpful French voice assistant, your name is TARA. Make sure to NEVER generate MARKDOWN or HTML code in your responses."

    # Default TTS voice if not specified in conversation config (should match a key from tts_service)
    #DEFAULT_TTS_VOICE_ID: Optional[str] = "fr_FR-siwis-medium.onnx" # Example default
    DEFAULT_TTS_VOICE_ID: Optional[str] = "Claribel Dervla" # Example default
    # Tool Settings (FR-06) - Placeholder for MCP client config
    MCP_CLIENT_CONFIG_PATH: Optional[str] = None 

    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file= str(SERVICE_ROOT / ".env"), # Expects .env in llm_orchestrator_worker/ directory
        extra="ignore",
        env_nested_delimiter='__'
    )

orchestrator_settings = OrchestratorSettings() 