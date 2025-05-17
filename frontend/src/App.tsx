import './App.css';
import useAppStore from './store/useAppStore';
import useWebSocket, { type ServerMessage } from './hooks/useWebSocket';
import useAudioStreamer from './hooks/useAudioStreamer';
import useStreamedAudioPlayer from './hooks/useStreamedAudioPlayer';
import { useEffect, useCallback, useState } from 'react';

// Import Components
import FuturisticAnimation from './components/FuturisticAnimation';
import ChatDisplay from './components/ChatDisplay';

// TODO: Move to a config file or environment variable
const WEBSOCKET_URL = (window as any).APP_CONFIG?.VITE_API_BASE_URL || import.meta.env.VITE_API_BASE_URL || '/v1/ws/audio';
console.log('WEBSOCKET_URL', WEBSOCKET_URL);

function App() {
  // 1. Zustand store selectors
  const {
    partialTranscript,
    chatMessages,
    setPartialTranscript,
    addChatMessage,
    startAssistantMessage,
    appendContentToCurrentAssistantMessage,
    clearCurrentAssistantMessageId,
    clearChat,
    setIsPlayingAudio,
    setAudioPlaybackError,
    selectedMicId,
    setActiveConversationId,
  } = useAppStore();

  // 2. useState for local component state
  const [currentAudioLevel, setCurrentAudioLevel] = useState(0);

  // 3. Custom hooks providing core functionalities (audio streaming, playback)
  // These need to be before callbacks that use their returned functions.
  // Note: isConnected and sendAudioChunk from useWebSocket are used by useAudioStreamer.
  // This creates a slight ordering challenge if useWebSocket also needs callbacks defined after these.
  // We will define callbacks, then useWebSocket, then useAudioStreamer will use sendAudioChunk from it.

  const {
    startAudioStream,
    enqueueAudioChunk,
    endAudioStream,
    stopAudioPlayback,
    isPlaying: isStreamedAudioPlaying,
    playbackAudioLevel,
    error: streamedAudioError,
  } = useStreamedAudioPlayer();

  // 4. Callback definitions (useCallback)
  // These are passed to useWebSocket, so they need to be defined before it.
  // They also use functions from useStreamedAudioPlayer and useAppStore.

  const onConnectCallback = useCallback(() => {
    console.log('App: WebSocket Connected');
  }, []);

  const onDisconnectCallback = useCallback((event: CloseEvent) => {
    console.log('App: WebSocket Disconnected', event.reason);
    stopAudioPlayback(); 
  }, [stopAudioPlayback]);

  const onErrorCallback = useCallback((event: Event) => {
    console.error('App: WebSocket Error', event);
    stopAudioPlayback(); 
  }, [stopAudioPlayback]);

  const handleWebSocketMessage = useCallback((message: ServerMessage) => {
    console.log('App: Received WebSocket message:', message);
    const currentConvId = useAppStore.getState().activeConversationId;
    const storeActions = useAppStore.getState();

    switch (message.type) {
      case 'system_event': 
        if (message.event === 'conversation_started' && message.conversation_id) {
          storeActions.setActiveConversationId(message.conversation_id);
          console.log('App: Conversation started with ID:', message.conversation_id);
          storeActions.clearChat(); 
          stopAudioPlayback();
        }
        break;
      case 'partial_transcript':
        storeActions.setPartialTranscript(message.text);
        break;
      case 'final_transcript':
        storeActions.addChatMessage({ type: 'user', content: message.transcript });
        storeActions.clearCurrentAssistantMessageId();
        break;
      case 'token':
        if (!useAppStore.getState().currentAssistantMessageId) {
            storeActions.startAssistantMessage();
        }
        storeActions.appendContentToCurrentAssistantMessage(message.content);
        break;
      case 'tool':
        storeActions.addChatMessage({ type: 'tool_status', content: `${message.name}: ${message.status}` });
        break;
      case 'user_interrupted':
        console.log('App: User interrupted signal received:', message);
        if (message.conversation_id === currentConvId) {
            stopAudioPlayback();
            storeActions.clearCurrentAssistantMessageId();
        }
        break;
      case 'audio_stream_start':
        console.log('App: Audio stream START received for assistant:', message);
        if (message.conversation_id === currentConvId) {
            if (!useAppStore.getState().currentAssistantMessageId) {
                storeActions.startAssistantMessage(); 
            }
            startAudioStream(message.sample_rate, message.channels);
        }
        break;
      case 'raw_audio_chunk':
        if (message.conversation_id === currentConvId) {
            enqueueAudioChunk(message.data);
        }
        break;
      case 'audio_stream_end':
        console.log('App: Audio stream END received for assistant:', message);
        if (message.conversation_id === currentConvId) {
            endAudioStream();
            storeActions.clearCurrentAssistantMessageId();
        }
        break;
      case 'audio_stream_error':
        console.error('App: Audio stream ERROR received:', message);
        if (message.conversation_id === currentConvId) {
            stopAudioPlayback();
            storeActions.setAudioPlaybackError(message.error); 
            storeActions.clearCurrentAssistantMessageId();
        }
        break;
      case 'barge_in_notification':
        console.log('App: Barge-in notification received:', message);
        if (message.conversation_id === currentConvId) {
            stopAudioPlayback();
            storeActions.clearCurrentAssistantMessageId();
            console.log('App: Audio playback stopped due to barge-in notification.');
        }
        break;
      default:
        console.warn('App: Unknown message type received:', message);
    }
  }, [
    stopAudioPlayback, startAudioStream, enqueueAudioChunk, endAudioStream, 
    setActiveConversationId, setPartialTranscript, addChatMessage, startAssistantMessage, 
    appendContentToCurrentAssistantMessage, clearCurrentAssistantMessageId, setAudioPlaybackError,
    clearChat
  ]);

  // 5. WebSocket hook - now uses the defined callbacks
  const { 
    isConnected, 
    sendAudioChunk,
  } = useWebSocket({
    url: WEBSOCKET_URL,
    onMessage: handleWebSocketMessage,
    onConnect: onConnectCallback,
    onDisconnect: onDisconnectCallback,
    onError: onErrorCallback
  });

  // 6. AudioStreamer hook - uses sendAudioChunk and isConnected from useWebSocket
  const {
    startStreaming,
    stopStreaming,
    isRecording: isStreamingAudio,
    micAudioLevel,
  } = useAudioStreamer({
    onAudioChunk: (chunk: ArrayBuffer) => {
      if (isConnected && chunk.byteLength > 0) {
        sendAudioChunk(chunk);
      } else if (!isConnected) {
        // console.warn('WebSocket not connected. Audio chunk not sent.');
      }
    },
    onError: (error: Error) => {
        console.error("Audio Streamer Error in App:", error.message);
    },
    deviceId: selectedMicId,
  });

  // 7. useEffect hooks
  useEffect(() => {
    // Combine mic and playback audio levels
    const newLevel = Math.max(micAudioLevel || 0, playbackAudioLevel || 0);
    setCurrentAudioLevel(newLevel);
  }, [micAudioLevel, playbackAudioLevel]);

  useEffect(() => {
    if (streamedAudioError) {
      setAudioPlaybackError(streamedAudioError);
    }
  }, [streamedAudioError, setAudioPlaybackError]);

  useEffect(() => {
    setIsPlayingAudio(isStreamedAudioPlaying);
  }, [isStreamedAudioPlaying, setIsPlayingAudio]);
  
  // 8. Event handlers for UI elements
  const toggleRecording = () => {
    if (isStreamingAudio) {
      stopStreaming(); 
    } else {
      clearChat(); 
      useAppStore.getState().resetAudioPlaybackProgress();
      stopAudioPlayback(); 
      startStreaming(); 
    }
  };

  // 9. Render logic (JSX)
  return (
    <div className="app-container">

      <div className="main-content-area">
        <div className="animation-container">
          <FuturisticAnimation audioLevel={currentAudioLevel} statusText={isConnected ? 'ONLINE' : 'OFFLINE'} mainText="TARA"/>
        </div>

        <div className="controls-section">
          <button 
            onClick={toggleRecording} 
            disabled={!isConnected && !isStreamingAudio}
            className="futuristic-button"
          >
            {isStreamingAudio ? 'STOP SESSION' : 'START SESSION'}
          </button>
        </div>
        {!isConnected && !isStreamingAudio && 
            <p className="text-error mt-1" style={{textAlign: 'center'}}>SYSTEM OFFLINE. CANNOT START SESSION.</p>}

        <div className="chat-area-container">
          <ChatDisplay messages={chatMessages} partialTranscript={partialTranscript} />
        </div>
      </div>
    </div>
  );
}

export default App;
