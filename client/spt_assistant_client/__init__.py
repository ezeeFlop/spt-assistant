"""SPT Assistant Python Client Package."""

from .spt_client import SPTClient, main
from .config import settings
from .audio_processor import AudioProcessor
from .websocket_client import WebSocketClient

__version__ = "1.0.0"
__author__ = "SPT Assistant Team"
__description__ = "Python client for SPT Assistant voice interface"

__all__ = [
    "SPTClient",
    "main",
    "settings",
    "AudioProcessor", 
    "WebSocketClient"
] 