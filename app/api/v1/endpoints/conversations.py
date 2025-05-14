from fastapi import APIRouter, HTTPException, Path, Body, status
from typing import Dict, Any, Optional
import json # For serializing/deserializing config in Redis

from app.schemas.conversation_config import ConversationConfigUpdate, ConversationConfigResponse
from app.core.logging_config import get_logger
from app.services.redis_service import redis_service # Import global redis_service
from app.core.config import settings # Import settings for prefix

logger = get_logger(__name__)
router = APIRouter()

# _conversation_configs: Dict[str, Dict[str, Any]] = {} # Removed in-memory store

@router.post(
    "/conversations/{conversation_id}/config", 
    response_model=ConversationConfigResponse,
    status_code=status.HTTP_200_OK,
    summary="Update or Create Conversation Configuration (FR-09, 7.2)"
)
async def update_conversation_configuration(
    conversation_id: str = Path(..., description="The unique identifier for the conversation."),
    config_update: ConversationConfigUpdate = Body(..., description="Configuration settings to update.")
) -> ConversationConfigResponse:
    """
    Updates the configuration for a specific conversation. 
    If the conversation ID doesn't exist, it creates a new configuration entry.
    Allows changing model, voice, VAD mode, etc. (FR-09)
    """
    logger.info(f"Updating configuration for conversation_id: {conversation_id} with: {config_update.model_dump(exclude_unset=True)}")
    
    redis_key = f"{settings.CONVERSATION_CONFIG_PREFIX}{conversation_id}"
    r_client = await redis_service.get_redis_client()
    
    current_config_json = await r_client.get(redis_key)
    current_config = json.loads(current_config_json) if current_config_json else {}
    
    update_data = config_update.model_dump(exclude_unset=True)
    
    for key, value in update_data.items():
        if value is not None:
            current_config[key] = value
    
    await r_client.set(redis_key, json.dumps(current_config))
    # TODO: Add TTL for conversation configs in Redis?
    # Example: await r_client.expire(redis_key, timedelta(hours=24))
    
    response_data = {
        "conversation_id": conversation_id,
        "llm_model_name": current_config.get("llm_model_name"),
        "llm_temperature": current_config.get("llm_temperature"),
        "llm_max_tokens": current_config.get("llm_max_tokens"),
        "tts_voice_id": current_config.get("tts_voice_id"),
        "vad_aggressiveness": current_config.get("vad_aggressiveness"),
    }
    
    logger.info(f"Updated configuration for '{conversation_id}' in Redis: {response_data}")
    return ConversationConfigResponse(**response_data)

@router.get(
    "/conversations/{conversation_id}/config",
    response_model=ConversationConfigResponse,
    summary="Get Conversation Configuration"
)
async def get_conversation_configuration(
    conversation_id: str = Path(..., description="The unique identifier for the conversation.")
) -> ConversationConfigResponse:
    """
    Retrieves the current configuration for a specific conversation.
    """
    logger.debug(f"Fetching configuration for conversation_id: {conversation_id} from Redis")
    redis_key = f"{settings.CONVERSATION_CONFIG_PREFIX}{conversation_id}"
    r_client = await redis_service.get_redis_client()
    
    config_json = await r_client.get(redis_key)
    
    if not config_json:
        logger.warning(f"No specific configuration found in Redis for conversation_id: {conversation_id}. Returning defaults.")
        # Return a default response indicating no specific overrides are set for this conversation_id
        return ConversationConfigResponse(
            conversation_id=conversation_id, 
            llm_model_name=None, # Client can infer global default from orchestrator_settings if needed
            llm_temperature=None,
            llm_max_tokens=None,
            tts_voice_id=None,   
            vad_aggressiveness=None 
        )
        # Alternative: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Configuration for conversation '{conversation_id}' not found.")

    config = json.loads(config_json)
    response_data = {
        "conversation_id": conversation_id,
        "llm_model_name": config.get("llm_model_name"),
        "llm_temperature": config.get("llm_temperature"),
        "llm_max_tokens": config.get("llm_max_tokens"),
        "tts_voice_id": config.get("tts_voice_id"),
        "vad_aggressiveness": config.get("vad_aggressiveness"),
    }
    return ConversationConfigResponse(**response_data)

# TODO: The LLM Orchestrator and TTS Service will need a way to fetch this configuration.
# This is now handled by the LLM Orchestrator directly accessing Redis with the same prefix. 