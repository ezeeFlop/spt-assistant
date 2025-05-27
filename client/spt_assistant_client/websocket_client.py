"""WebSocket client for SPT Assistant Python client."""

import asyncio
import json
import logging
import time
from typing import Callable, Optional, Dict, Any, Union
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException

from .config import settings


logger = logging.getLogger(__name__)


class WebSocketClient:
    """WebSocket client that handles communication with the SPT Assistant backend."""
    
    def __init__(
        self,
        on_message: Callable[[Dict[str, Any]], None],
        on_audio_chunk: Callable[[bytes], None],
        on_connect: Optional[Callable[[], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[Exception], None]] = None
    ):
        self.url = settings.WEBSOCKET_URL
        self.on_message = on_message
        self.on_audio_chunk = on_audio_chunk
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.on_error = on_error
        
        # Connection state
        self.websocket: Optional[websockets.WebSocketServerProtocol] = None
        self.is_connected = False
        self.should_reconnect = True
        self.reconnect_attempts = 0
        
        # Conversation state
        self.active_conversation_id: Optional[str] = None
        
        # Tasks
        self.connection_task: Optional[asyncio.Task] = None
        self.message_handler_task: Optional[asyncio.Task] = None
        
        logger.info(f"WebSocketClient initialized for URL: {self.url}")
    
    async def connect(self) -> bool:
        """Connect to the WebSocket server."""
        try:
            logger.info(f"Connecting to WebSocket: {self.url}")
            self.websocket = await websockets.connect(
                self.url,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=10
            )
            
            self.is_connected = True
            self.reconnect_attempts = 0
            
            # Start message handler
            self.message_handler_task = asyncio.create_task(self._message_handler())
            
            if self.on_connect:
                self.on_connect()
            
            logger.info("WebSocket connected successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to WebSocket: {e}")
            self.is_connected = False
            if self.on_error:
                self.on_error(e)
            return False
    
    async def disconnect(self):
        """Disconnect from the WebSocket server."""
        self.should_reconnect = False
        self.is_connected = False
        
        if self.message_handler_task:
            self.message_handler_task.cancel()
            try:
                await self.message_handler_task
            except asyncio.CancelledError:
                pass
        
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
        
        if self.on_disconnect:
            self.on_disconnect()
        
        logger.info("WebSocket disconnected")
    
    async def send_audio_chunk(self, audio_data: bytes):
        """Send binary audio data to the server."""
        if not self.is_connected or not self.websocket:
            logger.warning("Cannot send audio chunk: WebSocket not connected")
            return
        
        try:
            await self.websocket.send(audio_data)
            logger.debug(f"Sent audio chunk: {len(audio_data)} bytes")
        except Exception as e:
            logger.error(f"Failed to send audio chunk: {e}")
            if self.on_error:
                self.on_error(e)
    
    async def send_json_message(self, message: Dict[str, Any]):
        """Send JSON message to the server."""
        if not self.is_connected or not self.websocket:
            logger.warning("Cannot send JSON message: WebSocket not connected")
            return
        
        try:
            await self.websocket.send(json.dumps(message))
            logger.debug(f"Sent JSON message: {message}")
        except Exception as e:
            logger.error(f"Failed to send JSON message: {e}")
            if self.on_error:
                self.on_error(e)
    
    async def _message_handler(self):
        """Handle incoming WebSocket messages."""
        try:
            async for message in self.websocket:
                if isinstance(message, bytes):
                    # Binary audio data
                    logger.debug(f"Received audio chunk: {len(message)} bytes")
                    if self.on_audio_chunk:
                        self.on_audio_chunk(message)
                elif isinstance(message, str):
                    # JSON message
                    try:
                        parsed_message = json.loads(message)
                        logger.debug(f"Received JSON message: {parsed_message.get('type', 'unknown')}")
                        
                        # Handle conversation ID tracking
                        if parsed_message.get('type') == 'system_event' and parsed_message.get('event') == 'conversation_started':
                            self.active_conversation_id = parsed_message.get('conversation_id')
                            logger.info(f"Conversation started: {self.active_conversation_id}")
                        
                        if self.on_message:
                            self.on_message(parsed_message)
                            
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse JSON message: {e}")
                        logger.debug(f"Raw message: {message}")
                else:
                    logger.warning(f"Received unknown message type: {type(message)}")
                    
        except ConnectionClosed:
            logger.info("WebSocket connection closed")
            self.is_connected = False
        except Exception as e:
            logger.error(f"Error in message handler: {e}")
            self.is_connected = False
            if self.on_error:
                self.on_error(e)
        finally:
            await self._handle_disconnection()
    
    async def _handle_disconnection(self):
        """Handle WebSocket disconnection and potential reconnection."""
        self.is_connected = False
        
        if self.on_disconnect:
            self.on_disconnect()
        
        if self.should_reconnect and self.reconnect_attempts < settings.MAX_RECONNECT_ATTEMPTS:
            self.reconnect_attempts += 1
            logger.info(f"Attempting to reconnect ({self.reconnect_attempts}/{settings.MAX_RECONNECT_ATTEMPTS})")
            
            await asyncio.sleep(settings.RECONNECT_DELAY)
            
            if self.should_reconnect:  # Check again in case disconnect was called during sleep
                await self.connect()
        else:
            logger.error("Max reconnection attempts reached or reconnection disabled")
    
    async def start(self):
        """Start the WebSocket client with auto-reconnect."""
        self.should_reconnect = True
        await self.connect()
    
    async def stop(self):
        """Stop the WebSocket client."""
        await self.disconnect()


