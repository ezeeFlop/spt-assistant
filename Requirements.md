# Voice Assistant Platform – Requirements

## 1. Purpose

Design and implement a **real‑time, French‑first voice assistant** capable of two‑way spoken interaction, tool execution through an MCP client, and a modern web front‑end. The stack must remain **100 % open‑source for all audio components** (STT, VAD, TTS) while allowing any LLM (open or proprietary) to supply language understanding.

## 2. Scope

* Multimodal voice interface (microphone ↔ speaker) with sub‑second latency.
* Runs fully offline for audio processing; only the LLM may call external APIs.
* Single‑user MVP, but architecture must scale to multi‑user / multi‑session in the future.

## 3. Functional Requirements

|  FR‑ID  | Description                                                                                                                                                    |
| ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
|  FR‑01  | Capture microphone audio in the browser, stream to backend over **WebSocket** in 16‑kHz PCM chunks.                                                            |
|  FR‑02  | **Voice Activity Detection (VAD)** via Silero or WebRTC VAD to gate STT and support barge‑in.                                                                  |
|  FR‑03  | **Streaming STT** using `faster‑whisper` with **`openai/whisper‑large‑v3` French fine‑tune**. Must emit partial transcripts every ≤ 300 ms.                    |
|  FR‑04  | **Barge‑in / interruption**: when user speaks while TTS is playing, detect VAD > 150 ms, fade/stop playback, cancel current LLM turn, and restart pipeline.    |
|  FR‑05  | **LLM orchestration**: send transcript + conversation context to selected LLM; stream tokens back.                                                             |
|  FR‑06  | **Tool calls**: parse LLM JSON tool messages; dispatch via **MCP client library**; return results to LLM.                                                      |
|  FR‑07  | **Streaming TTS** in French with < 220 ms end‑to‑end lag using **Piper (fr‑siwis / fr‑gilles)** by default; allow plug‑ins for Coqui‑TTS, Parler‑TTS, or XTTS. |
|  FR‑08  | Web UI shows live waveform, partial ASR, final transcript, LLM tokens, tool status, and a playback progress bar.                                               |
|  FR‑09  | **Settings panel** to switch voices, microphone, VAD aggressiveness, and LLM endpoint.                                                                         |
|  FR‑10  | Provide REST+WebSocket API docs via OpenAPI/Swagger.                                                                                                           |

## 4. Non‑Functional Requirements

* **Latency**: ≤ 700 ms user‑speech‑to‑assistant‑speech (95th percentile).
* **WER (French)**: ≤ 10 % on CommonVoice v15 test set.
* **Audio Quality**: MOS ≥ 4.0 for TTS.
* **Availability**: 99.5 % in production.
* **Security**: TLS 1.3 for all network traffic; JWT session auth.
* **Observability**: structured logs (JSON via `structlog`) + Prometheus metrics + OpenTelemetry traces.
* **Extensibility**: plug‑in architecture for models/tools, no hard LLM coupling.

## 5. System Architecture

```
Browser (Vite + React  TS) ──WS──▶  Gateway (FastAPI) ─▶  VAD & STT Service (Whisper)
                                           │
                                           ├─▶  LLM Orchestrator ──▶ LLM API
                                           │            ▲
                                           │            └─ Tool Router (MCP client)
                                           │
                                           └─▶  TTS Service (Piper)
                                                    ▲
Browser ◀── Audio Stream (Opus/PCM) ◀───────────────┘
```

* **FastAPI Gateway**: accepts WebSocket streams, pushes PCM to Redis pub/sub.
* **VAD & STT**: Python worker using Silero VAD + faster‑whisper; publishes partial/final transcripts.
* **LLM Orchestrator**: consumes transcript events, manages dialog state, tool calls, and TTS requests.
* **TTS Service**: Piper server with phoneme cache; returns 24‑kHz WAV frames for immediate playback.

*All services containerised; recommended orchestrator: Docker Compose (dev) → Kubernetes (prod).*

## 6. Technology Stack & Dependencies

