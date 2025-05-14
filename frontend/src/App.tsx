import './App.css';
import useAppStore from './store/useAppStore';
import useWebSocket, { type ServerMessage } from './hooks/useWebSocket';
import useAudioStreamer from './hooks/useAudioStreamer';
import useStreamedAudioPlayer from './hooks/useStreamedAudioPlayer';
import { useEffect, useCallback } from 'react';

// Import Components
import WaveformDisplay from './components/WaveformDisplay';
import TranscriptionDisplay from './components/TranscriptionDisplay';
import LlmResponseDisplay from './components/LlmResponseDisplay';
import PlaybackControls from './components/PlaybackControls';
import SettingsPanel from './components/SettingsPanel';

// TODO: Move to a config file or environment variable
const WEBSOCKET_URL = 'ws://localhost:8000/v1/ws/audio';

function App() {
  const {
    partialTranscript,
    finalTranscript,
    llmResponse,
    toolStatus,
    setPartialTranscript,
    appendFinalTranscript,
    appendLlmResponse,
    setToolStatus,
    setCurrentAudioUrl,
    setIsPlayingAudio,
    setAudioPlaybackError,
    selectedMicId,
    setActiveConversationId,
  } = useAppStore();

  const {
    startAudioStream,
    enqueueAudioChunk,
    endAudioStream,
    stopAudioPlayback,
    isPlaying: isStreamedAudioPlaying,
    error: streamedAudioError,
  } = useStreamedAudioPlayer();

  useEffect(() => {
    if (streamedAudioError) {
      setAudioPlaybackError(streamedAudioError);
    }
  }, [streamedAudioError, setAudioPlaybackError]);

  useEffect(() => {
    setIsPlayingAudio(isStreamedAudioPlaying);
  }, [isStreamedAudioPlaying, setIsPlayingAudio]);

  const handleWebSocketMessage = useCallback((message: ServerMessage) => {
    console.log('App: Received WebSocket message:', message);
    const currentConvId = useAppStore.getState().activeConversationId;

    switch (message.type) {
      case 'system_event': 
        if (message.event === 'conversation_started' && message.conversation_id) {
          setActiveConversationId(message.conversation_id);
          console.log('App: Conversation started with ID:', message.conversation_id);
          stopAudioPlayback();
        }
        break;
      case 'partial_transcript':
        setPartialTranscript(message.text);
        break;
      case 'final_transcript':
        appendFinalTranscript(message.text);
        break;
      case 'token':
        appendLlmResponse(message.content);
        break;
      case 'tool':
        setToolStatus(`${message.name}: ${message.status}`);
        break;
      case 'audio':
        console.log('App: Audio message (URL-based - DEPRECATED) received:', message.url, 'End:', message.end);
        stopAudioPlayback();
        if (message.url) {
          setCurrentAudioUrl(message.url);
        } else {
          setCurrentAudioUrl(null);
        }
        break;
      case 'user_interrupted':
        console.log('App: User interrupted (barge-in) signal received:', message);
        if (message.conversation_id === currentConvId) {
            stopAudioPlayback();
        }
        setCurrentAudioUrl(null);
        break;
      case 'audio_stream_start':
        console.log('App: Audio stream START received:', message);
        if (message.conversation_id === currentConvId) {
            startAudioStream(message.sample_rate, message.channels);
        }
        setCurrentAudioUrl(null);
        break;
      case 'raw_audio_chunk':
        if (message.conversation_id === currentConvId) {
            enqueueAudioChunk(message.data);
        }
        break;
      case 'audio_stream_end':
        console.log('App: Audio stream END received:', message);
        if (message.conversation_id === currentConvId) {
            endAudioStream();
        }
        break;
      case 'audio_stream_error':
        console.error('App: Audio stream ERROR received:', message);
        if (message.conversation_id === currentConvId) {
            stopAudioPlayback();
            setAudioPlaybackError(message.error); 
        }
        break;
      default:
        console.warn('App: Unknown message type received:', message);
    }
  }, [
    setActiveConversationId, 
    stopAudioPlayback, 
    setPartialTranscript, 
    appendFinalTranscript, 
    appendLlmResponse, 
    setToolStatus, 
    setCurrentAudioUrl, 
    startAudioStream, 
    enqueueAudioChunk, 
    endAudioStream, 
    setAudioPlaybackError
  ]);

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

  const handleAudioError = (error: Error) => {
    console.error("Audio Streamer Error in App:", error.message);
  };

  const {
    startStreaming,
    stopStreaming,
    isRecording: isStreamingAudio
  } = useAudioStreamer({
    onAudioChunk: (chunk: ArrayBuffer) => {
      if (isConnected && chunk.byteLength > 0) {
        console.log(`Sending audio chunk: ${chunk.byteLength} bytes`);
        sendAudioChunk(chunk);
      } else if (!isConnected) {
        console.warn('WebSocket not connected. Audio chunk not sent.');
      }
    },
    onError: handleAudioError,
    deviceId: selectedMicId,
  });
  
  const toggleRecording = () => {
    if (isStreamingAudio) {
      stopStreaming();
    } else {
      setPartialTranscript('');
      appendFinalTranscript('');
      useAppStore.getState().setLlmResponse('');
      useAppStore.getState().setToolStatus('');
      useAppStore.getState().resetAudioPlaybackProgress();
      startStreaming();
    }
  };

  return (
    <div className="app-container">
      <header className="app-header">
        <h1>Voice Assistant UI</h1>
        <p>Real-time Speech Processing Interface</p>
        <p className={isConnected ? 'text-success' : 'text-error'}>
          WebSocket: {isConnected ? 'Connected' : 'Disconnected'}
        </p>
        <p>
          Streamed TTS Playing: {isStreamedAudioPlaying ? 'Yes' : 'No'}
          {streamedAudioError && <span style={{color: 'red'}}> Error: {streamedAudioError}</span>}
        </p>
      </header>

      <div className="main-layout">
        <aside className="left-panel">
          <div className="panel-section">
            <h3>Controls &amp; Input</h3>
            <WaveformDisplay />
            <button onClick={toggleRecording} disabled={!isConnected && !isStreamingAudio} className="mt-1">
              {isStreamingAudio ? 'Stop Recording' : 'Start Recording'}
            </button>
            {!isConnected && !isStreamingAudio && 
              <p className="text-error mt-1">Connect to WebSocket to enable recording.</p>}
          </div>
          
          <div className="panel-section">
            <SettingsPanel />
          </div>
        </aside>

        <main className="right-panel">
          <div className="panel-section">
            <h3>Transcription</h3>
            <TranscriptionDisplay partialTranscript={partialTranscript} finalTranscript={finalTranscript} />
          </div>
          
          <div className="panel-section">
            <h3>Assistant Response</h3>
            <LlmResponseDisplay llmResponse={llmResponse} toolStatus={toolStatus} />
          </div>

          <div className="panel-section playback-controls">
            <PlaybackControls />
          </div>
        </main>
      </div>
    </div>
  );
}

export default App;
