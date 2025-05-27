# SPT Assistant Python Client

A Python client that replicates the functionality of the React frontend for the SPT Assistant real-time AI voice interface. This client provides the same voice interaction capabilities through a command-line interface.

## 🎯 Overview

The SPT Assistant Python client enables natural voice conversations with AI through:

- **Real-time audio streaming** via WebSocket with binary data support
- **Voice Activity Detection (VAD)** and speech recognition
- **Text-to-Speech (TTS) playback** with sentence-by-sentence streaming
- **Barge-in support** for natural conversation interruption
- **Command-line interface** for easy interaction

## ✨ Features

### 🔊 **Audio Processing**
- **16kHz, 16-bit PCM audio** capture and playback
- **Real-time audio streaming** to SPT Assistant backend
- **Audio level monitoring** for both microphone input and TTS output
- **Multiple audio device support** with device selection

### 🌐 **WebSocket Communication**
- **Bi-directional communication** with SPT Assistant backend
- **Binary audio streaming** for low-latency voice transmission
- **JSON message handling** for transcripts, tokens, and control signals
- **Automatic reconnection** with exponential backoff

### 💬 **Chat Interface**
- **Real-time transcript display** with partial and final transcripts
- **Streaming LLM responses** with token-by-token updates
- **Tool execution status** monitoring
- **Chat history management**

### ⚡ **Barge-in Support**
- **Natural conversation flow** with interruption capability
- **Automatic TTS stopping** when user starts speaking
- **Seamless conversation resumption**

## 🛠️ Installation

### Prerequisites

- **Python 3.8+**
- **UV** (fast Python package manager)
- **PortAudio** (for PyAudio)
- **SPT Assistant backend** running on `localhost:8000`

### Install UV

If you don't have UV installed:

```bash
# On macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# On Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

# Or via pip
pip install uv
```

### Install PortAudio

#### macOS
```bash
brew install portaudio
```

#### Ubuntu/Debian
```bash
sudo apt-get install portaudio19-dev
```

#### Windows
```bash
# PortAudio is usually included with PyAudio on Windows
```

### Install Dependencies

```bash
cd client
uv sync
```

This will create a virtual environment and install all dependencies defined in `pyproject.toml`.

## 🚀 Quick Start

### 1. Start SPT Assistant Backend

Make sure the SPT Assistant backend is running:

```bash
# From the project root
./run.sh
```

### 2. Run the Python Client

```bash
cd client

# Run with UV
uv run spt-client

# Or activate the virtual environment and run directly
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
python -m spt_assistant_client.spt_client
```

### 3. Basic Usage

Once the client starts, you'll see:

```
🚀 SPT Assistant Python Client Started
Commands:
  's' - Start recording session
  'x' - Stop recording session
  'q' - Quit
  'status' - Show status
  'devices' - List audio devices
  'clear' - Clear chat

> 
```

**Start a conversation:**
1. Type `s` and press Enter to start recording
2. Speak naturally to the assistant
3. The assistant will respond with both text and voice
4. Type `x` to stop the session

## 📋 Commands

| Command | Description |
|---------|-------------|
| `s` or `start` | Start recording session |
| `x` or `stop` | Stop recording session |
| `q` or `quit` | Quit the application |
| `status` | Show current client status |
| `devices` | List available audio devices |
| `clear` | Clear chat history |
| `help` | Show available commands |

## ⚙️ Configuration

### Environment Variables

Create a `.env` file in the client directory:

```env
# WebSocket connection
SPT_CLIENT_WEBSOCKET_URL=ws://localhost:8000/api/v1/ws/audio

# Audio settings
SPT_CLIENT_SAMPLE_RATE=16000
SPT_CLIENT_CHANNELS=1
SPT_CLIENT_CHUNK_SIZE=4096

# Audio devices (optional - None = default device)
SPT_CLIENT_INPUT_DEVICE_INDEX=None
SPT_CLIENT_OUTPUT_DEVICE_INDEX=None

# Connection settings
SPT_CLIENT_MAX_RECONNECT_ATTEMPTS=5
SPT_CLIENT_RECONNECT_DELAY=5.0

# Logging
SPT_CLIENT_LOG_LEVEL=INFO
```

