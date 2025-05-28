# Connection Disconnect Notification System

## Overview

This document describes the implementation of a connection disconnect notification system that ensures all workers (VAD/STT, LLM Orchestrator, TTS) are aware when WebSocket connections are closed and can properly clean up their resources.

## Problem Statement

Previously, when a WebSocket connection was closed (due to client disconnect, network issues, or server errors), the workers would continue processing requests for that conversation ID, leading to:

- Resource leaks (audio processors, TTS queues, LLM generation tasks)
- Unnecessary processing for disconnected clients
- Potential memory and CPU waste
- Inconsistent state across workers

## Solution Architecture

### 1. Connection Events Channel

A new Redis pub/sub channel `connection_events` is used to broadcast connection lifecycle events to all workers.

**Channel Configuration:**
- **API Gateway**: `CONNECTION_EVENTS_CHANNEL = "connection_events"`
- **VAD/STT Worker**: `CONNECTION_EVENTS_CHANNEL = "connection_events"`
- **LLM Orchestrator**: `CONNECTION_EVENTS_CHANNEL = "connection_events"`
- **TTS Worker**: `CONNECTION_EVENTS_CHANNEL = "connection_events"`

### 2. Message Format

Connection disconnect events use the following JSON format:

```json
{
  "type": "connection_disconnected",
  "conversation_id": "uuid-string",
  "timestamp_ms": 1234567890123,
  "reason": "client_disconnect" | "server_error" | "timeout"
}
```

**Fields:**
- `type`: Always "connection_disconnected" for disconnect events
- `conversation_id`: The unique conversation identifier
- `timestamp_ms`: Unix timestamp in milliseconds when disconnect occurred
- `reason`: Reason for disconnect (client_disconnect, server_error, timeout)

## Implementation Details

### 3. API Gateway Changes

**File**: `app/api/v1/endpoints/audio.py`

**New Function**: `publish_connection_disconnect_event()`
- Publishes disconnect events to the connection events channel
- Called from all WebSocket cleanup scenarios
- Includes proper error handling and logging

**Integration Points:**
- WebSocket connection cleanup in `websocket_audio_endpoint()`
- Early disconnect scenarios (before main loop)
- Exception handling in WebSocket endpoint
- Normal connection termination

### 4. VAD/STT Worker Changes

**File**: `vad_stt_worker/main.py`

**New Function**: `handle_connection_disconnect_event()`
- Cleans up audio processors for disconnected conversations
- Removes conversation from active processors dictionary
- Logs cleanup actions for monitoring

**New Function**: `subscribe_to_connection_events()`
- Subscribes to connection events channel
- Processes disconnect events asynchronously
- Integrated into main worker loop

**Resource Cleanup:**
- Removes `AudioProcessor` instances from `active_processors`
- Cleans up `last_activity_time` tracking
- Calls processor `close()` method for proper cleanup

### 5. LLM Orchestrator Worker Changes

**File**: `llm_orchestrator_worker/main.py`

**New Function**: `handle_connection_disconnect_event()`
- Cancels active LLM generation for disconnected conversations
- Sends TTS stop commands to prevent orphaned TTS processing
- Optionally cleans up conversation data (currently preserves for reconnection)

**New Function**: `subscribe_to_connection_events()`
- Subscribes to connection events channel
- Processes disconnect events asynchronously
- Integrated into main worker loop with other subscriptions

**Resource Cleanup:**
- Calls `llm_service.cancel_generation(conversation_id)`
- Publishes TTS stop command via `TTS_CONTROL_CHANNEL`
- Preserves conversation history for potential reconnection

### 6. TTS Worker Changes

**File**: `tts_worker/main.py`

**New Function**: `handle_connection_disconnect_event()`
- Cancels active TTS processor tasks for disconnected conversations
- Clears pending TTS requests from conversation queues
- Removes TTS active state from Redis

**New Function**: `subscribe_to_connection_events()`
- Subscribes to connection events channel
- Processes disconnect events asynchronously
- Integrated into main worker loop

**Resource Cleanup:**
- Cancels tasks in `active_tts_processors`
- Clears queues in `tts_request_queues`
- Calls `set_tts_active_state_for_conversation(conversation_id, redis_client, False)`

## Configuration Updates

### 7. Configuration Files Updated

All worker configuration files now include the connection events channel:

**Files Updated:**
- `app/core/config.py`
- `vad_stt_worker/config.py`
- `llm_orchestrator_worker/config.py`
- `tts_worker/config.py`

**New Setting:**
```python
CONNECTION_EVENTS_CHANNEL: str = "connection_events"
```

## Testing

### 8. Test Implementation

**File**: `test_connection_disconnect.py`

A comprehensive test script that:
1. Simulates connection activity across all workers
2. Publishes a connection disconnect event
3. Verifies resource cleanup in each worker
4. Monitors for unexpected messages after disconnect
5. Reports overall system health

**Test Scenarios:**
- Audio processing cleanup (VAD/STT)
- LLM generation cancellation (LLM Orchestrator)
- TTS processing cleanup (TTS Worker)
- Redis state cleanup verification
- No orphaned message detection

## Benefits

### 9. System Improvements

**Resource Management:**
- Prevents memory leaks from orphaned processors
- Reduces CPU usage from unnecessary processing
- Ensures consistent state across all workers

**Reliability:**
- Graceful handling of connection failures
- Proper cleanup on client disconnects
- Reduced risk of resource exhaustion

**Monitoring:**
- Clear logging of disconnect events and cleanup actions
- Ability to track resource cleanup success/failure
- Better observability of connection lifecycle

**Scalability:**
- Efficient resource utilization
- Prevents accumulation of stale resources
- Better handling of high connection churn

## Error Handling

### 10. Robust Error Management

**Redis Connection Errors:**
- Graceful handling of Redis publish failures
- Retry logic in subscription loops
- Fallback cleanup mechanisms

**Worker-Specific Errors:**
- Safe cleanup even if some operations fail
- Comprehensive error logging
- Continuation of service despite individual failures

**Edge Cases:**
- Multiple disconnect events for same conversation
- Disconnect events for non-existent conversations
- Cleanup during worker shutdown

## Future Enhancements

### 11. Potential Improvements

**Connection Reconnection:**
- Support for connection reconnection with state restoration
- Conversation state persistence and recovery
- Client reconnection detection

**Advanced Monitoring:**
- Metrics for disconnect event processing
- Resource cleanup success rates
- Performance impact monitoring

**Configuration Options:**
- Configurable cleanup timeouts
- Selective resource preservation policies
- Custom disconnect reason handling

## Conclusion

The connection disconnect notification system provides a robust, scalable solution for managing WebSocket connection lifecycles across all workers. It ensures proper resource cleanup, prevents memory leaks, and maintains system reliability even under high connection churn scenarios.

The implementation follows the existing architectural patterns, uses the established Redis pub/sub infrastructure, and maintains backward compatibility while adding essential resource management capabilities. 