class MessageHandler:
    """Handles different types of WebSocket messages."""
    
    def __init__(self, client_instance):
        self.client = client_instance
        self.logger = logging.getLogger(__name__)
    
    def handle_message(self, message: Dict[str, Any]):
        """Route message to appropriate handler based on type."""
        message_type = message.get('type')
        
        handlers = {
            'system_event': self._handle_system_event,
            'partial_transcript': self._handle_partial_transcript,
            'final_transcript': self._handle_final_transcript,
            'token': self._handle_llm_token,
            'tool': self._handle_tool_status,
            'user_interrupted': self._handle_user_interrupted,
            'audio_stream_start': self._handle_audio_stream_start,
            'audio_stream_end': self._handle_audio_stream_end,
            'audio_stream_error': self._handle_audio_stream_error,
            'barge_in_notification': self._handle_barge_in_notification,
        }
        
        handler = handlers.get(message_type)
        if handler:
            handler(message)
        else:
            self.logger.warning(f"Unknown message type: {message_type}")
    
    def _handle_system_event(self, message: Dict[str, Any]):
        """Handle system events like conversation_started."""
        event = message.get('event')
        conversation_id = message.get('conversation_id')
        
        if event == 'conversation_started':
            self.logger.info(f"System: Conversation started - {conversation_id}")
            self.client.on_conversation_started(conversation_id)
    
    def _handle_partial_transcript(self, message: Dict[str, Any]):
        """Handle partial transcript updates."""
        text = message.get('text', '')
        self.logger.info(f"Partial transcript: {text}")
        self.client.on_partial_transcript(text)
    
    def _handle_final_transcript(self, message: Dict[str, Any]):
        """Handle final transcript."""
        transcript = message.get('transcript', '')
        conversation_id = message.get('conversation_id')
        self.logger.info(f"Final transcript: {transcript}")
        self.client.on_final_transcript(transcript, conversation_id)
    
    def _handle_llm_token(self, message: Dict[str, Any]):
        """Handle streaming LLM tokens."""
        content = message.get('content', '')
        conversation_id = message.get('conversation_id')
        self.client.on_llm_token(content, conversation_id)
    
    def _handle_tool_status(self, message: Dict[str, Any]):
        """Handle tool execution status."""
        name = message.get('name', '')
        status = message.get('status', '')
        conversation_id = message.get('conversation_id')
        self.logger.info(f"Tool {name}: {status}")
        self.client.on_tool_status(name, status, conversation_id)
    
    def _handle_user_interrupted(self, message: Dict[str, Any]):
        """Handle user interruption signal."""
        conversation_id = message.get('conversation_id')
        self.logger.info(f"User interrupted: {conversation_id}")
        self.client.on_user_interrupted(conversation_id)
    
    def _handle_audio_stream_start(self, message: Dict[str, Any]):
        """Handle audio stream start."""
        conversation_id = message.get('conversation_id')
        sample_rate = message.get('sample_rate', 16000)
        channels = message.get('channels', 1)
        self.logger.info(f"Audio stream started: {sample_rate}Hz, {channels}ch")
        self.client.on_audio_stream_start(conversation_id, sample_rate, channels)
    
    def _handle_audio_stream_end(self, message: Dict[str, Any]):
        """Handle audio stream end."""
        conversation_id = message.get('conversation_id')
        self.logger.info(f"Audio stream ended: {conversation_id}")
        self.client.on_audio_stream_end(conversation_id)
    
    def _handle_audio_stream_error(self, message: Dict[str, Any]):
        """Handle audio stream error."""
        conversation_id = message.get('conversation_id')
        error = message.get('error', 'Unknown error')
        self.logger.error(f"Audio stream error: {error}")
        self.client.on_audio_stream_error(conversation_id, error)
    
    def _handle_barge_in_notification(self, message: Dict[str, Any]):
        """Handle barge-in notification."""
        conversation_id = message.get('conversation_id')
        timestamp_ms = message.get('timestamp_ms')
        self.logger.info(f"Barge-in detected: {conversation_id}")
        self.client.on_barge_in_notification(conversation_id, timestamp_ms) 