### Audio Device Selection

List available audio devices:

```bash
> devices

Available Audio Devices:
  0: Built-in Microphone (In: 2, Out: 0)
  1: Built-in Output (In: 0, Out: 2)
  2: USB Headset (In: 1, Out: 2)
```

Set specific devices in your `.env` file:

```env
SPT_CLIENT_INPUT_DEVICE_INDEX=2   # Use USB Headset for input
SPT_CLIENT_OUTPUT_DEVICE_INDEX=2  # Use USB Headset for output
```

## 🔧 Architecture

The Python client mirrors the React frontend's architecture:

```
┌─────────────────┐    WebSocket     ┌──────────────────┐
│   SPTClient     │◄────────────────►│  FastAPI Gateway │
│                 │   (JSON + Binary) │                  │
├─────────────────┤                   └──────────────────┘
│ AudioProcessor  │ ──── PCM Audio ──────────────────────►
├─────────────────┤                                       
│ WebSocketClient │ ◄──── TTS Audio ──────────────────────
├─────────────────┤                                       
│ MessageHandler  │ ◄──── Transcripts & Tokens ──────────
└─────────────────┘
```

### Core Components

#### 🎤 **AudioProcessor**
- Captures microphone input using PyAudio
- Converts audio to 16kHz, 16-bit PCM format
- Monitors audio levels for visual feedback
- Handles TTS audio playback with queuing

#### 🌐 **WebSocketClient**
- Manages persistent WebSocket connection with auto-reconnect
- Handles both JSON messages and binary audio data
- Provides connection status and error handling
- Supports graceful disconnection and cleanup

#### 📨 **MessageHandler**
- Routes different message types to appropriate handlers
- Handles transcripts, LLM tokens, tool status, and system events
- Manages conversation state and audio stream control

#### 🎯 **SPTClient**
- Main client class that orchestrates all components
- Manages conversation state and chat history
- Provides command-line interface
- Handles barge-in functionality

## 🎵 Audio Format

The client uses the same audio format as the frontend:

- **Sample Rate**: 16kHz
- **Bit Depth**: 16-bit signed integer
- **Channels**: Mono (1 channel)
- **Format**: PCM (Pulse Code Modulation)
- **Chunk Size**: 4096 samples (256ms at 16kHz)

## 🔄 Message Types

The client handles the same WebSocket message types as the frontend:

### Incoming Messages (Server → Client)

```python
# Transcription
{"type": "partial_transcript", "text": "Hello, how are"}
{"type": "final_transcript", "transcript": "Hello, how are you?", "conversation_id": "..."}

# LLM Response
{"type": "token", "content": "I'm doing great!", "conversation_id": "..."}
{"type": "tool", "name": "web_search", "status": "running"}

# Audio Streaming
{"type": "audio_stream_start", "sample_rate": 16000, "channels": 1}
# Binary audio chunks (ArrayBuffer equivalent)
{"type": "audio_stream_end", "conversation_id": "..."}

# System Events
{"type": "system_event", "event": "conversation_started", "conversation_id": "..."}
{"type": "barge_in_notification", "conversation_id": "..."}
```

### Outgoing Messages (Client → Server)

```python
# Binary audio data (PCM 16-bit, 16kHz)
# Raw bytes sent directly via WebSocket
```

## 🐛 Troubleshooting

### Common Issues

#### Audio Device Not Found
```
Error: Failed to start recording: Invalid device
```

**Solution**: List available devices and set the correct device index:
```bash
> devices
# Note the device index you want to use
# Set SPT_CLIENT_INPUT_DEVICE_INDEX in .env
```

#### WebSocket Connection Failed
```
❌ Connection error: Connection refused
```

