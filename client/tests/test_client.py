"""Basic tests for SPT Assistant Python Client."""

import pytest
from unittest.mock import Mock, patch
from spt_assistant_client import SPTClient, settings, AudioProcessor


def test_client_import():
    """Test that the client can be imported successfully."""
    assert SPTClient is not None
    assert settings is not None
    assert AudioProcessor is not None


def test_client_initialization():
    """Test that the client can be initialized."""
    client = SPTClient()
    assert client is not None
    assert client.is_recording is False
    assert client.is_playing_audio is False
    assert client.chat_messages == []


def test_settings_default_values():
    """Test that settings have expected default values."""
    assert settings.WEBSOCKET_URL == "ws://localhost:8000/api/v1/ws/audio"
    assert settings.SAMPLE_RATE == 16000
    assert settings.CHANNELS == 1
    assert settings.CHUNK_SIZE == 4096


@patch('spt_assistant_client.audio_processor.pyaudio.PyAudio')
def test_audio_processor_initialization(mock_pyaudio):
    """Test that AudioProcessor can be initialized."""
    mock_callback = Mock()
    processor = AudioProcessor(mock_callback)
    assert processor is not None
    assert processor.on_audio_chunk == mock_callback


def test_chat_message_creation():
    """Test ChatMessage creation."""
    from spt_assistant_client.spt_client import ChatMessage
    
    message = ChatMessage("user", "Hello, world!")
    assert message.type == "user"
    assert message.content == "Hello, world!"
    assert message.id is not None
    assert message.timestamp is not None 