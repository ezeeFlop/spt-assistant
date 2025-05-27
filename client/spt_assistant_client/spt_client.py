"""Main SPT Assistant Python client."""

import asyncio
import logging
import signal
import sys
import threading
import time
from typing import Dict, Any, Optional, List
from collections import deque

from .config import settings
from .audio_processor import AudioProcessor
from .websocket_client import WebSocketClient, MessageHandler


logger = logging.getLogger(__name__)


class ChatMessage:
    """Represents a chat message similar to the frontend."""
    
    def __init__(self, message_type: str, content: str, timestamp: Optional[float] = None):
        self.id = f"{int(time.time() * 1000)}_{id(self)}"
        self.type = message_type  # 'user', 'assistant', 'tool_status'
        self.content = content
        self.timestamp = timestamp or time.time()


class SPTClient:
    """Main SPT Assistant Python client that replicates frontend functionality."""
    
    def __init__(self):
        self.setup_logging()
        
        # State management (similar to frontend Zustand store)
        self.is_recording = False
        self.is_playing_audio = False
        self.active_conversation_id: Optional[str] = None
        self.chat_messages: List[ChatMessage] = []
        self.partial_transcript = ""
        self.current_assistant_message_id: Optional[str] = None
        self.current_assistant_content = ""
        
        # Audio levels
        self.mic_audio_level = 0.0
        self.playback_audio_level = 0.0
        
        # Components
        self.audio_processor: Optional[AudioProcessor] = None
        self.websocket_client: Optional[WebSocketClient] = None
        self.message_handler: Optional[MessageHandler] = None
        
        # Threading
        self.main_loop: Optional[asyncio.AbstractEventLoop] = None
        self.audio_level_thread: Optional[threading.Thread] = None
        self.should_stop = False
        
        logger.info("SPTClient initialized")
    
    def setup_logging(self):
        """Setup logging configuration."""
        logging.basicConfig(
            level=getattr(logging, settings.LOG_LEVEL),
            format=settings.LOG_FORMAT,
            handlers=[
                logging.StreamHandler(sys.stdout),
                logging.FileHandler('spt_client.log')
            ]
        )
    
    def list_audio_devices(self):
        """List available audio devices."""
        if not self.audio_processor:
            temp_processor = AudioProcessor(lambda x: None)
            devices = temp_processor.list_audio_devices()
            temp_processor.close()
            return devices
        return self.audio_processor.list_audio_devices()
    
    async def initialize(self):
        """Initialize the client components."""
        try:
            # Initialize audio processor
            self.audio_processor = AudioProcessor(self._on_audio_chunk, self._on_playback_finished)
            
            # Initialize WebSocket client
            self.websocket_client = WebSocketClient(
                on_message=self._on_websocket_message,
                on_audio_chunk=self._on_audio_chunk_received,
                on_connect=self._on_websocket_connect,
                on_disconnect=self._on_websocket_disconnect,
                on_error=self._on_websocket_error
            )
            
            # Initialize message handler
            self.message_handler = MessageHandler(self)
            
            # Start audio level monitoring thread
            self.audio_level_thread = threading.Thread(target=self._audio_level_monitor)
            self.audio_level_thread.daemon = True
            self.audio_level_thread.start()
            
            logger.info("SPTClient initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize SPTClient: {e}")
            raise
    
    async def start(self):
        """Start the client and connect to the server."""
        await self.initialize()
        await self.websocket_client.start()
    
    async def stop(self):
        """Stop the client and clean up resources."""
        self.should_stop = True
        
        if self.is_recording:
            self.stop_recording()
        
        if self.websocket_client:
            await self.websocket_client.stop()
        
        if self.audio_processor:
            self.audio_processor.close()
        
        logger.info("SPTClient stopped")
    
    def start_recording(self, device_index: Optional[int] = None) -> bool:
        """Start recording audio (equivalent to frontend's startStreaming)."""
        if self.is_recording:
            logger.warning("Recording already in progress")
            return False
        
        if not self.websocket_client or not self.websocket_client.is_connected:
            logger.error("Cannot start recording: WebSocket not connected")
            return False
        
        # Clear chat and reset state (like frontend's toggleRecording)
        self.clear_chat()
        self.stop_audio_playback()
        
        success = self.audio_processor.start_recording(device_index)
        if success:
            self.is_recording = True
            logger.info("Started recording session")
        
        return success
    
    def stop_recording(self):
        """Stop recording audio (equivalent to frontend's stopStreaming)."""
        if not self.is_recording:
            return
        
        self.is_recording = False
        self.audio_processor.stop_recording()
        logger.info("Stopped recording session")
    
    def stop_audio_playback(self):
        """Stop audio playback."""
        if self.audio_processor:
            self.audio_processor.stop_audio_playback()
        self.is_playing_audio = False
    
    def clear_chat(self):
        """Clear chat messages."""
        self.chat_messages.clear()
        self.partial_transcript = ""
        self.current_assistant_message_id = None
        self.current_assistant_content = ""
    
    def _on_audio_chunk(self, audio_data: bytes):
        """Callback for audio chunks from microphone.
        
        Audio flow:
        1. Microphone captures at 16kHz (matching frontend)
        2. Send raw 16kHz PCM to server via WebSocket
        3. Server processes and returns TTS audio (typically 24kHz)
        4. Client resamples TTS audio to supported playback rate
        """
        if self.websocket_client and self.websocket_client.is_connected:
            # Send audio chunk to server asynchronously
            asyncio.run_coroutine_threadsafe(
                self.websocket_client.send_audio_chunk(audio_data),
                self.main_loop
            )
    
    def _on_audio_chunk_received(self, audio_data: bytes):
        """Callback for audio chunks received from server (TTS)."""
        if self.audio_processor and self.is_playing_audio:
            self.audio_processor.enqueue_audio_chunk(audio_data)
    
    def _on_playback_finished(self):
        """Callback when audio playback has completely finished."""
        logger.info("Playback finished callback triggered")
        self.is_playing_audio = False
        self.clear_current_assistant_message()
        print("\n🎵 Assistant finished speaking")
    
    def _on_websocket_message(self, message: Dict[str, Any]):
        """Callback for WebSocket messages."""
        if self.message_handler:
            self.message_handler.handle_message(message)
    
    def _on_websocket_connect(self):
        """Callback for WebSocket connection."""
        logger.info("Connected to SPT Assistant server")
        print("🟢 Connected to SPT Assistant server")
    
    def _on_websocket_disconnect(self):
        """Callback for WebSocket disconnection."""
        logger.info("Disconnected from SPT Assistant server")
        print("🔴 Disconnected from SPT Assistant server")
        self.stop_recording()
        self.stop_audio_playback()
    
    def _on_websocket_error(self, error: Exception):
        """Callback for WebSocket errors."""
        logger.error(f"WebSocket error: {error}")
        print(f"❌ Connection error: {error}")
    
    def _audio_level_monitor(self):
        """Monitor audio levels in a separate thread."""
        while not self.should_stop:
            if self.audio_processor:
                mic_level, playback_level = self.audio_processor.get_audio_levels()
                self.mic_audio_level = mic_level
                self.playback_audio_level = playback_level
            time.sleep(0.1)  # Update 10 times per second
    
    # Message handler callbacks (called by MessageHandler)
    
    def on_conversation_started(self, conversation_id: str):
        """Handle conversation started event."""
        self.active_conversation_id = conversation_id
        self.clear_chat()
        self.stop_audio_playback()
        print(f"🎯 Conversation started: {conversation_id}")
    
    def on_partial_transcript(self, text: str):
        """Handle partial transcript updates."""
        self.partial_transcript = text
        print(f"🎤 Listening: {text}", end='\r')
    
    def on_final_transcript(self, transcript: str, conversation_id: Optional[str]):
        """Handle final transcript."""
        self.add_chat_message('user', transcript)
        self.partial_transcript = ""
        self.clear_current_assistant_message()
        print(f"\n👤 You: {transcript}")
    
    def on_llm_token(self, content: str, conversation_id: Optional[str]):
        """Handle streaming LLM tokens."""
        if not self.current_assistant_message_id:
            self.start_assistant_message()
        
        self.current_assistant_content += content
        print(content, end='', flush=True)
    
    def on_tool_status(self, name: str, status: str, conversation_id: Optional[str]):
        """Handle tool execution status."""
        self.add_chat_message('tool_status', f"{name}: {status}")
        print(f"\n🔧 Tool {name}: {status}")
    
    def on_user_interrupted(self, conversation_id: Optional[str]):
        """Handle user interruption."""
        if conversation_id == self.active_conversation_id:
            self.stop_audio_playback()
            self.clear_current_assistant_message()
            print("\n⚡ Interrupted")
    
    def on_audio_stream_start(self, conversation_id: Optional[str], sample_rate: int, channels: int):
        """Handle audio stream start."""
        if conversation_id == self.active_conversation_id:
            if not self.current_assistant_message_id:
                self.start_assistant_message()
            
            # Only start new playback if not already playing, or if audio format changed
            if not self.is_playing_audio:
                self.audio_processor.start_audio_playback(sample_rate, channels)
                self.is_playing_audio = True
                print(f"\n🔊 Assistant speaking...")
            else:
                # Already playing - just continue with existing stream
                # Reset the stream_ended flag since we're getting more audio
                if self.audio_processor:
                    self.audio_processor.stream_ended = False
                print(f"🔊 Continuing audio stream...")
    
    def on_audio_stream_end(self, conversation_id: Optional[str]):
        """Handle audio stream end - signal end but don't clear message yet."""
        if conversation_id == self.active_conversation_id:
            # Signal that this stream segment has ended
            if self.audio_processor:
                self.audio_processor.signal_stream_ended()
            print("✅ Audio stream segment ended")
    
    def on_audio_stream_error(self, conversation_id: Optional[str], error: str):
        """Handle audio stream error."""
        if conversation_id == self.active_conversation_id:
            self.stop_audio_playback()
            self.clear_current_assistant_message()
            print(f"\n❌ Audio error: {error}")
    
    def on_barge_in_notification(self, conversation_id: Optional[str], timestamp_ms: Optional[float]):
        """Handle barge-in notification."""
        if conversation_id == self.active_conversation_id:
            self.stop_audio_playback()
            self.clear_current_assistant_message()
            print("\n⚡ Barge-in detected - stopping playback")
    
    # Chat management methods
    
    def add_chat_message(self, message_type: str, content: str):
        """Add a message to the chat."""
        message = ChatMessage(message_type, content)
        self.chat_messages.append(message)
    
    def start_assistant_message(self, initial_content: str = ""):
        """Start a new assistant message."""
        self.current_assistant_message_id = f"assistant_{int(time.time() * 1000)}"
        self.current_assistant_content = initial_content
        print(f"\n🤖 Assistant: ", end='')
    
    def clear_current_assistant_message(self):
        """Clear the current assistant message."""
        if self.current_assistant_message_id and self.current_assistant_content:
            self.add_chat_message('assistant', self.current_assistant_content)
        
        self.current_assistant_message_id = None
        self.current_assistant_content = ""
    
    def get_chat_history(self) -> List[Dict[str, Any]]:
        """Get chat history as a list of dictionaries."""
        return [
            {
                'id': msg.id,
                'type': msg.type,
                'content': msg.content,
                'timestamp': msg.timestamp
            }
            for msg in self.chat_messages
        ]
    
    def print_status(self):
        """Print current client status."""
        status_lines = [
            f"🎯 Conversation: {self.active_conversation_id or 'None'}",
            f"🎤 Recording: {'Yes' if self.is_recording else 'No'}",
            f"🔊 Playing: {'Yes' if self.is_playing_audio else 'No'}",
            f"📡 Connected: {'Yes' if self.websocket_client and self.websocket_client.is_connected else 'No'}",
            f"🔄 Echo Cancellation: System-level (like browser getUserMedia)",
            f"📊 Mic Level: {self.mic_audio_level:.2f}",
            f"📊 Playback Level: {self.playback_audio_level:.2f}",
            f"💬 Messages: {len(self.chat_messages)}"
        ]
        
        print("\n" + "="*50)
        print("SPT Assistant Client Status")
        print("="*50)
        for line in status_lines:
            print(line)
        print("="*50 + "\n")


