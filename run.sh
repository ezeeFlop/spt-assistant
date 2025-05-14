#!/bin/bash

# Script to run backend services for the Voice Assistant Platform

ROOT_DIR=$(pwd)
LOG_DIR="$ROOT_DIR/logs"
mkdir -p "$LOG_DIR"

# Define service commands and directories
# API (FastAPI Gateway)
API_CMD="uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
API_DIR="."

# TTS Service
TTS_CMD="uv run python main.py"
TTS_DIR="tts_worker"

# VAD & STT Worker
VAD_CMD="uv run python main.py"
VAD_DIR="vad_stt_worker"

# LLM Orchestrator
LLM_CMD="uv run python main.py"
LLM_DIR="llm_orchestrator_worker"

# Function to start a service in the background
start_service_background() {
    local service_name_display="$1" # For logging/display purposes
    local service_dir_relative="$2"
    local run_command="$3"
    local log_file="$LOG_DIR/${service_name_display// /_}.log" # Replace spaces for log file name

    echo "Starting $service_name_display in $ROOT_DIR/$service_dir_relative (background)..."
    cd "$ROOT_DIR/$service_dir_relative" || { echo "Failed to cd to $ROOT_DIR/$service_dir_relative for $service_name_display"; return 1; }
    
    if [[ "$run_command" == *"python main.py"* ]]; then
        nohup env PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}" $run_command > "$log_file" 2>&1 &
    else
        nohup $run_command > "$log_file" 2>&1 &
    fi
    
    pid=$!
    echo "$service_name_display started with PID $pid. Log: $log_file"
    cd "$ROOT_DIR" || exit
}

# Function to start a service in the foreground
start_service_foreground() {
    local service_name_display="$1" # For logging/display purposes
    local service_dir_relative="$2"
    local run_command="$3"

    echo "Starting $service_name_display in $ROOT_DIR/$service_dir_relative (foreground)..."
    cd "$ROOT_DIR/$service_dir_relative" || { echo "Failed to cd to $ROOT_DIR/$service_dir_relative for $service_name_display"; return 1; }
    
    # DIAGNOSTIC CHANGE FOR TTS:
    if [ "$service_name_display" == "TTS Service" ]; then
        echo "Attempting to activate .venv/bin/activate and run python main.py directly for TTS Service..."
        if [ -f ".venv/bin/activate" ]; then
            echo "Activating $(pwd)/.venv/bin/activate"
            source .venv/bin/activate
            echo "Running: PYTHONPATH=\"$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}\" python main.py"
            PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}" python main.py
            echo "Deactivating venv for TTS Service..."
            deactivate
        elif [ -f ".venv/Scripts/activate" ]; then # For Git Bash on Windows compatibility
            echo "Activating $(pwd)/.venv/Scripts/activate"
            source .venv/Scripts/activate
            echo "Running: PYTHONPATH=\"$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}\" python main.py"
            PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}" python main.py
            echo "Deactivating venv for TTS Service..."
            deactivate
        else
            echo "Error: .venv/bin/activate (or .venv/Scripts/activate) not found in $(pwd) for TTS Service."
            echo "Please ensure install.sh ran correctly and created the venv in ${service_dir_relative}"
        fi
    elif [[ "$run_command" == *"python main.py"* ]]; then
        PYTHONPATH="$ROOT_DIR${PYTHONPATH:+:$PYTHONPATH}" $run_command
    else
        $run_command
    fi
    
    echo "$service_name_display finished."
    cd "$ROOT_DIR" || exit
}

SERVICE_TO_RUN_ARG=$1

if [ -z "$SERVICE_TO_RUN_ARG" ]; then
    echo "Starting all services in background... Logs will be in $LOG_DIR"
    start_service_background "FastAPI Gateway" "$API_DIR" "$API_CMD"
    start_service_background "VAD STT Worker" "$VAD_DIR" "$VAD_CMD"
    start_service_background "LLM Orchestrator" "$LLM_DIR" "$LLM_CMD"
    start_service_background "TTS Service" "$TTS_DIR" "$TTS_CMD"
    
    echo ""
    echo "All services launched in the background."
    echo "To view logs, check the files in $LOG_DIR"
    echo "To stop services, use kill_all.sh or find their PIDs (e.g., using 'pgrep -f uvicorn' or 'pgrep -f python.*main.py') and then 'kill <PID>'."
else
    case $SERVICE_TO_RUN_ARG in
        api)
            start_service_foreground "FastAPI Gateway" "$API_DIR" "$API_CMD"
            ;;
        tts)
            start_service_foreground "TTS Service" "$TTS_DIR" "$TTS_CMD"
            ;;
        vad)
            start_service_foreground "VAD STT Worker" "$VAD_DIR" "$VAD_CMD"
            ;;
        llm)
            start_service_foreground "LLM Orchestrator" "$LLM_DIR" "$LLM_CMD"
            ;;
        *)
            echo "Error: Unknown service '$SERVICE_TO_RUN_ARG'"
            echo "Available services: api, tts, vad, llm"
            exit 1
            ;;
    esac
fi 