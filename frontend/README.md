# SPT Assistant Frontend

A modern React + TypeScript frontend for the SPT Assistant real-time AI voice interface. Built with Vite for fast development and optimized production builds.

## 🎯 Overview

The SPT Assistant frontend provides a sleek, futuristic web interface for real-time voice conversations with AI. It features audio-reactive animations, real-time transcription display, and seamless WebSocket communication with the backend services.

## ✨ Key Features

### 🎨 **Modern UI/UX**
- **Futuristic design** with cyberpunk-inspired aesthetics
- **Audio-reactive animations** that respond to voice input and TTS output
- **Real-time chat interface** with streaming text updates
- **Responsive design** optimized for desktop and mobile

### 🔊 **Advanced Audio Processing**
- **Real-time audio streaming** via WebSocket with binary data support
- **Voice Activity Detection (VAD)** visualization
- **Audio level monitoring** for both microphone input and TTS playback
- **Sentence-by-sentence TTS playback** for natural conversation flow
- **Barge-in support** - interrupt the assistant naturally

### 🌐 **Real-Time Communication**
- **WebSocket-based** bi-directional communication
- **Binary audio streaming** for low-latency voice transmission
- **JSON message handling** for transcripts, tokens, and control signals
- **Automatic reconnection** with exponential backoff

## 🏗️ Architecture

```
┌─────────────────┐    WebSocket     ┌──────────────────┐
│   React App     │◄────────────────►│  FastAPI Gateway │
│                 │   (JSON + Binary) │                  │
├─────────────────┤                   └──────────────────┘
│ Audio Streamer  │ ──── PCM Audio ──────────────────────►
├─────────────────┤                                       
│ Audio Player    │ ◄──── TTS Audio ──────────────────────
├─────────────────┤                                       
│ Chat Display    │ ◄──── Transcripts & Tokens ──────────
├─────────────────┤                                       
│ Futuristic UI   │ ──── Audio Levels ────────────────────
└─────────────────┘
```

### Core Components

#### 🎤 **Audio Streaming (`useAudioStreamer`)**
- Captures microphone input using Web Audio API
- Processes audio through AudioWorklet for real-time PCM conversion
- Monitors audio levels for visual feedback
- Handles device selection and permissions

#### 🔊 **Audio Playback (`useStreamedAudioPlayer`)**
- Receives binary audio chunks via WebSocket
- Queues and plays TTS audio sentence-by-sentence
- Provides audio level monitoring for animations
- Supports playback interruption (barge-in)

#### 🌐 **WebSocket Communication (`useWebSocket`)**
- Manages persistent WebSocket connection with auto-reconnect
- Handles both JSON messages and binary audio data
- Provides connection status and error handling
- Supports graceful disconnection and cleanup

#### 🎨 **Futuristic Animation (`FuturisticAnimation`)**
- Audio-reactive visual effects with dynamic glow
- Cyberpunk-inspired design with rotating elements
- Real-time response to audio levels
- Status indicators and loading states

#### 💬 **Chat Interface (`ChatDisplay`)**
- Real-time message display with streaming updates
- Support for user messages, assistant responses, and tool status
- Partial transcript display during speech recognition
- Auto-scrolling and message history

## 🛠️ Technology Stack

### Frontend Framework
- **React 19** with TypeScript for type safety
- **Vite** for fast development and optimized builds
- **Zustand** for lightweight state management
- **CSS3** with custom properties for theming

### Audio Processing
- **Web Audio API** for real-time audio processing
- **AudioWorklet** for low-latency PCM conversion
- **MediaDevices API** for microphone access
- **Binary WebSocket** for audio streaming

### Development Tools
- **TypeScript** for static type checking
- **ESLint** for code quality
- **Vite** for hot module replacement
- **Modern ES modules** for optimal bundling

## 🚀 Getting Started

### Prerequisites
- **Node.js 18+** and npm/yarn/pnpm
- **Modern browser** with WebSocket and Web Audio API support
- **SPT Assistant backend** running on `localhost:8000`

### Installation

```bash
# Clone the repository
git clone https://github.com/ezeeFlop/spt-assistant
cd spt-assistant/frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

### Configuration

The frontend connects to the backend via WebSocket. Configure the connection in `public/config.js`:

```javascript
window.APP_CONFIG = {
    VITE_API_BASE_URL: 'ws://localhost:8000/api/v1/ws/audio',
};
```

For production deployment, update this URL to match your backend server.

## 📁 Project Structure

```
frontend/
├── public/
│   ├── config.js              # Runtime configuration
│   └── vite.svg               # App icon
├── src/
│   ├── components/            # React components
│   │   ├── ChatDisplay.tsx    # Chat interface
│   │   ├── FuturisticAnimation.tsx # Audio-reactive UI
│   │   └── *.tsx              # Other components
│   ├── hooks/                 # Custom React hooks
│   │   ├── useAudioStreamer.ts    # Microphone capture
│   │   ├── useStreamedAudioPlayer.ts # TTS playback
│   │   └── useWebSocket.ts    # WebSocket communication
│   ├── store/                 # State management
│   │   └── useAppStore.ts     # Zustand store
│   ├── audio/                 # Audio processing
│   │   └── pcm-processor.ts   # AudioWorklet processor
│   ├── App.tsx                # Main application
│   ├── App.css                # Global styles
│   └── main.tsx               # Application entry point
├── package.json               # Dependencies and scripts
├── vite.config.ts             # Vite configuration
└── tsconfig.json              # TypeScript configuration
```

## 🎨 Styling & Theming

The frontend uses a cyberpunk-inspired design system with CSS custom properties:

```css
:root {
  --primary-bg-color: #0a0f1e;     /* Deep space blue */
  --secondary-bg-color: #141a2e;   /* Panel background */
  --accent-color: #00ffff;         /* Cyan accent */
  --text-color: #e0e0e0;           /* Light text */
  --glow-color: rgba(0, 255, 255, 0.7); /* Glow effects */
}
```

### Audio-Reactive Elements
- **Dynamic glow effects** based on audio levels
- **Pulsing animations** synchronized with voice activity
- **Color intensity** that responds to audio amplitude
- **Smooth transitions** for natural visual feedback

## 🔧 Development

### Available Scripts

```bash
# Development server with hot reload
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview

