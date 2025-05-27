# SPT Assistant: Real-Time AI Voice Assistant with Distributed Architecture

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18+-blue.svg)](https://reactjs.org/)

**Author:** Christophe Verdier  
**Contact:** christophe.verdier@sponge-theory.ai  
**Website:** [https://sponge-theory.ai](https://sponge-theory.ai)  
**Repository:** [https://github.com/ezeeFlop/spt-assistant](https://github.com/ezeeFlop/spt-assistant)

SPT Assistant is a cutting-edge, real-time AI voice assistant that prioritizes privacy, local execution, and enterprise-grade scalability. Built with a distributed microservices architecture, it delivers natural voice conversations with advanced features like barge-in detection, streaming responses, and flexible deployment options.

![SPT Assistant](docs/frontend.png)

## 🚀 Key Features

### 🎯 **Real-Time Voice Interaction**
- **Ultra-low latency** WebSocket-based communication
- **Bi-directional streaming** for natural conversations
- **Intelligent barge-in detection** - interrupt the assistant naturally
- **Sentence-by-sentence TTS** for immediate audio feedback
- **Voice Activity Detection (VAD)** with Silero VAD

### 🔒 **Privacy-First & Local Execution**
- **Complete local processing** - your data never leaves your infrastructure
- **Local LLM support** via Ollama, LM Studio, or any OpenAI-compatible endpoint
- **Local TTS** with Piper (neural TTS) or Coqui TTS
- **Local STT** with faster-whisper and WhisperX
- **Optional cloud integration** for enhanced capabilities

### 🏗️ **Distributed Microservices Architecture**
- **Redis pub/sub backbone** for seamless inter-service communication
- **Horizontally scalable** - scale each component independently
- **Docker & Kubernetes ready** with production deployment configs
- **GPU optimization** for STT and TTS workloads
- **Fault-tolerant design** with graceful degradation

### 🎨 **Modern Web Interface**
- **React + TypeScript** frontend with real-time audio visualization
- **Audio-reactive animations** responding to voice input and TTS output
- **Responsive design** optimized for desktop and mobile
- **Real-time conversation display** with streaming text updates

## 🏛️ Architecture Overview

SPT Assistant employs a sophisticated distributed architecture where specialized workers communicate through Redis pub/sub channels:

```
┌─────────────────┐    WebSocket    ┌──────────────────┐
│   React Client  │◄──────────────►│  FastAPI Gateway │
└─────────────────┘                 └──────────────────┘
                                             │
                                    ┌────────┴────────┐
                                    │      Redis      │
                                    │   (Pub/Sub)     │
                                    └────────┬────────┘
                          ┌─────────────────┼─────────────────┐
                          │                 │                 │
                    ┌─────▼─────┐    ┌─────▼─────┐    ┌─────▼─────┐
                    │VAD/STT    │    │    LLM    │    │    TTS    │
                    │Worker     │    │Orchestrator│    │  Worker   │
                    └───────────┘    └───────────┘    └───────────┘
                          │                 │                 │
                    ┌─────▼─────┐    ┌─────▼─────┐    ┌─────▼─────┐
                    │  Silero   │    │ LiteLLM   │    │   Piper   │
                    │faster-    │    │(OpenAI/   │    │  Coqui    │
                    │whisper    │    │Ollama/etc)│    │ElevenLabs │
                    └───────────┘    └───────────┘    └───────────┘
```

### Core Components

#### 🌐 **FastAPI Gateway** (`app/`)
- WebSocket endpoint for real-time client communication
- JWT authentication and session management
- Message routing between client and backend services
- Static file serving for the React frontend

#### 🎤 **VAD/STT Worker** (`vad_stt_worker/`)
- Voice Activity Detection using Silero VAD
- Speech-to-Text with faster-whisper or WhisperX
- Real-time audio chunk processing
- Barge-in detection and signaling

#### 🧠 **LLM Orchestrator** (`llm_orchestrator_worker/`)
- Conversation state management with Redis persistence
- LLM integration via LiteLLM (supports 100+ providers)
- Tool execution and function calling
- Streaming response processing with sentence boundary detection

#### 🗣️ **TTS Worker** (`tts_worker/`)
- Multi-provider TTS support (Piper, Coqui, ElevenLabs)
- Real-time audio streaming to clients
- Queue-based processing for conversation management
- Audio format conversion and optimization

## 🛠️ Technology Stack

### Backend
- **Python 3.12+** with async/await throughout
- **FastAPI** for high-performance API endpoints
- **Redis** for pub/sub messaging and state management
- **UV** for fast Python package management
- **Pydantic** for data validation and settings

### AI/ML Components
- **LiteLLM** - Universal LLM API (OpenAI, Anthropic, Ollama, etc.)
- **faster-whisper** - Optimized Whisper implementation for STT
- **Silero VAD** - Voice Activity Detection
- **Piper TTS** - Neural text-to-speech synthesis
- **NLTK** - Natural language processing for sentence segmentation

### Frontend
- **React 18** with TypeScript
- **Zustand** for state management
- **Vite** for fast development and building
- **WebSocket API** for real-time communication

### Infrastructure
- **Docker** with multi-stage builds
- **Docker Swarm** for production orchestration
- **Redis Cluster** support for high availability

## 🚀 Quick Start

### Prerequisites

- **Python 3.12+**
- **Node.js 18+** and npm/yarn/pnpm
- **Redis server** (local or remote)
- **UV package manager**: `pip install uv`

### 1. Clone and Setup

```bash
git clone https://github.com/ezeeFlop/spt-assistant
cd spt-assistant

# Make helper scripts executable
chmod +x run.sh kill_all.sh
```

### 2. Configure Environment Variables

Create `.env` files for each service:

```bash
# Copy example configurations
cp app/.env.example app/.env
cp llm_orchestrator_worker/.env.example llm_orchestrator_worker/.env
cp tts_worker/.env.example tts_worker/.env
cp vad_stt_worker/.env.example vad_stt_worker/.env
```

### 3. Install Dependencies

```bash
# Backend services
cd app && uv sync && cd ..
cd vad_stt_worker && uv sync && cd ..
cd llm_orchestrator_worker && uv sync && cd ..
cd tts_worker && uv sync && cd ..

# Frontend
cd frontend && npm install && cd ..
```

### 4. Start Services

```bash
# Start all backend services
./run.sh

# Start frontend (in a new terminal)
cd frontend && npm run dev
```

### 5. Access the Application

- **Frontend**: http://localhost:5173
- **API Gateway**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs

## ⚙️ Configuration Guide

### Local LLM with Ollama

For complete privacy, run LLMs locally:

```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a model
ollama pull llama3.1

# Configure in llm_orchestrator_worker/.env
LLM_PROVIDER="ollama"
LLM_MODEL_NAME="llama3.1"
LLM_BASE_URL="http://localhost:11434/v1"
LLM_API_KEY="ollama"
```

### Local TTS with Piper

```bash
# Download Piper (included in project)
./install_piper.sh

# Configure in tts_worker/.env
TTS_PROVIDER="piper"
PIPER__EXECUTABLE_PATH="/path/to/piper/executable"
PIPER__VOICES_DIR="/path/to/piper_voices/"
PIPER__DEFAULT_VOICE_MODEL="fr_FR-siwis-medium.onnx"
```

### STT Configuration

```bash
# Configure in vad_stt_worker/.env
STT_MODEL_NAME="Systran/faster-whisper-large-v3"
STT_DEVICE="cuda"  # or "cpu"
STT_COMPUTE_TYPE="float16"  # or "int8" for CPU
```

## 🐳 Production Deployment

### Docker Swarm

```bash
# Build images
./build.sh

# Deploy stack
docker stack deploy -c docker-stack.yml spt-assistant
```

### Environment Variables for Production

```yaml
# docker-stack.yml excerpt
environment:
  - REDIS_HOST=redis
  - LLM_BASE_URL=http://ollama:11434
  - TTS_PROVIDER=piper
  - STT_DEVICE=cuda
```

## 🔧 Development

### Running Individual Services

```bash
# API Gateway
cd app && uv run dev

# VAD/STT Worker
cd vad_stt_worker && uv run python -m vad_stt_worker.main

# LLM Orchestrator
cd llm_orchestrator_worker && uv run python -m llm_orchestrator_worker.main

# TTS Worker
cd tts_worker && uv run python -m tts_worker.main
```

### Code Quality

```bash
# Linting and formatting
uv run ruff check .
uv run ruff format .

# Type checking
uv run mypy .
```

## 📊 Performance & Scaling

### Benchmarks
- **Latency**: <200ms end-to-end for local deployment
- **Throughput**: 100+ concurrent conversations per instance
- **Memory**: ~2GB RAM per worker (varies by model size)
- **GPU**: Optional but recommended for STT/TTS acceleration

### Scaling Guidelines
- **Horizontal scaling**: Deploy multiple instances of each worker
- **GPU allocation**: Assign STT and TTS workers to GPU nodes
- **Redis clustering**: Use Redis Cluster for high availability
- **Load balancing**: Use nginx or similar for API gateway load balancing

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

### Development Setup

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- **Piper TTS** for high-quality neural voice synthesis
- **faster-whisper** for optimized speech recognition
- **LiteLLM** for universal LLM integration
- **Silero** for voice activity detection
- **FastAPI** for the excellent async web framework

## 📞 Support & Contact

- **Issues**: [GitHub Issues](https://github.com/ezeeFlop/spt-assistant/issues)
- **Discussions**: [GitHub Discussions](https://github.com/ezeeFlop/spt-assistant/discussions)
- **Email**: christophe.verdier@sponge-theory.ai
- **Website**: [https://sponge-theory.ai](https://sponge-theory.ai)

---

**Ready to experience the future of voice AI?** ⭐ Star this repository and join the revolution in privacy-first, real-time AI assistants!

```
app/
├── api/
│   ├── deps.py
│   └── v1/
│       ├── __init__.py
│       └── endpoints/
│           ├── __init__.py
│           └── audio.py
├── core/
│   ├── __init__.py
│   ├── auth.py
│   ├── config.py
│   ├── logging_config.py
│   └── security.py
├── db/
│   ├── __init__.py
│   ├── base.py
│   ├── base_class.py
│   └── session.py
├── main.py
├── middleware/
│   ├── __init__.py
│   ├── cors.py
│   ├── db_health.py
│   ├── error_handler.py
│   ├── logging.py
│   └── validation.py
├── models/
│   └── __init__.py
├── schemas/
│   ├── __init__.py
│   └── ws_messages.py
├── services/
│   └── __init__.py
├── tasks/
└── utils/
pyproject.toml
README.md
```

