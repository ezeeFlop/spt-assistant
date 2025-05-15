#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Define image names and tags
API_IMAGE_NAME="voice-assistant-api"
VAD_STT_IMAGE_NAME="voice-assistant-vad-stt"
LLM_ORCHESTRATOR_IMAGE_NAME="voice-assistant-llm-orchestrator"
TTS_IMAGE_NAME="voice-assistant-tts"
IMAGE_TAG="latest"

# --- Build API Service Image (including Frontend) ---
echo "Building API service image: ${API_IMAGE_NAME}:${IMAGE_TAG}..."
docker build -t "${API_IMAGE_NAME}:${IMAGE_TAG}" -f Dockerfile.api .
echo "API service image built successfully."

# --- Build VAD-STT Worker Image ---
echo "Building VAD-STT worker image: ${VAD_STT_IMAGE_NAME}:${IMAGE_TAG}..."
docker build -t "${VAD_STT_IMAGE_NAME}:${IMAGE_TAG}" -f Dockerfile.vad_stt .
echo "VAD-STT worker image built successfully."

# --- Build LLM Orchestrator Worker Image ---
echo "Building LLM Orchestrator worker image: ${LLM_ORCHESTRATOR_IMAGE_NAME}:${IMAGE_TAG}..."
docker build -t "${LLM_ORCHESTRATOR_IMAGE_NAME}:${IMAGE_TAG}" -f Dockerfile.llm_orchestrator .
echo "LLM Orchestrator worker image built successfully."

# --- Build TTS Worker Image ---
echo "Building TTS worker image: ${TTS_IMAGE_NAME}:${IMAGE_TAG}..."
docker build -t "${TTS_IMAGE_NAME}:${IMAGE_TAG}" -f Dockerfile.tts .
echo "TTS worker image built successfully."

echo "
All Docker images built successfully:
- ${API_IMAGE_NAME}:${IMAGE_TAG}
- ${VAD_STT_IMAGE_NAME}:${IMAGE_TAG}
- ${LLM_ORCHESTRATOR_IMAGE_NAME}:${IMAGE_TAG}
- ${TTS_IMAGE_NAME}:${IMAGE_TAG}
" 