def main():
    """Main function to run the SPT client."""
    
    async def run_client():
        client = SPTClient()
        
        # Setup signal handlers for graceful shutdown
        def signal_handler(signum, frame):
            print("\n🛑 Shutting down...")
            asyncio.create_task(client.stop())
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        try:
            # Store the event loop for audio callback
            client.main_loop = asyncio.get_event_loop()
            
            # Start the client
            await client.start()
            
            print("🚀 SPT Assistant Python Client Started")
            print("Commands:")
            print("  's' - Start recording session")
            print("  'x' - Stop recording session")
            print("  'q' - Quit")
            print("  'status' - Show status")
            print("  'devices' - List audio devices")
            print("  'clear' - Clear chat")
            print("  'volume <0.0-2.0>' - Set output volume")
            print("  'test' - Test audio output")
            print("Note: Echo cancellation is handled by the system (like browser getUserMedia)")
            
            # Interactive command loop
            while True:
                try:
                    command = await asyncio.get_event_loop().run_in_executor(
                        None, input, "\n> "
                    )
                    
                    command = command.strip().lower()
                    
                    if command == 'q' or command == 'quit':
                        break
                    elif command == 's' or command == 'start':
                        client.start_recording()
                    elif command == 'x' or command == 'stop':
                        client.stop_recording()
                    elif command == 'status':
                        client.print_status()
                    elif command == 'devices':
                        devices = client.list_audio_devices()
                        print("\nAvailable Audio Devices:")
                        for device in devices:
                            default_markers = []
                            if device.get('is_default_input'):
                                default_markers.append("DEFAULT INPUT")
                            if device.get('is_default_output'):
                                default_markers.append("DEFAULT OUTPUT")
                            default_str = f" [{', '.join(default_markers)}]" if default_markers else ""
                            
                            print(f"  {device['index']}: {device['name']}{default_str}")
                            print(f"      In: {device['max_input_channels']}, Out: {device['max_output_channels']}")
                    elif command == 'clear':
                        client.clear_chat()
                        print("Chat cleared")
                    elif command.startswith('volume '):
                        try:
                            volume_str = command.split(' ', 1)[1]
                            volume = float(volume_str)
                            if client.audio_processor:
                                client.audio_processor.set_output_volume(volume)
                                print(f"Volume set to {volume:.2f}")
                            else:
                                print("Audio processor not initialized")
                        except (ValueError, IndexError):
                            print("Usage: volume <0.0-2.0> (e.g., volume 1.5)")
                    elif command == 'test':
                        if client.audio_processor:
                            print("Playing test tone...")
                            client.audio_processor.test_audio_output()
                        else:
                            print("Audio processor not initialized")
                    elif command == 'help':
                        print("Commands: s(tart), x(stop), q(uit), status, devices, clear, volume, test")
                    else:
                        print("Unknown command. Type 'help' for available commands.")
                        
                except EOFError:
                    break
                except Exception as e:
                    logger.error(f"Error in command loop: {e}")
        
        except Exception as e:
            logger.error(f"Error running client: {e}")
        finally:
            await client.stop()
    
    # Run the async client
    asyncio.run(run_client())


if __name__ == "__main__":
    main() 