import { useEffect, useRef, useState, useCallback } from 'react';

// Define the types for messages based on Requirements.md
interface PartialTranscriptMessage {
  type: "partial_transcript";
  text: string;
  timestamp: number;
}

interface FinalTranscriptMessage {
  type: "final_transcript";
  text: string;
  timestamp: number; 
}

interface LlmTokenMessage {
  type: "token";
  role: "assistant";
  content: string;
  conversation_id: string; // Added based on backend structure
}

interface ToolStatusMessage {
  type: "tool";
  name: string;
  status: "running" | "completed" | "error" | "failed"; // Added "failed"
  conversation_id: string; // Added based on backend structure
  tool_id?: string; // Optional, from backend
  result?: any; // Optional, from backend
}

// This will be deprecated by audio_stream_start, raw_audio_chunk, audio_stream_end
interface AudioPlaybackMessageObsolete {
  type: "audio"; // Kept for now to avoid breaking App.tsx immediately, but should be removed
  url: string; 
  end: boolean;
}

interface UserInterruptedMessage {
  type: "user_interrupted";
  conversation_id: string; 
  timestamp: number;
}

// New messages for native WebSocket audio streaming
export interface AudioStreamStartMessage {
  type: "audio_stream_start";
  conversation_id: string;
  sample_rate: number;
  channels: number;
  sample_width: number;
}

export interface RawAudioChunkMessage {
  type: "raw_audio_chunk";
  data: ArrayBuffer;
  conversation_id: string; // Potentially useful, though WS context implies it
}

export interface AudioStreamEndMessage {
  type: "audio_stream_end";
  conversation_id: string;
  chunk_count?: number;
}

export interface AudioStreamErrorMessage {
  type: "audio_stream_error";
  conversation_id: string;
  error: string;
}

// Message from client to server (for STT start/stop controls, etc.)
// Example, not fully implemented yet
// interface ClientControlMessage {
//   type: "control";
//   command: "start_stt" | "stop_stt";
//   conversation_id: string;
// }

// System event from server upon connection
export interface SystemEventMessage {
  type: "system_event";
  event: string; // e.g., "conversation_started"
  conversation_id: string;
}

export type ServerMessage = 
  | PartialTranscriptMessage 
  | FinalTranscriptMessage 
  | LlmTokenMessage 
  | ToolStatusMessage 
  | AudioPlaybackMessageObsolete // To be removed
  | UserInterruptedMessage
  | AudioStreamStartMessage
  | RawAudioChunkMessage
  | AudioStreamEndMessage
  | AudioStreamErrorMessage
  | SystemEventMessage;

interface UseWebSocketOptions {
  url: string;
  onMessage: (message: ServerMessage) => void;
  onConnect?: () => void;
  onDisconnect?: (event: CloseEvent) => void;
  onError?: (event: Event) => void;
}

