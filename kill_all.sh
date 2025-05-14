#!/bin/bash

# Script to stop all backend services for the Voice Assistant Platform

echo "Attempting to stop all services..."

# Function to stop a service based on a pattern in its command line
# This is a bit rudimentary and might need adjustment based on how `uv run dev` spawns processes.
# It tries to find processes running main.py or uvicorn within the specific service directories.
stop_service() {
    local service_name="$1"
    local service_dir_pattern="$2" # e.g., "app", "vad_stt_worker"

    echo "Stopping $service_name (looking for processes in $service_dir_pattern)..."

    # Try to find PIDs: Look for python processes running main.py in the service directory
    # or uvicorn processes that might be started by `uv run dev` for the FastAPI app.
    # The pgrep pattern might need to be refined.
    # Example: pgrep -f "python.*${service_dir_pattern}/main.py" or pgrep -f "uvicorn.*main:app.*--port XXXX"
    # Using a simpler pgrep for now, may need to be more specific.
    
    # General patterns that might catch the processes:
    # 1. For Uvicorn (FastAPI app):
    pgrep -f "uvicorn.*app.main:app" | while read pid; do
        echo "Found uvicorn process for $service_name with PID $pid. Killing..."
        kill "$pid" || echo "Failed to kill $pid for $service_name (uvicorn)"
    done

    # 2. For Python workers (assuming they run a main.py in their directory):
    # This pattern is broad. If multiple python scripts run from these dirs, it might kill unintended ones.
    # A more specific command used in `uv run dev` would be better if known.
    pgrep -af "python.*${service_dir_pattern}/main.py" | while IFS=' ' read -r pid rest_of_cmd; do 
        echo "Found python process for $service_name with PID $pid (Cmd: $rest_of_cmd). Killing..."
        kill "$pid" || echo "Failed to kill $pid for $service_name (python main.py)"
    done

    # If `uv run dev` directly translates to a specific executable name identifiable with pgrep,
    # that would be more robust. For example, if it was always `python -m vad_stt_worker.main`,
    # then `pgrep -f "vad_stt_worker.main"` would be better.
}

# Stop FastAPI Gateway (app)
# Uvicorn is typically used for FastAPI. The pattern above should catch it if `app.main:app` is in the cmd.
stop_service "fastapi_gateway" "app"

# Stop VAD & STT Worker
stop_service "vad_stt_worker" "vad_stt_worker"

# Stop LLM Orchestrator
stop_service "llm_orchestrator" "llm_orchestrator"

# Stop TTS Service
stop_service "tts_service" "tts_service"

echo ""
echo "Service shutdown attempt complete."
echo "Please verify manually if all processes have been terminated (e.g., using 'ps aux | grep python' or 'ps aux | grep uvicorn')." 