# Lint code
npm run lint
```

### Code Quality

The project uses ESLint with TypeScript rules for code quality:

```bash
# Run linter
npm run lint

# Auto-fix issues
npm run lint -- --fix
```

### Browser Compatibility

- **Chrome/Edge 88+** (recommended)
- **Firefox 84+**
- **Safari 14+**

Requires modern browser features:
- WebSocket API
- Web Audio API
- AudioWorklet
- MediaDevices API
- ES2020+ features

## 🌐 WebSocket API

The frontend communicates with the backend using a WebSocket connection that handles both JSON messages and binary audio data.

### Message Types

#### Incoming Messages (Server → Client)
```typescript
// Transcription
{ type: "partial_transcript", text: string }
{ type: "final_transcript", transcript: string, conversation_id: string }

// LLM Response
{ type: "token", content: string, conversation_id: string }
{ type: "tool", name: string, status: string }

// Audio Streaming
{ type: "audio_stream_start", sample_rate: number, channels: number }
{ type: "raw_audio_chunk", data: ArrayBuffer }
{ type: "audio_stream_end", conversation_id: string }

// System Events
{ type: "system_event", event: "conversation_started", conversation_id: string }
{ type: "barge_in_notification", conversation_id: string }
```

#### Outgoing Messages (Client → Server)
```typescript
// Binary audio data (PCM 16-bit, 16kHz)
ArrayBuffer // Microphone audio chunks
```

## 🎯 State Management

The application uses Zustand for state management with the following key state:

```typescript
interface AppState {
  // Audio State
  isRecording: boolean;
  isPlayingAudio: boolean;
  micAudioLevel: number;
  playbackAudioLevel: number;

  // Conversation State
  activeConversationId: string | null;
  chatMessages: ChatMessage[];
  partialTranscript: string;

  // Device Settings
  selectedMicId: string | null;
  availableMics: MediaDeviceInfo[];

  // Connection State
  isConnected: boolean;
  connectionError: string | null;
}
```

## 🔊 Audio Processing Pipeline

### Microphone Input
1. **MediaDevices.getUserMedia()** - Capture microphone
2. **AudioContext** - Create audio processing context
3. **AudioWorklet** - Real-time PCM conversion (16kHz, 16-bit)
4. **WebSocket** - Stream binary audio to backend

### TTS Output
1. **WebSocket** - Receive binary audio chunks
2. **AudioBuffer** - Convert PCM to Web Audio format
3. **AudioBufferSourceNode** - Queue and play sentences
4. **AnalyserNode** - Monitor audio levels for visualization

## 🚀 Production Deployment

### Build for Production

```bash
# Create optimized build
npm run build

# The dist/ folder contains the production build
```

### Deployment Options

#### Static Hosting (Recommended)
- **Vercel, Netlify, or GitHub Pages** for static hosting
- **CDN distribution** for global performance
- **HTTPS required** for microphone access

#### Docker Deployment
```dockerfile
FROM nginx:alpine
COPY dist/ /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/nginx.conf
EXPOSE 80
```

#### Environment Configuration
Update `public/config.js` for your production backend:

```javascript
window.APP_CONFIG = {
    VITE_API_BASE_URL: 'wss://your-backend.com/api/v1/ws/audio',
};
```

## 🐛 Troubleshooting

### Common Issues

#### Microphone Not Working
- **Check browser permissions** - Allow microphone access
- **HTTPS required** - Microphone API requires secure context
- **Device selection** - Try different microphone devices

#### WebSocket Connection Failed
- **Backend running** - Ensure SPT Assistant backend is accessible
- **CORS configuration** - Check backend CORS settings
- **Network connectivity** - Verify WebSocket endpoint

#### Audio Playback Issues
- **Browser compatibility** - Use Chrome/Edge for best support
- **Audio context** - Click to start (user gesture required)
- **Sample rate mismatch** - Backend should send 16kHz audio

### Debug Mode

Enable debug logging in browser console:
```javascript
localStorage.setItem('debug', 'spt:*');
```

## 🤝 Contributing

1. **Fork the repository**
2. **Create feature branch** (`git checkout -b feature/amazing-feature`)
3. **Follow code style** - Use ESLint and TypeScript
4. **Test thoroughly** - Ensure audio functionality works
5. **Submit pull request**

### Development Guidelines
- **TypeScript strict mode** - All code must be properly typed
- **Component composition** - Prefer composition over inheritance
- **Custom hooks** - Extract reusable logic into hooks
- **Performance** - Optimize for real-time audio processing

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](../LICENSE) file for details.

## 🙏 Acknowledgments

- **React Team** for the excellent framework
- **Vite** for lightning-fast development experience
- **Web Audio API** for enabling real-time audio processing
- **Zustand** for simple and effective state management

---

**Ready to experience the future of voice AI?** 🚀 Start the development server and begin your conversation with TARA!