const useWebSocket = ({ url, onMessage, onConnect, onDisconnect, onError }: UseWebSocketOptions) => {
  const socketRef = useRef<WebSocket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [attemptReconnect, setAttemptReconnect] = useState(true);
  const reconnectIntervalRef = useRef<number | null>(null);

  // Ref to hold the current value of attemptReconnect for use in callbacks
  const attemptReconnectRef = useRef(attemptReconnect);
  useEffect(() => {
    attemptReconnectRef.current = attemptReconnect;
  }, [attemptReconnect]);

  const connect = useCallback(() => {
    if (!url || (socketRef.current && socketRef.current.readyState === WebSocket.OPEN)) {
      return;
    }

    console.log(`Attempting to connect WebSocket to ${url}...`);
    const socket = new WebSocket(url);
    socket.binaryType = 'arraybuffer'; 
    socketRef.current = socket;

    socket.onopen = () => {
      console.log('WebSocket connected');
      setIsConnected(true);
      setAttemptReconnect(true); // Reset for next potential disconnect
      if (reconnectIntervalRef.current) {
        clearInterval(reconnectIntervalRef.current);
        reconnectIntervalRef.current = null;
      }
      onConnect?.();
    };

    socket.onclose = (event: CloseEvent) => {
      console.log(`WebSocket disconnected: Code=${event.code}, Reason='${event.reason}', Clean=${event.wasClean}`);
      setIsConnected(false);
      onDisconnect?.(event);
      // Use the ref here to get the latest value of attemptReconnect
      if (attemptReconnectRef.current && event.code !== 1000) { // 1000 is normal closure
        if (!reconnectIntervalRef.current) {
            reconnectIntervalRef.current = window.setInterval(() => {
                console.log('Attempting to reconnect WebSocket...');
                // Call connect directly - it's stable now regarding attemptReconnect state changes
                // that happen within its own lifecycle (like in onopen).
                connect(); 
            }, 5000); // Attempt to reconnect every 5 seconds
        }
      } else if (event.code === 1000) {
        console.log('WebSocket closed normally, not attempting reconnect.');
      }
    };

    socket.onerror = (event: Event) => {
      console.error('WebSocket error:', event);
      onError?.(event);
    };

    socket.onmessage = (event: MessageEvent) => {
      if (event.data instanceof ArrayBuffer) {
        const currentConversationId = useAppStore.getState().activeConversationId;
        onMessage({ 
            type: "raw_audio_chunk", 
            data: event.data, 
            conversation_id: currentConversationId || "unknown"
        } as RawAudioChunkMessage);
      } else if (typeof event.data === 'string') {
        try {
          const parsedMessage = JSON.parse(event.data) as ServerMessage;
          onMessage(parsedMessage);
        } catch (e) {
          console.error('Failed to parse JSON message from WebSocket:', event.data, e);
        }
      } else {
        console.warn('Received WebSocket message of unknown type:', typeof event.data, event.data);
      }
    };
  // Removed `attemptReconnect` from this dependency array
  }, [url, onMessage, onConnect, onDisconnect, onError]);

  useEffect(() => {
    connect(); // Call the connect function which is now more stable
    return () => {
      console.log('Cleaning up WebSocket connection hook...');
      // This ensures that if the component unmounts, we intend to stop reconnecting.
      setAttemptReconnect(false); 
      // attemptReconnectRef.current will be updated by the other useEffect

      if (reconnectIntervalRef.current) {
        clearInterval(reconnectIntervalRef.current);
        reconnectIntervalRef.current = null;
      }
      if (socketRef.current) {
        console.log('Closing WebSocket connection from useEffect cleanup.');
        // The reason "Component unmounting" is accurate when this cleanup is due to unmount.
        socketRef.current.close(1000, "Component unmounting"); 
        socketRef.current = null;
      }
    };
  // `connect` is now more stable regarding internal state changes like `attemptReconnect`
  }, [connect]);

  const sendData = (data: string | ArrayBuffer) => {
    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
      socketRef.current.send(data);
    } else {
      console.warn('WebSocket is not connected. Message not sent.');
    }
  };

  const sendJsonMessage = (message: object) => {
    sendData(JSON.stringify(message));
  };

  const sendAudioChunk = (chunk: ArrayBuffer) => {
    sendData(chunk);
  };

  const closeWebSocket = (code = 1000, reason = "User requested close") => {
    setAttemptReconnect(false); 
    if (reconnectIntervalRef.current) {
        clearInterval(reconnectIntervalRef.current);
        reconnectIntervalRef.current = null;
    }
    if (socketRef.current) {
      socketRef.current.close(code, reason);
    }
  };

  return { isConnected, sendJsonMessage, sendAudioChunk, closeWebSocket, connectWebSocket: connect };
};

// Need to import useAppStore if accessing it here, or pass conversation_id some other way.
// For the RawAudioChunkMessage, this is a temporary solution for conversation_id.
// This should ideally be handled more robustly, perhaps by App.tsx providing the current conv_id.
import useAppStore from '../store/useAppStore'; 

export default useWebSocket; 