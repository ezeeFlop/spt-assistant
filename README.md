# Voice Assistant Platform

This project implements a real-time, French-first voice assistant capable of two-way spoken interaction, tool execution, and a modern web front-end. The backend services are built with Python and FastAPI, utilizing various open-source components for audio processing.

## Project Structure

The backend consists of several microservices:

-   **`app/`**: The main FastAPI Gateway. Handles WebSocket connections from the client, authentication, and routes messages to/from other services via Redis.
-   **`vad_stt_worker/`**: Voice Activity Detection (VAD) and Speech-to-Text (STT) worker. Consumes raw audio, performs VAD with Silero, and STT with faster-whisper.
-   **`llm_orchestrator/`**: LLM Orchestrator. Manages conversation flow, interacts with the chosen Language Model, handles tool calls, and requests TTS generation.
-   **`tts_service/`**: Text-to-Speech (TTS) service. Synthesizes speech from text using Piper TTS.
-   **`frontend/`**: (Details not covered here) Web front-end for user interaction.

All backend services communicate via Redis pub/sub.

## Prerequisites

-   Python 3.12+
-   [UV](https://github.com/astral-sh/uv) (Python package installer and resolver, `pip install uv`)
-   Redis server running.
-   (For TTS Service) Piper TTS executable and voice models. Download these and configure paths in `tts_service/.env`.
-   (For VAD/STT) STT models for faster-whisper will be downloaded on first run if not cached.

## Setup Instructions

1.  **Clone the Repository:**

    ```bash
    git clone <repository_url>
    cd <repository_name>
    ```

2.  **Environment Configuration:**

    Each service (`app`, `vad_stt_worker`, `llm_orchestrator`, `tts_service`) requires its own `.env` file in its respective directory for configuration. Create these based on the examples below. Adjust values as needed for your environment.

    **Common variables for workers (`vad_stt_worker`, `llm_orchestrator`, `tts_service`):**

    ```env
    # .env in vad_stt_worker/, llm_orchestrator/, tts_service/
    REDIS_HOST=localhost
    REDIS_PORT=6379
    # REDIS_PASSWORD=
    # REDIS_DB=0
    LOG_LEVEL=INFO
    ```

    **`app/.env`:**

    ```env
    # General app settings (can be omitted if defaults in config.py are fine)
    PROJECT_NAME="Voice Assistant Platform - Gateway"
    
    # Redis (shared with workers)
    REDIS_HOST=localhost
    REDIS_PORT=6379
    
    # JWT Secret - VERY IMPORTANT: Change this to a strong, unique secret key!
    JWT_SECRET_KEY="your-super-secret-key-please-change-in-production-for-app-gateway"
    # JWT_ALGORITHM="HS256" (default)
    # JWT_ACCESS_TOKEN_EXPIRE_MINUTES=1440 (default is 24 hours)
    ```

    **`vad_stt_worker/.env` (additional):**

    ```env
    # VAD Settings (defaults are in config.py, override here if needed)
    # VAD_MODEL_REPO="snakers4/silero-vad"
    # VAD_MODEL_NAME="silero_vad"
    # VAD_SAMPLING_RATE=16000
    # VAD_THRESHOLD=0.5
    
    # STT Settings
    STT_MODEL_NAME="Systran/faster-whisper-large-v3-french" # Or other Whisper model
    STT_DEVICE="cpu" # or "cuda"
    STT_COMPUTE_TYPE="int8" # e.g., "float16", "int8"
    # STT_LANGUAGE="fr"
    ```

    **`llm_orchestrator/.env` (additional):**

    ```env
    LLM_PROVIDER="openai" # or your provider
    LLM_MODEL_NAME="gpt-3.5-turbo" # or your model
    LLM_API_KEY="sk-your-openai-api-key" # Replace with your actual LLM API key
    # LLM_BASE_URL= (if using a custom OpenAI-compatible endpoint)
    # DEFAULT_TTS_VOICE_ID="fr_FR-siwis-medium" # Default voice for TTS requests
    ```

    **`tts_service/.env` (additional):**

    ```env
    PIPER_EXECUTABLE_PATH="/path/to/your/piper/executable" # IMPORTANT: Set this path
    PIPER_VOICES_DIR="/path/to/your/piper_voices/"        # IMPORTANT: Set this path
    # DEFAULT_PIPER_VOICE_MODEL="fr_FR-siwis-medium.onnx" # Default voice model file name (should be in VOICES_DIR)
    # PIPER_VOICE_NATIVE_SAMPLE_RATE=22050 # Sample rate of your Piper voice model
    # AUDIO_OUTPUT_SAMPLE_RATE=24000     # Target output sample rate (resampling will occur if different)
    ```

3.  **Install Dependencies for Each Service:**

    Navigate into each service's directory and install its dependencies using UV.

    ```bash
    # For the FastAPI Gateway
    cd app
    uv sync
    cd ..
    
    # For the VAD & STT Worker
    cd vad_stt_worker
    uv sync
    cd ..
    
    # For the LLM Orchestrator
    cd llm_orchestrator
    uv sync
    cd ..
    
    # For the TTS Service
    cd tts_service
    uv sync
    cd ..
    ```
    If you have a root `pyproject.toml` that manages all workspace packages (more advanced setup), you might run `uv sync` from the root. The current structure assumes per-service `pyproject.toml` for dependencies.

## Running the Services

Two helper scripts are provided in the root directory:

-   `run.sh`: Starts all backend services in the background. Logs for each service will be stored in a `logs/` directory in the project root.
-   `kill_all.sh`: Attempts to stop all services started by `run.sh`.

1.  **Make scripts executable:**

    ```bash
    chmod +x run.sh
    chmod +x kill_all.sh
    ```

2.  **Start all services:**

    ```bash
    ./run.sh
    ```
    This will launch:
    -   FastAPI Gateway (`app`)
    -   VAD & STT Worker (`vad_stt_worker`)
    -   LLM Orchestrator (`llm_orchestrator`)
    -   TTS Service (`tts_service`)

    Check the `logs/` directory for output from each service.

3.  **Accessing the API (Gateway):**

    The FastAPI gateway will typically be available at `http://localhost:8000` (as per `app/pyproject.toml`).
    -   API Docs (Swagger UI): `http://localhost:8000/docs`
    -   Health Check: `http://localhost:8000/v1/health`
    -   WebSocket Endpoint: `ws://localhost:8000/v1/ws/audio` (Requires JWT token, see below)

4.  **WebSocket Authentication (JWT):**

    The WebSocket endpoint `/v1/ws/audio` is protected by JWT authentication. The client must provide a valid JWT token as a query parameter named `token`.

    Example: `ws://localhost:8000/v1/ws/audio?token=<your_jwt_token>`

    For development, you'll need a way to generate a token. The `JWT_SECRET_KEY` in `app/.env` is used for this. You can create a small utility script or a temporary unsecured endpoint in the `app` service to generate a token using `app.core.security.create_access_token(data={"sub": "test_user"})`.

## Stopping the Services

```bash
./kill_all.sh
```
This script will attempt to find and terminate the processes for each service. You may need to verify manually using `ps aux | grep python` or `ps aux | grep uvicorn` if all processes were stopped, as `pgrep` patterns can sometimes be tricky.

## Development

-   **UV Package Manager**: This project uses UV for dependency management and running scripts. Refer to UV documentation for more commands.
-   **Individual Service Development**: You can run services individually by navigating to their directory and using `uv run dev` (or the specific script defined in their `pyproject.toml`).
-   **Linting and Formatting**: Consider using tools like Ruff (for linting and formatting) and MyPy (for type checking), as suggested in the dev-dependencies of `pyproject.toml` files.

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
# .env (you create this)
# .env.example (you create this)
```

## Next Steps

- Implement VAD & STT service interaction (e.g., via Redis Pub/Sub).
- Develop LLM Orchestrator.
- Integrate TTS Service.
- Build out REST API endpoints (e.g., for configuration).
- Add authentication (JWT).
- Implement detailed error handling and logging middleware.
- Write tests (unit, integration). 