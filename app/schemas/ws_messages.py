from typing import Literal, Optional
from pydantic import BaseModel, Field

class WSPartialMessage(BaseModel):
    type: Literal["partial"] = "partial"
    text: str
    timestamp: int # Assuming this is a Unix timestamp or similar numeric representation

class WSFinalMessage(BaseModel):
    type: Literal["final"] = "final"
    text: str

class WSTokenMessage(BaseModel):
    type: Literal["token"] = "token"
    role: Literal["assistant", "user", "system"] # Assuming role can be assistant, user or system
    content: str

class WSToolMessage(BaseModel):
    type: Literal["tool"] = "tool"
    name: str
    status: Literal["running", "completed", "failed"] # Assuming these statuses
    # Depending on the tool, you might add 'arguments' or 'result' fields

class WSAudioMessage(BaseModel):
    type: Literal["audio"] = "audio"
    url: str # URL to the audio blob
    end: bool # True if this is the final audio chunk for the current TTS turn

# A Union type could be useful if you need to validate against any of these types
# from typing import Union
# WSMessage = Union[WSPartialMessage, WSFinalMessage, WSTokenMessage, WSToolMessage, WSAudioMessage] 