# SPT Assistant - Technical Documentation

## Table of Contents

1. [System Architecture Overview](#system-architecture-overview)
2. [WebSocket Interface Specification](#websocket-interface-specification)
3. [Audio Processing Pipeline](#audio-processing-pipeline)
4. [Distributed Redis Architecture](#distributed-redis-architecture)
5. [Barge-In Feature Implementation](#barge-in-feature-implementation)
6. [Real-Time Communication Flow](#real-time-communication-flow)
7. [Error Handling & Recovery](#error-handling--recovery)
8. [Performance Optimizations](#performance-optimizations)
9. [Development & Debugging](#development--debugging)

---

## System Architecture Overview

SPT Assistant is a distributed, real-time AI voice assistant built on a microservices architecture with Redis as the message broker. The system enables natural voice conversations with AI through advanced audio processing, real-time streaming, and intelligent barge-in capabilities.

### Core Components

```
┌─────────────────┐    WebSocket     ┌──────────────────┐    Redis PubSub    ┌─────────────────┐
│   React App     │◄────────────────►│  FastAPI Gateway │◄──────────────────►│  VAD/STT Worker │
│   (Frontend)    │   Binary + JSON  │   (API Gateway)  │                    │                 │
└─────────────────┘                  └──────────────────┘                    └─────────────────┘
         │                                      │                                      │
         │ Audio Streaming                      │ Redis Channels                       │ Audio Processing
         │ Chat Interface                       │ • audio_stream_channel               │ • Voice Activity Detection
         │ Real-time Updates                    │ • transcript_channel                 │ • Speech Recognition
         │                                      │ • llm_token_channel                  │ • Barge-in Detection
         │                                      │ • llm_tool_call_channel             │
         │                                      │ • audio_output_stream_*             │
         │                                      │ • barge_in_notifications            │
         │                                      │                                      │
         │                          ┌──────────▼──────────┐              ┌─────────────▼─────────────┐
         │                          │ LLM Orchestrator    │              │ TTS Worker              │
         │                          │ Worker              │              │                         │
         │                          │                     │              │                         │
         │                          │ • Conversation Mgmt │              │ • Text-to-Speech        │
         │                          │ • LLM Integration   │              │ • Audio Streaming       │
         │                          │ • Tool Execution    │              │ • Voice Synthesis       │
         │                          │ • Context Management│              │ • Audio Chunking        │
         │                          └─────────────────────┘              └─────────────────────────┘
         │
         └────► Local/Remote AI Models ◄──── Configurable Backends
                • OpenAI GPT-4/Claude          • Local Ollama
                • Azure OpenAI                 • Local Whisper
                • Anthropic Claude             • Local Piper TTS
```

### Architectural Principles

- **Microservices**: Independent, scalable workers for specialized tasks
- **Event-Driven**: Redis pub/sub for loose coupling and scalability
- **Real-Time**: WebSocket for low-latency bidirectional communication
- **Fault-Tolerant**: Graceful degradation and automatic recovery
- **Local-First**: Support for local AI models and offline operation

---

## WebSocket Interface Specification

The WebSocket endpoint (`/api/v1/ws/audio`) serves as the primary interface between the frontend and backend, handling both binary audio streams and JSON control messages.

### Connection Lifecycle

```typescript
// Connection establishment
const ws = new WebSocket('ws://localhost:8000/api/v1/ws/audio');

// Connection events
ws.onopen = () => {
    // Receive conversation_id and system status
};

ws.onmessage = (event) => {
    if (event.data instanceof ArrayBuffer) {
        // Binary audio data (TTS output)
        handleAudioChunk(event.data);
    } else {
        // JSON messages (transcripts, tokens, control)
        const message = JSON.parse(event.data);
        handleJSONMessage(message);
    }
};
```

### Message Types

#### 1. System Events (Server → Client)

```typescript
// Conversation initialization
{
    "type": "system_event",
    "event": "conversation_started",
    "conversation_id": "550e8400-e29b-41d4-a716-446655440000"
}

// Barge-in notification
{
    "type": "barge_in_notification",
    "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
    "timestamp_ms": 1640995200000
}
```

#### 2. Speech Recognition (Server → Client)

```typescript
// Partial transcript (real-time)
{
    "type": "partial_transcript",
    "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
    "transcript": "Hello, how are",
    "timestamp_ms": 1640995200000,
    "is_final": false
}

// Final transcript
{
    "type": "final_transcript",
    "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
    "transcript": "Hello, how are you today?",
    "timestamp_ms": 1640995200100,
    "is_final": true
}
```

#### 3. LLM Response Streaming (Server → Client)

```typescript
// Streaming token
{
    "type": "token",
    "role": "assistant",
    "content": "I'm doing",
    "conversation_id": "550e8400-e29b-41d4-a716-446655440000"
}

// Tool execution status
{
    "type": "tool",
    "name": "web_search",
    "status": "running", // "running" | "completed" | "failed"
    "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
    "tool_id": "call_abc123",
    "result": { /* tool output */ }
}
```

#### 4. Audio Streaming (Server → Client)

```typescript
// Audio stream initialization
{
    "type": "audio_stream_start",
    "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
    "sample_rate": 16000,
    "channels": 1,
    "format": "pcm_s16le"
}

// Binary audio chunk (ArrayBuffer)
// Raw PCM data, 16-bit signed little-endian, 16kHz, mono

// Audio stream termination
{
    "type": "audio_stream_end",
    "conversation_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

#### 5. Client Audio Input (Client → Server)

```typescript
// Binary audio data only
// Raw PCM, 16-bit signed little-endian, 16kHz, mono
// Sent as ArrayBuffer via WebSocket.send(audioBuffer)
```

### WebSocket Implementation Details

#### Server-Side Handler

```python
@router.websocket("/ws/audio")
async def websocket_audio_endpoint(websocket: WebSocket):
    await websocket.accept()
    conversation_id = str(uuid.uuid4())
    
    # Send initial conversation event
    await websocket.send_json({
        "type": "system_event",
        "event": "conversation_started", 
        "conversation_id": conversation_id
    })
    
    # Spawn concurrent tasks for bidirectional communication
    tasks = [
        receive_audio_from_client(websocket, conversation_id),
        forward_transcripts_to_client(websocket, conversation_id),
        forward_llm_tokens_to_client(websocket, conversation_id),
        forward_tool_calls_to_client(websocket, conversation_id),
        forward_tts_audio_to_client(websocket, conversation_id),
        forward_barge_in_notifications_to_client(websocket, conversation_id)
    ]
    
    # Wait for any task to complete (usually disconnection)
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    
    # Cancel remaining tasks
    for task in pending:
        task.cancel()
```

#### Audio Reception Handler

```python
async def receive_audio_from_client(websocket: WebSocket, conversation_id: str):
    """Receives binary audio data and publishes to Redis"""
    while True:
        # Receive raw PCM audio bytes
        audio_data = await websocket.receive_bytes()
        
        # Package with conversation ID for workers
        audio_message = {
            "conversation_id": conversation_id,
            "audio_data": audio_data.hex()  # Convert bytes to hex string
        }
        
        # Publish to Redis for VAD/STT worker
        await redis_client.publish(
            settings.AUDIO_STREAM_CHANNEL, 
            json.dumps(audio_message)
        )
```

---

## Audio Processing Pipeline

The audio processing pipeline transforms raw microphone input into text transcriptions and synthesizes AI responses back into audio output.

### Frontend Audio Capture

#### 1. Web Audio API Setup

```typescript
// Initialize audio context and capture
const audioContext = new AudioContext({ sampleRate: 48000 });
const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
        sampleRate: 48000,
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true
    }
});

const source = audioContext.createMediaStreamSource(stream);
```

#### 2. AudioWorklet Processing

The `pcm-processor.ts` AudioWorklet handles real-time audio format conversion:

```typescript
class PCMProcessor extends AudioWorkletProcessor {
    private targetSampleRate = 16000;
    private internalBuffer: Float32Array;
    
    process(inputs: Float32Array[][]): boolean {
        const inputChannelData = inputs[0]?.[0];
        
        // Accumulate audio in internal buffer
        this.appendToBuffer(inputChannelData);
        
        // Process in 4096-sample chunks (256ms at 16kHz)
        while (this.hasEnoughSamples()) {
            const chunk = this.extractChunk();
            const resampled = this.downsample(chunk, 48000, 16000);
            const pcm16 = this.convertToPCM16(resampled);
            
            // Send to main thread
            this.port.postMessage(pcm16.buffer, [pcm16.buffer]);
        }
        
        return true; // Keep processor alive
    }
    
    downsample(buffer: Float32Array, inputSR: number, outputSR: number): Float32Array {
        const ratio = inputSR / outputSR;
        const outputLength = Math.floor(buffer.length / ratio);
        const result = new Float32Array(outputLength);
        
        // Linear interpolation downsampling
        for (let i = 0; i < outputLength; i++) {
            const position = i * ratio;
            const floor = Math.floor(position);
            const ceil = Math.ceil(position);
            
            if (ceil < buffer.length) {
                const fraction = position - floor;
                result[i] = buffer[floor] * (1 - fraction) + buffer[ceil] * fraction;
            } else {
                result[i] = buffer[floor];
            }
        }
        
        return result;
    }
    
    convertToPCM16(buffer: Float32Array): Int16Array {
        const pcm16 = new Int16Array(buffer.length);
        for (let i = 0; i < buffer.length; i++) {
            const sample = Math.max(-1, Math.min(1, buffer[i])); // Clamp to [-1, 1]
            pcm16[i] = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
        }
        return pcm16;
    }
}
```

#### 3. WebSocket Streaming

```typescript
// Send audio chunks to server
audioWorklet.port.onmessage = (event) => {
    const audioBuffer = event.data;
    if (websocket.readyState === WebSocket.OPEN) {
        websocket.send(audioBuffer); // Send as binary data
    }
};
```

### Backend Audio Processing

#### 1. VAD/STT Worker Processing

```python
class AudioProcessor:
    def __init__(self):
        self.vad_model = webrtcvad.Vad(2)  # Aggressiveness level 2
        self.stt_engine = whisper.load_model("base")
        self.audio_buffer = bytearray()
        self.sample_rate = 16000
        
    def process_audio_chunk(self, audio_bytes: bytes) -> List[Dict]:
        """Process incoming audio chunk and return events"""
        events = []
        
        # Append to buffer
        self.audio_buffer.extend(audio_bytes)
        
        # VAD processing (30ms frames)
        frame_size = int(self.sample_rate * 0.03)  # 30ms frames
        
        while len(self.audio_buffer) >= frame_size * 2:  # 2 bytes per sample
            frame = self.audio_buffer[:frame_size * 2]
            del self.audio_buffer[:frame_size * 2]
            
            # Voice activity detection
            is_speech = self.vad_model.is_speech(frame, self.sample_rate)
            
            if is_speech:
                self.speech_buffer.extend(frame)
                
                # Check for barge-in condition
                if self.should_trigger_barge_in():
                    events.append({
                        "event_type": "vad_event",
                        "status": "barge_in_start",
                        "timestamp_ms": time.time() * 1000
                    })
                
                # Accumulate speech for transcription
                if len(self.speech_buffer) >= self.transcription_threshold:
                    transcript = self.transcribe_speech()
                    events.append({
                        "event_type": "transcript",
                        "transcript": transcript,
                        "is_final": self.is_complete_utterance(),
                        "timestamp_ms": time.time() * 1000
                    })
        
        return events
```

#### 2. Speech Recognition

```python
def transcribe_speech(self) -> str:
    """Convert speech buffer to text using Whisper"""
    # Convert bytes to numpy array
    audio_np = np.frombuffer(self.speech_buffer, dtype=np.int16).astype(np.float32) / 32768.0
    
    # Run Whisper transcription
    result = self.stt_engine.transcribe(
        audio_np,
        language="en",
        task="transcribe",
        fp16=False
    )
    
    return result["text"].strip()
```

### TTS Audio Generation

#### 1. Text-to-Speech Processing

```python
class TTSProcessor:
    def __init__(self):
        self.tts_engine = TTS("tts_models/en/ljspeech/tacotron2-DDC")
        self.sample_rate = 16000
        
    async def synthesize_speech(self, text: str, conversation_id: str):
        """Convert text to speech and stream audio chunks"""
        # Generate audio
        audio_data = self.tts_engine.tts(text)
        
        # Convert to 16kHz, 16-bit PCM
        audio_16k = librosa.resample(audio_data, 22050, 16000)
        audio_pcm = (audio_16k * 32767).astype(np.int16)
        
        # Send stream start message
        start_message = {
            "type": "audio_stream_start",
            "conversation_id": conversation_id,
            "sample_rate": 16000,
            "channels": 1,
            "format": "pcm_s16le"
        }
        await self.publish_control_message(start_message)
        
        # Stream audio in chunks
        chunk_size = 4096  # 256ms chunks at 16kHz
        for i in range(0, len(audio_pcm), chunk_size):
            chunk = audio_pcm[i:i + chunk_size]
            await self.stream_audio_chunk(chunk.tobytes(), conversation_id)
            
        # Send stream end message  
        end_message = {
            "type": "audio_stream_end",
            "conversation_id": conversation_id
        }
        await self.publish_control_message(end_message)
```

#### 2. Audio Chunk Streaming

```python
async def stream_audio_chunk(self, audio_bytes: bytes, conversation_id: str):
    """Stream audio chunk to Redis for frontend delivery"""
    channel = f"audio_output_stream:{conversation_id}"
    await redis_client.publish(channel, audio_bytes)
```

### Frontend Audio Playback

#### 1. Audio Buffer Management

```typescript
class StreamedAudioPlayer {
    private audioContext: AudioContext;
    private audioQueue: AudioBuffer[] = [];
    private isPlaying = false;
    
    async handleAudioChunk(audioData: ArrayBuffer) {
        // Convert PCM to AudioBuffer
        const audioBuffer = await this.pcmToAudioBuffer(audioData);
        this.audioQueue.push(audioBuffer);
        
        if (!this.isPlaying) {
            this.playNextChunk();
        }
    }
    
    private async pcmToAudioBuffer(pcmData: ArrayBuffer): Promise<AudioBuffer> {
        const samples = new Int16Array(pcmData);
        const audioBuffer = this.audioContext.createBuffer(1, samples.length, 16000);
        const channelData = audioBuffer.getChannelData(0);
        
        // Convert 16-bit PCM to float
        for (let i = 0; i < samples.length; i++) {
            channelData[i] = samples[i] / 32768;
        }
        
        return audioBuffer;
    }
    
    private async playNextChunk() {
        if (this.audioQueue.length === 0) {
            this.isPlaying = false;
            return;
        }
        
        this.isPlaying = true;
        const audioBuffer = this.audioQueue.shift()!;
        
        const source = this.audioContext.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(this.audioContext.destination);
        
        source.onended = () => {
            this.playNextChunk(); // Play next chunk when current ends
        };
        
        source.start();
    }
}
```

---

## Distributed Redis Architecture

Redis serves as the central message broker, enabling loose coupling between microservices and horizontal scaling.

### Redis Channel Architecture

```
┌─────────────────────┐
│   Redis Pub/Sub     │
├─────────────────────┤
│ audio_stream_channel│ ◄─── Audio chunks from frontend
│ transcript_channel  │ ◄─── STT results to frontend  
│ llm_token_channel   │ ◄─── LLM streaming tokens
│ llm_tool_call_channel │ ◄─── Tool execution status
│ audio_output_stream:* │ ◄─── TTS audio to frontend
│ barge_in_notifications│ ◄─── Interruption signals
├─────────────────────┤
│ Conversation Data   │
├─────────────────────┤
│ conversation_config:*│ ◄─── Per-conversation settings
│ conversation_history:*│ ◄─── Message history (TTL)
│ tts_active:*        │ ◄─── TTS playback state
└─────────────────────┘
```

### Channel Message Specifications

#### 1. Audio Stream Channel
```json
{
    "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
    "audio_data": "deadbeef01234567..." // Hex-encoded PCM bytes
}
```

#### 2. Transcript Channel
```json
{
    "type": "final_transcript",
    "conversation_id": "550e8400-e29b-41d4-a716-446655440000", 
    "transcript": "Hello, how are you today?",
    "timestamp_ms": 1640995200000,
    "is_final": true
}
```

#### 3. LLM Token Channel
```json
{
    "type": "token",
    "role": "assistant",
    "content": "I'm doing great, thank you for asking!",
    "conversation_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

#### 4. Audio Output Stream (Per Conversation)
```
Channel: audio_output_stream:550e8400-e29b-41d4-a716-446655440000
Data: Raw binary PCM audio bytes or JSON control messages
```

### Redis Data Structures

#### 1. Conversation Configuration
```redis
Key: conversation_config:550e8400-e29b-41d4-a716-446655440000
Value: {
    "llm_model_name": "gpt-4",
    "llm_temperature": 0.7,
    "llm_max_tokens": 2048,
    "tts_voice_id": "nova",
    "user_preferences": {
        "language": "en",
        "response_style": "conversational"
    }
}
TTL: 3600 seconds
```

#### 2. Conversation History
```redis
Key: conversation_history:550e8400-e29b-41d4-a716-446655440000
Value: [
    {"role": "system", "content": "You are TARA, a helpful assistant..."},
    {"role": "user", "content": "Hello, how are you?"},
    {"role": "assistant", "content": "I'm doing great, thank you for asking!"}
]
TTL: 3600 seconds
```

#### 3. TTS Active State
```redis
Key: tts_active:550e8400-e29b-41d4-a716-446655440000
Value: "1"
TTL: 30 seconds (auto-expires if not refreshed)
```

### Worker Communication Patterns

#### 1. Audio Processing Flow
```python
# VAD/STT Worker subscribes to audio stream
async def process_audio_stream():
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("audio_stream_channel")
    
    async for message in pubsub.listen():
        if message["type"] == "message":
            payload = json.loads(message["data"])
            conversation_id = payload["conversation_id"]
            audio_data = bytes.fromhex(payload["audio_data"])
            
            # Process audio and publish transcript
            transcript = await process_audio_chunk(audio_data)
            await publish_transcript(conversation_id, transcript)
```

#### 2. LLM Orchestration Flow
```python
# LLM Orchestrator subscribes to transcripts
async def process_transcripts():
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("transcript_channel")
    
    async for message in pubsub.listen():
        if message["type"] == "message":
            transcript_data = json.loads(message["data"])
            
            if transcript_data["type"] == "final_transcript":
                conversation_id = transcript_data["conversation_id"]
                user_text = transcript_data["transcript"]
                
                # Generate LLM response and stream tokens
                async for token in llm_service.generate_response(user_text):
                    await publish_token(conversation_id, token)
```

#### 3. TTS Generation Flow
```python
# TTS Worker subscribes to TTS requests
async def process_tts_requests():
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("tts_request_channel")
    
    async for message in pubsub.listen():
        if message["type"] == "message":
            tts_request = json.loads(message["data"])
            conversation_id = tts_request["conversation_id"]
            text = tts_request["text_to_speak"]
            
            # Mark TTS as active
            await redis_client.set(f"tts_active:{conversation_id}", "1", ex=30)
            
            # Generate and stream audio
            async for audio_chunk in generate_speech(text):
                await stream_audio_chunk(conversation_id, audio_chunk)
                
            # Clear TTS active state
            await redis_client.delete(f"tts_active:{conversation_id}")
```

---

## Barge-In Feature Implementation

The barge-in feature allows users to naturally interrupt the AI assistant during speech playback, creating a more conversational experience.

### Barge-In Detection Logic

#### 1. Voice Activity Detection
```python
class BargeInDetector:
    def __init__(self):
        self.vad_model = webrtcvad.Vad(2)  # Medium aggressiveness
        self.speech_threshold = 0.3  # 300ms of speech to trigger
        self.speech_buffer_ms = 0
        
    def process_frame(self, audio_frame: bytes, frame_duration_ms: float) -> bool:
        """Returns True if barge-in should be triggered"""
        is_speech = self.vad_model.is_speech(audio_frame, 16000)
        
        if is_speech:
            self.speech_buffer_ms += frame_duration_ms
            if self.speech_buffer_ms >= self.speech_threshold * 1000:
                return True
        else:
            # Reset on silence
            self.speech_buffer_ms = 0
            
        return False
```

#### 2. TTS State Tracking
```python
async def check_tts_active(conversation_id: str) -> bool:
    """Check if TTS is currently playing for this conversation"""
    tts_key = f"tts_active:{conversation_id}"
    return await redis_client.exists(tts_key) > 0

async def set_tts_active(conversation_id: str, active: bool):
    """Set TTS active state with auto-expiry"""
    tts_key = f"tts_active:{conversation_id}"
    if active:
        await redis_client.set(tts_key, "1", ex=30)  # 30s TTL
    else:
        await redis_client.delete(tts_key)
```

#### 3. Barge-In Event Processing
```python
async def handle_barge_in_detection(conversation_id: str):
    """Handle detected barge-in event"""
    # Check if TTS is currently active
    tts_is_active = await check_tts_active(conversation_id)
    
    if tts_is_active:
        logger.info(f"Barge-in detected during TTS for {conversation_id}")
        
        # Publish barge-in notification
        barge_in_event = {
            "type": "barge_in_detected",
            "conversation_id": conversation_id,
            "timestamp_ms": time.time() * 1000
        }
        
        await redis_client.publish(
            "barge_in_notifications", 
            json.dumps(barge_in_event)
        )
        
        return True
    
    return False
```

### Barge-In Response Chain

#### 1. LLM Cancellation
```python
class LLMService:
    def __init__(self):
        self._cancellation_events: Dict[str, asyncio.Event] = {}
    
    def cancel_generation(self, conversation_id: str):
        """Cancel ongoing LLM generation for conversation"""
        if conversation_id in self._cancellation_events:
            self._cancellation_events[conversation_id].set()
            logger.info(f"Cancelled LLM generation for {conversation_id}")
    
    async def generate_response_stream(self, conversation_id: str, messages: List[Dict]):
        """Generate streaming LLM response with cancellation support"""
        # Create cancellation event
        cancellation_event = asyncio.Event()
        self._cancellation_events[conversation_id] = cancellation_event
        
        try:
            async for chunk in self.llm_client.stream(messages):
                # Check for cancellation
                if cancellation_event.is_set():
                    logger.info(f"LLM stream cancelled for {conversation_id}")
                    break
                    
                yield chunk
        finally:
            # Cleanup cancellation event
            if conversation_id in self._cancellation_events:
                del self._cancellation_events[conversation_id]
```

#### 2. TTS Interruption
```python
async def handle_tts_stop_command(conversation_id: str):
    """Stop TTS playback and clear audio queue"""
    # Clear TTS active state
    await redis_client.delete(f"tts_active:{conversation_id}")
    
    # Send stop command to audio output stream
    stop_message = {
        "type": "audio_stream_end",
        "conversation_id": conversation_id,
        "reason": "interrupted"
    }
    
    audio_channel = f"audio_output_stream:{conversation_id}"
    await redis_client.publish(audio_channel, json.dumps(stop_message))
```

#### 3. Frontend Audio Interruption
```typescript
class StreamedAudioPlayer {
    private currentSource: AudioBufferSourceNode | null = null;
    private audioQueue: AudioBuffer[] = [];
    
    handleBargeIn() {
        // Stop current playback immediately
        if (this.currentSource) {
            this.currentSource.stop();
            this.currentSource = null;
        }
        
        // Clear pending audio queue
        this.audioQueue = [];
        
        // Reset playback state
        this.isPlaying = false;
        
        logger.info("Audio playback interrupted by barge-in");
    }
    
    handleWebSocketMessage(message: any) {
        if (message.type === "barge_in_notification") {
            this.handleBargeIn();
        } else if (message.type === "audio_stream_end" && message.reason === "interrupted") {
            this.handleBargeIn();
        }
    }
}
```

### Barge-In State Machine

```
┌─────────────────┐     User Speaks     ┌─────────────────┐
│   TTS Playing   │────────────────────►│  Barge-In       │
│                 │   (VAD detects)      │  Detected       │
└─────────────────┘                     └─────────────────┘
         │                                        │
         │ Audio chunks                           │ Cancellation
         │ streaming                              │ events
         ▼                                        ▼
┌─────────────────┐                     ┌─────────────────┐
│   Frontend      │                     │   LLM + TTS     │
│   Playing       │                     │   Cancelled     │
└─────────────────┘                     └─────────────────┘
         │                                        │
         │ Audio stopped                          │
         │ Queue cleared                          │
         ▼                                        ▼
┌─────────────────┐     New transcript   ┌─────────────────┐
│   Ready for     │◄────────────────────│   Processing    │
│   New Input     │                     │   User Speech   │
└─────────────────┘                     └─────────────────┘
```

---

## Real-Time Communication Flow

Understanding the complete message flow helps optimize performance and debug issues.

### Complete Conversation Flow

#### 1. Connection Establishment
```
1. Frontend → WebSocket connect to /api/v1/ws/audio
2. Server → Accept connection, generate conversation_id
3. Server → Send {"type": "system_event", "event": "conversation_started"}
4. Server → Spawn 6 concurrent tasks for bidirectional communication
```

#### 2. User Speech Processing
```
Frontend Audio Capture:
1. Microphone → Web Audio API → AudioWorklet
2. AudioWorklet → PCM conversion (48kHz → 16kHz)
3. WebSocket → Binary audio chunks (4096 samples each)

Backend Processing:
4. Gateway → Redis publish to "audio_stream_channel"
5. VAD/STT Worker → Subscribe and process audio
6. VAD/STT Worker → Voice activity detection per 30ms frame
7. VAD/STT Worker → Accumulate speech buffer
8. VAD/STT Worker → Whisper transcription on complete utterances
9. VAD/STT Worker → Redis publish to "transcript_channel"

Frontend Display:
10. Gateway → Subscribe to transcript channel, forward to WebSocket
11. Frontend → Receive partial/final transcripts
12. Frontend → Update chat display with real-time transcription
```

#### 3. LLM Response Generation
```
Backend Processing:
1. LLM Orchestrator → Subscribe to "transcript_channel"
2. LLM Orchestrator → Load conversation history from Redis
3. LLM Orchestrator → Send request to LLM (OpenAI/Claude/Ollama)
4. LLM Orchestrator → Stream tokens to "llm_token_channel"
5. LLM Orchestrator → Check for tool calls in response
6. LLM Orchestrator → Execute tools if needed
7. LLM Orchestrator → Send completed sentences to "tts_request_channel"

Frontend Display:
8. Gateway → Forward LLM tokens to WebSocket
9. Frontend → Update chat with streaming text
10. Frontend → Display tool execution status
```

#### 4. TTS Audio Synthesis
```
Backend Processing:
1. TTS Worker → Subscribe to "tts_request_channel"
2. TTS Worker → Set "tts_active:{conversation_id}" in Redis
3. TTS Worker → Generate speech audio (Piper/ElevenLabs/OpenAI)
4. TTS Worker → Convert audio to 16kHz PCM
5. TTS Worker → Send "audio_stream_start" control message
6. TTS Worker → Stream 4096-byte audio chunks
7. TTS Worker → Send "audio_stream_end" control message
8. TTS Worker → Clear "tts_active" state

Frontend Playback:
9. Gateway → Forward audio chunks to WebSocket
10. Frontend → Convert PCM to AudioBuffer
11. Frontend → Queue and play audio sentence-by-sentence
12. Frontend → Monitor audio levels for visualization
```

#### 5. Barge-In Handling
```
Interruption Detection:
1. User starts speaking while TTS is playing
2. VAD/STT Worker → Detects speech during TTS active state
3. VAD/STT Worker → Publish to "barge_in_notifications"

Cancellation Chain:
4. LLM Orchestrator → Subscribe to barge-in, cancel generation
5. LLM Orchestrator → Send TTS stop command
6. TTS Worker → Stop audio generation, clear active state
7. Gateway → Forward barge-in notification to frontend
8. Frontend → Stop audio playback, clear queue

Recovery:
9. VAD/STT Worker → Continue processing user speech
10. System → Resume normal conversation flow
```

### Performance Metrics

#### Latency Targets
- **Audio Capture to STT**: < 100ms
- **STT to LLM Response Start**: < 200ms  
- **LLM First Token**: < 500ms
- **TTS Generation Start**: < 300ms
- **End-to-End Response**: < 1000ms
- **Barge-In Response**: < 150ms

#### Throughput Specifications
- **Audio Streaming**: 32kbps (16kHz, 16-bit PCM)
- **WebSocket Messages**: 1000+ msgs/sec per connection
- **Redis Pub/Sub**: 10,000+ msgs/sec total
- **Concurrent Conversations**: 100+ simultaneous

---

## Error Handling & Recovery

Robust error handling ensures reliable operation under various failure conditions.

### Connection Resilience

#### 1. WebSocket Reconnection
```typescript
class ResilientWebSocket {
    private reconnectAttempts = 0;
    private maxReconnectAttempts = 5;
    private reconnectDelay = 1000; // Start with 1s
    
    async connect() {
        try {
            this.ws = new WebSocket(this.url);
            this.setupEventHandlers();
            this.reconnectAttempts = 0; // Reset on successful connection
        } catch (error) {
            await this.handleConnectionError(error);
        }
    }
    
    private async handleConnectionError(error: Error) {
        this.reconnectAttempts++;
        
        if (this.reconnectAttempts <= this.maxReconnectAttempts) {
            const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
            logger.warn(`WebSocket connection failed, retrying in ${delay}ms...`);
            
            setTimeout(() => this.connect(), delay);
        } else {
            logger.error("Max reconnection attempts reached");
            this.onPermanentFailure?.(error);
        }
    }
}
```

#### 2. Redis Connection Recovery
```python
class RedisService:
    def __init__(self):
        self.redis_pool = None
        self.connection_retry_count = 0
        self.max_retries = 5
        
    async def get_redis_client(self) -> redis.Redis:
        """Get Redis client with automatic reconnection"""
        if not self.redis_pool:
            await self.connect()
            
        try:
            # Test connection
            await self.redis_pool.ping()
            self.connection_retry_count = 0  # Reset on success
            return self.redis_pool
        except redis.ConnectionError:
            await self.handle_connection_error()
            return await self.get_redis_client()
    
    async def handle_connection_error(self):
        self.connection_retry_count += 1
        
        if self.connection_retry_count <= self.max_retries:
            delay = min(30, 2 ** self.connection_retry_count)
            logger.warning(f"Redis connection lost, retrying in {delay}s...")
            await asyncio.sleep(delay)
            await self.connect()
        else:
            raise ConnectionError("Redis connection permanently failed")
```

### Audio Processing Error Recovery

#### 1. Audio Buffer Underrun/Overrun
```typescript
class AudioStreamManager {
    private bufferHealthCheck() {
        const bufferSize = this.audioQueue.length;
        
        if (bufferSize > this.maxBufferSize) {
            // Buffer overrun - drop oldest chunks
            const dropCount = bufferSize - this.targetBufferSize;
            this.audioQueue.splice(0, dropCount);
            logger.warn(`Dropped ${dropCount} audio chunks due to buffer overrun`);
        }
        
        if (bufferSize < this.minBufferSize && this.isPlaying) {
            // Buffer underrun - pause playback temporarily
            this.pausePlayback();
            logger.warn("Audio playback paused due to buffer underrun");
        }
    }
    
    private pausePlayback() {
        this.isPlaying = false;
        // Resume when buffer is healthy again
        setTimeout(() => {
            if (this.audioQueue.length >= this.targetBufferSize) {
                this.resumePlayback();
            }
        }, 100);
    }
}
```

#### 2. STT Processing Failures
```python
class AudioProcessor:
    async def process_audio_chunk(self, audio_bytes: bytes) -> List[Dict]:
        try:
            return await self._process_audio_internal(audio_bytes)
        except whisper.ModelError as e:
            logger.error(f"STT model error: {e}")
            # Fall back to partial transcription or silence
            return [{"event_type": "error", "message": "STT temporarily unavailable"}]
        except Exception as e:
            logger.error(f"Unexpected audio processing error: {e}", exc_info=True)
            # Continue processing, skip problematic chunk
            return []
    
    def handle_transcription_error(self, error: Exception):
        """Handle various transcription errors gracefully"""
        if isinstance(error, whisper.ModelTimeoutError):
            # Audio too long, split into smaller chunks
            return self.process_in_smaller_chunks()
        elif isinstance(error, whisper.NoSpeechError):
            # No speech detected, return empty transcript
            return ""
        else:
            # Log error and continue
            logger.error(f"Transcription error: {error}")
            return "[transcription error]"
```

#### 3. LLM Service Failures
```python
class LLMService:
    async def generate_response_with_retry(
        self, 
        messages: List[Dict], 
        max_retries: int = 3
    ) -> AsyncIterator[str]:
        """Generate LLM response with automatic retry and fallback"""
        
        for attempt in range(max_retries):
            try:
                async for token in self.primary_llm.stream(messages):
                    yield token
                return  # Success, exit retry loop
                
            except openai.RateLimitError:
                if attempt < max_retries - 1:
                    delay = 2 ** attempt  # Exponential backoff
                    logger.warning(f"Rate limited, retrying in {delay}s...")
                    await asyncio.sleep(delay)
                else:
                    # Fall back to local model
                    logger.warning("Falling back to local LLM due to rate limits")
                    async for token in self.fallback_llm.stream(messages):
                        yield token
                        
            except openai.APIError as e:
                logger.error(f"LLM API error (attempt {attempt + 1}): {e}")
                if attempt == max_retries - 1:
                    yield "I'm sorry, I'm experiencing technical difficulties. Please try again."
```

### Data Consistency

#### 1. Conversation State Recovery
```python
async def recover_conversation_state(conversation_id: str) -> Dict:
    """Recover conversation state from Redis with fallback"""
    try:
        # Try to load from Redis
        history = await get_conversation_history(conversation_id)
        config = await get_conversation_config(conversation_id)
        
        if not history:
            # Initialize new conversation
            history = [{"role": "system", "content": settings.SYSTEM_PROMPT}]
            await save_conversation_history(conversation_id, history)
        
        return {"history": history, "config": config}
        
    except RedisError:
        # Fallback to in-memory state
        logger.warning(f"Redis unavailable, using memory state for {conversation_id}")
        return {
            "history": [{"role": "system", "content": settings.SYSTEM_PROMPT}],
            "config": {}
        }
```

#### 2. Message Deduplication
```python
class MessageProcessor:
    def __init__(self):
        self.processed_messages: Set[str] = set()
        self.message_cache_ttl = 300  # 5 minutes
    
    async def process_message(self, message_id: str, payload: Dict):
        """Process message with deduplication"""
        if message_id in self.processed_messages:
            logger.debug(f"Duplicate message ignored: {message_id}")
            return
        
        try:
            await self._process_message_internal(payload)
            self.processed_messages.add(message_id)
            
            # Clean up old message IDs periodically
            if len(self.processed_messages) > 1000:
                await self._cleanup_old_message_ids()
                
        except Exception as e:
            logger.error(f"Error processing message {message_id}: {e}")
```

---

## Performance Optimizations

The system implements several optimizations for low-latency, high-throughput operation.

### Audio Processing Optimizations

#### 1. Efficient PCM Conversion
```typescript
// Optimized PCM processing with minimal memory allocation
class OptimizedPCMProcessor extends AudioWorkletProcessor {
    private readonly bufferPool: Float32Array[] = [];
    private readonly outputPool: Int16Array[] = [];
    
    process(inputs: Float32Array[][]): boolean {
        const input = inputs[0]?.[0];
        if (!input) return true;
        
        // Reuse buffers from pool to minimize GC pressure
        const workBuffer = this.getPooledBuffer(input.length);
        const outputBuffer = this.getPooledOutput(input.length);
        
        // Vectorized operations where possible
        this.fastDownsample(input, workBuffer);
        this.fastPCMConvert(workBuffer, outputBuffer);
        
        this.port.postMessage(outputBuffer.buffer.slice(0, outputBuffer.byteLength));
        
        // Return buffers to pool
        this.returnToPool(workBuffer, outputBuffer);
        return true;
    }
    
    private fastDownsample(input: Float32Array, output: Float32Array) {
        // Optimized downsampling with SIMD-friendly operations
        const ratio = this.inputSampleRate / this.targetSampleRate;
        for (let i = 0; i < output.length; i++) {
            const sourceIndex = i * ratio;
            const floorIndex = Math.floor(sourceIndex);
            output[i] = input[floorIndex]; // Simplified for performance
        }
    }
}
```

#### 2. Streaming Audio Buffers
```python
class StreamingAudioBuffer:
    def __init__(self, target_size: int = 8192):
        self.buffer = bytearray()
        self.target_size = target_size
        self.chunk_ready_event = asyncio.Event()
    
    async def add_data(self, data: bytes):
        """Add data and signal when chunk is ready"""
        self.buffer.extend(data)
        if len(self.buffer) >= self.target_size:
            self.chunk_ready_event.set()
    
    async def get_chunk(self) -> bytes:
        """Get next chunk when available"""
        await self.chunk_ready_event.wait()
        
        if len(self.buffer) >= self.target_size:
            chunk = bytes(self.buffer[:self.target_size])
            del self.buffer[:self.target_size]
            
            # Reset event if buffer is below threshold
            if len(self.buffer) < self.target_size:
                self.chunk_ready_event.clear()
                
            return chunk
        
        return b''
```

### Redis Optimizations

#### 1. Connection Pooling
```python
class OptimizedRedisService:
    def __init__(self):
        self.connection_pool = redis.ConnectionPool(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            max_connections=20,          # Pool size
            retry_on_timeout=True,
            socket_keepalive=True,
            socket_keepalive_options={
                'TCP_KEEPIDLE': 300,     # Start keepalive after 5 min
                'TCP_KEEPINTVL': 30,     # Keepalive interval
                'TCP_KEEPCNT': 3         # Max keepalive probes
            }
        )
    
    async def get_client(self) -> redis.Redis:
        return redis.Redis(connection_pool=self.connection_pool)
```

#### 2. Pipeline Operations
```python
async def batch_publish_messages(messages: List[Tuple[str, str]]):
    """Publish multiple messages efficiently using pipeline"""
    client = await redis_service.get_client()
    
    async with client.pipeline() as pipe:
        for channel, message in messages:
            pipe.publish(channel, message)
        
        results = await pipe.execute()
        logger.debug(f"Published {len(messages)} messages in batch")
        return results
```

#### 3. Memory-Efficient Message Handling
```python
class MemoryEfficientSubscriber:
    def __init__(self, channels: List[str]):
        self.channels = channels
        self.message_handlers: Dict[str, Callable] = {}
        
    async def subscribe_and_process(self):
        """Subscribe with minimal memory footprint"""
        client = await redis_service.get_client()
        pubsub = client.pubsub()
        
        # Subscribe to all channels at once
        await pubsub.subscribe(*self.channels)
        
        # Process messages with bounded memory
        while True:
            try:
                # Timeout prevents memory buildup
                message = await pubsub.get_message(timeout=1.0)
                if message and message["type"] == "message":
                    # Process immediately, don't queue
                    await self.process_message_immediately(message)
            except asyncio.TimeoutError:
                # Periodic cleanup and health checks
                await self.cleanup_resources()
```

### WebSocket Optimizations

#### 1. Message Compression
```python
class CompressedWebSocketEndpoint:
    def __init__(self):
        self.compression_threshold = 1024  # Compress messages > 1KB
        
    async def send_json_optimized(self, websocket: WebSocket, data: Dict):
        """Send JSON with optional compression"""
        json_str = json.dumps(data, separators=(',', ':'))  # Compact JSON
        
        if len(json_str) > self.compression_threshold:
            # Compress large messages
            compressed = gzip.compress(json_str.encode('utf-8'))
            await websocket.send_bytes(compressed)
            await websocket.send_json({"type": "compressed", "encoding": "gzip"})
        else:
            await websocket.send_text(json_str)
```

#### 2. Efficient Binary Streaming
```python
async def stream_audio_efficiently(websocket: WebSocket, audio_data: bytes):
    """Stream audio with optimal chunk sizes"""
    optimal_chunk_size = 4096  # 4KB chunks for optimal network performance
    
    for i in range(0, len(audio_data), optimal_chunk_size):
        chunk = audio_data[i:i + optimal_chunk_size]
        
        # Send without awaiting to maximize throughput
        asyncio.create_task(websocket.send_bytes(chunk))
        
        # Yield control periodically to prevent blocking
        if i % (optimal_chunk_size * 10) == 0:
            await asyncio.sleep(0)
```

### LLM Response Optimizations

#### 1. Token Batching
```python
class TokenBatcher:
    def __init__(self, batch_size: int = 5, timeout_ms: int = 50):
        self.batch_size = batch_size
        self.timeout_ms = timeout_ms
        self.token_buffer: List[str] = []
        self.last_batch_time = time.time()
    
    async def add_token(self, token: str, conversation_id: str) -> Optional[str]:
        """Add token and return batched string when ready"""
        self.token_buffer.append(token)
        current_time = time.time()
        
        should_flush = (
            len(self.token_buffer) >= self.batch_size or
            (current_time - self.last_batch_time) * 1000 >= self.timeout_ms
        )
        
        if should_flush:
            batched_tokens = ''.join(self.token_buffer)
            self.token_buffer.clear()
            self.last_batch_time = current_time
            return batched_tokens
        
        return None
```

#### 2. Parallel Tool Execution
```python
class ParallelToolExecutor:
    async def execute_tools_parallel(self, tool_calls: List[Dict]) -> List[Dict]:
        """Execute multiple tools in parallel"""
        tasks = []
        
        for tool_call in tool_calls:
            task = asyncio.create_task(
                self.execute_single_tool(tool_call)
            )
            tasks.append(task)
        
        # Wait for all tools to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Handle any failed tools
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Tool {tool_calls[i]['name']} failed: {result}")
                processed_results.append({
                    "tool_call_id": tool_calls[i]["id"],
                    "role": "tool",
                    "name": tool_calls[i]["name"],
                    "content": json.dumps({"error": str(result)})
                })
            else:
                processed_results.append(result)
        
        return processed_results
```

---

## Development & Debugging

### Logging and Observability

#### 1. Structured Logging
```python
import structlog

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# Usage in components
async def process_audio_with_logging(conversation_id: str, audio_data: bytes):
    log = logger.bind(
        conversation_id=conversation_id,
        audio_size=len(audio_data),
        component="vad_stt_worker"
    )
    
    log.info("Starting audio processing")
    
    try:
        result = await process_audio(audio_data)
        log.info("Audio processing completed", transcript_length=len(result))
        return result
    except Exception as e:
        log.error("Audio processing failed", error=str(e))
        raise
```

#### 2. Performance Metrics
```python
class PerformanceMonitor:
    def __init__(self):
        self.metrics: Dict[str, List[float]] = defaultdict(list)
        self.start_times: Dict[str, float] = {}
    
    def start_timing(self, operation: str, context: str = ""):
        key = f"{operation}:{context}" if context else operation
        self.start_times[key] = time.time()
    
    def end_timing(self, operation: str, context: str = ""):
        key = f"{operation}:{context}" if context else operation
        if key in self.start_times:
            duration = time.time() - self.start_times[key]
            self.metrics[key].append(duration)
            del self.start_times[key]
            
            # Log slow operations
            if duration > 0.5:  # 500ms threshold
                logger.warning("Slow operation detected", 
                             operation=operation, 
                             duration_ms=duration * 1000)
    
    def get_stats(self, operation: str) -> Dict:
        values = self.metrics.get(operation, [])
        if not values:
            return {}
        
        return {
            "count": len(values),
            "avg_ms": sum(values) / len(values) * 1000,
            "min_ms": min(values) * 1000,
            "max_ms": max(values) * 1000,
            "p95_ms": sorted(values)[int(len(values) * 0.95)] * 1000
        }

# Usage
monitor = PerformanceMonitor()

async def timed_operation(conversation_id: str):
    monitor.start_timing("llm_response", conversation_id)
    try:
        result = await generate_llm_response()
        return result
    finally:
        monitor.end_timing("llm_response", conversation_id)
```

### Debug Tools

#### 1. WebSocket Message Inspector
```typescript
class WebSocketDebugger {
    private messageLog: Array<{
        timestamp: number;
        direction: 'in' | 'out';
        type: 'json' | 'binary';
        data: any;
        size?: number;
    }> = [];
    
    logIncomingMessage(data: any) {
        const entry = {
            timestamp: Date.now(),
            direction: 'in' as const,
            type: data instanceof ArrayBuffer ? 'binary' as const : 'json' as const,
            data: data instanceof ArrayBuffer ? `[Binary ${data.byteLength} bytes]` : data,
            size: data instanceof ArrayBuffer ? data.byteLength : undefined
        };
        
        this.messageLog.push(entry);
        this.trimLog();
        
        if (this.debugMode) {
            console.log('WS ←', entry);
        }
    }
    
    logOutgoingMessage(data: any) {
        const entry = {
            timestamp: Date.now(),
            direction: 'out' as const,
            type: data instanceof ArrayBuffer ? 'binary' as const : 'json' as const,
            data: data instanceof ArrayBuffer ? `[Binary ${data.byteLength} bytes]` : data,
            size: data instanceof ArrayBuffer ? data.byteLength : undefined
        };
        
        this.messageLog.push(entry);
        this.trimLog();
        
        if (this.debugMode) {
            console.log('WS →', entry);
        }
    }
    
    exportMessageLog(): string {
        return JSON.stringify(this.messageLog, null, 2);
    }
    
    getMessageStats() {
        const stats = {
            totalMessages: this.messageLog.length,
            jsonMessages: this.messageLog.filter(m => m.type === 'json').length,
            binaryMessages: this.messageLog.filter(m => m.type === 'binary').length,
            totalBytes: this.messageLog
                .filter(m => m.size)
                .reduce((sum, m) => sum + (m.size || 0), 0),
            timeRange: {
                start: Math.min(...this.messageLog.map(m => m.timestamp)),
                end: Math.max(...this.messageLog.map(m => m.timestamp))
            }
        };
        
        return stats;
    }
}
```

#### 2. Audio Analysis Tools
```typescript
class AudioAnalyzer {
    analyzeAudioBuffer(buffer: ArrayBuffer): AudioAnalysis {
        const samples = new Int16Array(buffer);
        
        // Calculate RMS (Root Mean Square) for volume
        let sumSquares = 0;
        for (let i = 0; i < samples.length; i++) {
            const normalized = samples[i] / 32768;
            sumSquares += normalized * normalized;
        }
        const rms = Math.sqrt(sumSquares / samples.length);
        
        // Calculate peak amplitude
        const peak = Math.max(...Array.from(samples).map(Math.abs)) / 32768;
        
        // Basic frequency analysis (zero-crossing rate)
        let zeroCrossings = 0;
        for (let i = 1; i < samples.length; i++) {
            if ((samples[i] >= 0) !== (samples[i-1] >= 0)) {
                zeroCrossings++;
            }
        }
        const zcr = zeroCrossings / samples.length;
        
        return {
            rms,
            peak,
            zeroCrossingRate: zcr,
            sampleCount: samples.length,
            durationMs: (samples.length / 16000) * 1000,
            estimatedFrequency: zcr * 16000 / 2 // Rough estimate
        };
    }
}

interface AudioAnalysis {
    rms: number;
    peak: number;
    zeroCrossingRate: number;
    sampleCount: number;
    durationMs: number;
    estimatedFrequency: number;
}
```

#### 3. Redis Message Tracer
```python
class RedisMessageTracer:
    def __init__(self):
        self.traced_channels: Set[str] = set()
        self.message_log: List[Dict] = []
        self.max_log_size = 1000
    
    async def trace_channel(self, channel: str, duration_seconds: int = 60):
        """Trace messages on a Redis channel for debugging"""
        if channel in self.traced_channels:
            logger.warning(f"Channel {channel} already being traced")
            return
        
        self.traced_channels.add(channel)
        client = await redis_service.get_client()
        pubsub = client.pubsub()
        
        try:
            await pubsub.subscribe(channel)
            logger.info(f"Started tracing channel: {channel}")
            
            start_time = time.time()
            while time.time() - start_time < duration_seconds:
                message = await pubsub.get_message(timeout=1.0)
                if message and message["type"] == "message":
                    self.log_message(channel, message)
                    
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
            self.traced_channels.remove(channel)
            logger.info(f"Stopped tracing channel: {channel}")
    
    def log_message(self, channel: str, message: Any):
        entry = {
            "timestamp": time.time(),
            "channel": channel,
            "size": len(message["data"]) if isinstance(message["data"], bytes) else len(str(message["data"])),
            "type": "binary" if isinstance(message["data"], bytes) else "text",
            "preview": self.get_message_preview(message["data"])
        }
        
        self.message_log.append(entry)
        
        # Trim log if too large
        if len(self.message_log) > self.max_log_size:
            self.message_log = self.message_log[-self.max_log_size:]
        
        logger.debug(f"Redis message on {channel}", **entry)
    
    def get_message_preview(self, data: Any) -> str:
        if isinstance(data, bytes):
            if len(data) > 100:
                return f"[Binary {len(data)} bytes]"
            else:
                return data.hex()[:50] + "..."
        else:
            text = str(data)
            return text[:100] + "..." if len(text) > 100 else text
    
    def export_trace_log(self) -> str:
        return json.dumps(self.message_log, indent=2, default=str)
```

This comprehensive technical documentation provides deep insights into the SPT Assistant's architecture, enabling developers to understand, extend, and optimize the system effectively. 