**Solution**: Ensure SPT Assistant backend is running:
```bash
# Check if backend is running
curl http://localhost:8000/health

# Start backend if not running
./run.sh
```

#### Audio Playback Issues
```
Error in playback worker: [Errno -9981] Input overflowed
```

**Solution**: Try different audio devices or adjust chunk size:
```env
SPT_CLIENT_CHUNK_SIZE=2048  # Smaller chunks
```

#### Permission Denied (macOS)
```
Error: Failed to start recording: Permission denied
```

**Solution**: Grant microphone permissions:
1. System Preferences → Security & Privacy → Privacy → Microphone
2. Add Terminal or your Python executable to the allowed apps

#### UV Installation Issues

If UV sync fails:

```bash
# Update UV to latest version
uv self update

# Clear UV cache
uv cache clean

# Reinstall dependencies
uv sync --reinstall
```

### Debug Mode

Enable debug logging:

```env
SPT_CLIENT_LOG_LEVEL=DEBUG
```

This will show detailed WebSocket messages and audio processing information.

## 🔗 Integration

### Using as a Library

```python
from spt_assistant_client import SPTClient
import asyncio

async def my_app():
    client = SPTClient()
    
    # Custom message handlers
    def on_transcript(transcript, conversation_id):
        print(f"User said: {transcript}")
    
    def on_llm_response(content, conversation_id):
        print(f"Assistant: {content}")
    
    # Override default handlers
    client.on_final_transcript = on_transcript
    client.on_llm_token = on_llm_response
    
    await client.start()
    
    # Start recording programmatically
    client.start_recording()
    
    # Keep running
    await asyncio.sleep(60)
    
    await client.stop()

asyncio.run(my_app())
```

### Custom Audio Processing

```python
from spt_assistant_client import AudioProcessor

def my_audio_handler(audio_chunk):
    # Process audio chunk
    print(f"Received {len(audio_chunk)} bytes")

processor = AudioProcessor(my_audio_handler)
processor.start_recording()
```

## 🧪 Development

### Setting up Development Environment

```bash
cd client

# Install with development dependencies
uv sync --group dev

# Activate virtual environment
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### Code Quality Tools

```bash
# Format code
uv run black .
uv run isort .

# Lint code
uv run ruff check .

# Type checking
uv run mypy .

# Run tests
uv run pytest
```

### Building and Installing

```bash
# Build the package
uv build

# Install locally for development
uv pip install -e .
```

## 📊 Performance

### Latency Targets
- **Audio Capture to WebSocket**: < 50ms
- **WebSocket Message Processing**: < 10ms
- **TTS Audio Playback**: < 100ms
- **End-to-End Response**: < 1000ms

### Resource Usage
- **Memory**: ~50MB typical usage
- **CPU**: ~5-10% during active conversation
- **Network**: ~32kbps audio streaming

## 🤝 Contributing

1. **Fork the repository**
2. **Create feature branch** (`git checkout -b feature/amazing-feature`)
3. **Follow code style** - Use UV for dependency management
4. **Test thoroughly** - Ensure audio functionality works
5. **Submit pull request**

### Development Guidelines
- **UV for dependencies** - Use `uv add package` to add new dependencies
- **Type hints** - All functions must have proper type annotations
- **Error handling** - Comprehensive error handling and logging
- **Documentation** - Clear docstrings for all public methods
- **Testing** - Unit tests for core functionality
- **Code formatting** - Use Black, isort, and Ruff for code quality

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](../LICENSE) file for details.

## 🙏 Acknowledgments

- **PyAudio** for cross-platform audio I/O
- **websockets** for WebSocket client implementation
- **NumPy & SciPy** for audio processing
- **UV** for fast and reliable Python package management
- **SPT Assistant Team** for the amazing backend architecture

---

**Ready to experience voice AI from the command line?** 🚀 

Start the client with UV and begin your conversation with TARA!

```bash
cd client
uv run spt-client
``` 