| Layer        | Package                                  | Version (min) | Notes                                                              |
| ------------ | ---------------------------------------- | ------------- | ------------------------------------------------------------------ |
| **STT**      | `faster-whisper`                         | 1.0           | GPU + CPU builds; use `openai/whisper-large-v3-french` checkpoint. |
|              | `whisper-cpp`                            | 1.6           | Fallback CPU‑only build.                                           |
| **VAD**      | `silero-vad`                             | 0.4           | TorchScript model; 16‑kHz mono.                                    |
|              | `webrtcvad`                              | 2.0           | Lightweight alternative for low‑power devices.                     |
| **TTS**      | `piper-tts`                              | 1.2           | Default; ship `fr-siwis-medium` and `fr-gilles-high`.              |
|              | `TTS` (Coqui)                            | 0.22          | Optional high‑fidelity voices; requires CUDA.                      |
|              | `parler-tts`                             | 0.3           | Experimental multi‑speaker French.                                 |
| **Backend**  | Python 3.12                              |               |                                                                    |
|              | `fastapi`, `uvicorn[standard]`           | ≥ 0.111       | WebSocket & REST.                                                  |
|              | `websockets`                             | 12.x          | Raw WS client/server.                                              |
|              | `pydantic` v2                            | 2.x           | Strong typing + validation.                                        |
|              | `structlog`, `loguru`                    | latest        | Structured + coloured logs.                                        |
|              | `redis-py`                               | 5.x           | Low‑latency pub/sub.                                               |
| **Frontend** | Vite 5 + React 18 + TS 5                 |               |                                                                    |
|              | `@tanstack/react-query`                  | latest        | Data fetching/cache.                                               |
|              | `zustand`                                | latest        | State management.                                                  |
|              | `socket.io‑client` or `native WebSocket` | 4.x           | Streaming audio & events.                                          |
|              | `wavesurfer.js`                          | 7.x           | Waveform visualisation.                                            |

## 7. APIs

### 7.1 WebSocket `/ws/audio`

* **Client → Server** (binary Opus/PCM frames).
* **Server → Client** (JSON):

  ```jsonc
  { "type": "partial", "text": "Bonjour…", "timestamp": 123 }
  { "type": "final",   "text": "Bonjour, comment puis‑je t\u2019aider ?" }
  { "type": "token",   "role": "assistant", "content": "Sure…" }
  { "type": "tool",    "name": "weather.get", "status": "running" }
  { "type": "audio",   "url": "blob:uuid", "end": true }
  ```

### 7.2 REST

* `POST /v1/conversations/{id}/config` – change model, voice, VAD mode.
* `GET  /v1/health` – liveness & readiness.

## 8. Voice Interaction Logic

1. Browser streams audio.
2. VAD high threshold → send to STT.
3. STT partials fed to GUI + LLM.
4. LLM may emit a **`tool` function call**; orchestrator waits for MCP reply.
5. When interrupt VAD triggers during TTS playback, orchestrator cancels current turn and resets token stream.

## 9. Error Handling & Logging

* Raise custom `VoicePipelineError` with context; auto‑retry transient network errors (exponential back‑off, max 3 attempts).
* Log every pipeline step with trace‑id; integrate **OpenTelemetry** exporter (`otlp`) for distributed tracing.

## 10. Security

* Enforce **WSS**; deny mixed content.
* **JWT** access tokens; rotate signing key every 24 h.
* Optional **OPA** policy engine for fine‑grained tool access control.

## 11. Internationalisation

* Default locale **fr‑FR**; provide i18n keys for GUI strings.
* Support extra languages by dropping replacement Whisper/Piper models.

## 12. Performance Targets & Benchmarks

| Metric             | Target       | Tool                           |
| ------------------ | ------------ | ------------------------------ |
| End‑to‑end latency | ≤ 700 ms p95 | Locust + WebRTC audio fixtures |
| STT WER (fr)       | ≤ 10 %       | `asr-eval` on CommonVoice v15  |
| TTS MOS            | ≥ 4.0        | `piper-eval` crowdsourced ABX  |

## 13. Testing Strategy

* **Unit tests**: pytest + hypothesis (≥ 90 % cov).
* **Integration tests**: Docker‑Compose CI matrix; record/playback golden WAVs.
* **E2E**: Playwright tests for GUI; synthetic mic input via WebAudio API.

## 14. Deployment

* **Dev**: `docker compose up` with `.env` for model paths.
* **Prod**: Helm chart; GPU node‑pools for STT/TTS; autoscale on GPU utilisation.
* **CI/CD**: GitHub Actions – lint → test → build → push → deploy.

## 15. Licensing & Compliance

* Ensure model checkpoints are under Apache‑2.0, MIT, MPL‑2.0, or CC‑BY‑SA.
* Provide NOTICE file bundling third‑party licenses.

## 16. Glossary

* **VAD** – Voice Activity Detection
* **STT** – Speech To Text
* **TTS** – Text To Speech
* **MCP** – Multi‑Capability Protocol (internal tool dispatch)
