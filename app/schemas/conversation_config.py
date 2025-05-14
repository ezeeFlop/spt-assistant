from pydantic import BaseModel, Field
from typing import Optional

class ConversationConfigBase(BaseModel):
    llm_model_name: Optional[str] = Field(None, description="Name of the LLM model to use for this conversation.")
    llm_temperature: Optional[float] = Field(None, ge=0.0, le=2.0, description="LLM temperature for this conversation.")
    llm_max_tokens: Optional[int] = Field(None, gt=0, description="LLM max tokens for responses in this conversation.")
    tts_voice_id: Optional[str] = Field(None, description="Identifier for the TTS voice to be used.")
    vad_aggressiveness: Optional[int] = Field(None, ge=0, le=3, description="VAD aggressiveness level (e.g., 0-3 as in WebRTC VAD).")
    # Add other configurable parameters as needed (e.g., LLM endpoint, specific STT model variant for this convo)

class ConversationConfigCreate(ConversationConfigBase):
    pass

class ConversationConfigUpdate(ConversationConfigBase):
    pass

class ConversationConfigResponse(ConversationConfigBase):
    conversation_id: str
    # Include all fields, even if None, to show current config
    llm_model_name: Optional[str] = None
    llm_temperature: Optional[float] = None
    llm_max_tokens: Optional[int] = None
    tts_voice_id: Optional[str] = None
    vad_aggressiveness: Optional[int] = None

    class Config:
        from_attributes = True # Renamed from orm_mode in Pydantic v2 