from abc import ABC, abstractmethod
import asyncio
from typing import AsyncIterator, List, Dict, Optional, Any

class AbstractTTSService(ABC):
    """
    Abstract Base Class for Text-to-Speech services within the tts_service module.
    """

    @abstractmethod
    async def synthesize_stream(self, text: str, voice_id: Optional[str] = None, stop_event: Optional[asyncio.Event] = None, **kwargs: Any) -> AsyncIterator[bytes]:
        """
        Synthesizes speech from the given text and streams audio data.

        Args:
            text: The text to synthesize.
            voice_id: Optional identifier for the voice to be used.
            stop_event: Optional asyncio.Event to signal premature stream termination.
            **kwargs: Additional provider-specific options.

        Yields:
            Audio data as bytes chunks.
        """
        # This is an abstract method, so it must be an empty generator.
        if False: # pragma: no cover
            yield b'' # pragma: no cover

    @abstractmethod
    async def get_available_voices(self) -> List[Dict[str, Any]]:
        """
        Retrieves a list of available voices for the TTS engine.
        Each voice should be a dictionary with at least an 'id' and 'name'.
        Example: [{'id': 'voice_1', 'name': 'Default Male', 'language': 'en', 'provider': 'piper'}, ...]

        Returns:
            A list of voice description dictionaries.
        """
        pass

    async def stop_synthesis(self) -> None:
        """
        Optional: Signals any ongoing synthesis for this instance to stop.
        Concrete implementations should override if they support stoppable synthesis.
        """
        # Default implementation does nothing.
        pass 