#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Define image names and tags
API_IMAGE_NAME="spt-assistant-api"
VAD_STT_IMAGE_NAME="spt-assistant-vad-stt"
LLM_ORCHESTRATOR_IMAGE_NAME="spt-assistant-llm-orchestrator"
TTS_IMAGE_NAME="spt-assistant-tts"
IMAGE_TAG="latest"
GIT_VERSION=$(git rev-parse --short HEAD)


(cd frontend && npm run build)

# --- Build API Service Image (including Frontend) ---
echo "Building API service image: ${API_IMAGE_NAME}:${GIT_VERSION}..."
docker build -t "${API_IMAGE_NAME}:${GIT_VERSION}" --platform linux/amd64 -f Dockerfile.api .
echo "API service image built successfully."

# --- Build VAD-STT Worker Image ---
echo "Building VAD-STT worker image: ${VAD_STT_IMAGE_NAME}:${GIT_VERSION}..."
docker build -t "${VAD_STT_IMAGE_NAME}:${GIT_VERSION}" --platform linux/amd64 -f Dockerfile.vad_stt .
echo "VAD-STT worker image built successfully."

# --- Build LLM Orchestrator Worker Image ---
echo "Building LLM Orchestrator worker image: ${LLM_ORCHESTRATOR_IMAGE_NAME}:${GIT_VERSION}..."
docker build -t "${LLM_ORCHESTRATOR_IMAGE_NAME}:${GIT_VERSION}" --platform linux/amd64 -f Dockerfile.llm_orchestrator .
echo "LLM Orchestrator worker image built successfully."

# --- Build TTS Worker Image ---
echo "Building TTS worker image: ${TTS_IMAGE_NAME}:${GIT_VERSION}..."
docker build -t "${TTS_IMAGE_NAME}:${GIT_VERSION}" --platform linux/amd64 -f Dockerfile.tts .
echo "TTS worker image built successfully."


echo "Pushing production Docker images to registry.sponge-theory.dev"
docker tag "${API_IMAGE_NAME}:${GIT_VERSION}" registry.sponge-theory.dev/spt-assistant-api:${IMAGE_TAG}
docker tag "${VAD_STT_IMAGE_NAME}:${GIT_VERSION}" registry.sponge-theory.dev/spt-assistant-vad-stt:${IMAGE_TAG}
docker tag "${LLM_ORCHESTRATOR_IMAGE_NAME}:${GIT_VERSION}" registry.sponge-theory.dev/spt-assistant-llm-orchestrator:${IMAGE_TAG}
docker tag "${TTS_IMAGE_NAME}:${GIT_VERSION}" registry.sponge-theory.dev/spt-assistant-tts:${IMAGE_TAG}

docker push registry.sponge-theory.dev/spt-assistant-api:${IMAGE_TAG}
docker push registry.sponge-theory.dev/spt-assistant-vad-stt:${IMAGE_TAG}
docker push registry.sponge-theory.dev/spt-assistant-llm-orchestrator:${IMAGE_TAG}
docker push registry.sponge-theory.dev/spt-assistant-tts:${IMAGE_TAG}

echo "Production Docker images pushed to registry.sponge-theory.dev/spt-assistant:${IMAGE_TAG}"
echo "Triggering deployment to Portainer..."
curl -X POST https://portainer.sponge-theory.dev/api/stacks/webhooks/df302c15-c3ab-4a31-95fe-6d4985fda263

echo "
All Docker images built and pushed successfully:
- ${API_IMAGE_NAME}:${IMAGE_TAG}
- ${VAD_STT_IMAGE_NAME}:${IMAGE_TAG}
- ${LLM_ORCHESTRATOR_IMAGE_NAME}:${IMAGE_TAG}
- ${TTS_IMAGE_NAME}:${IMAGE_TAG}
" 