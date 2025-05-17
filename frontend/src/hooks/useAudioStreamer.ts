// frontend/src/hooks/useAudioStreamer.ts
import { useState, useRef, useCallback, useEffect } from 'react';
import useAppStore from '../store/useAppStore';
import PcmProcessorWorkerModuleURL from '../audio/pcm-processor.ts?worker&url';

interface UseAudioStreamerOptions {
  onAudioChunk: (chunk: ArrayBuffer) => void; // This will now receive ArrayBuffer of Int16 PCM data
  onError: (error: Error) => void;
  // timeslice is no longer directly used by this hook as the worklet posts data as it processes
  deviceId?: string | null;
}

const useAudioStreamer = ({ 
  onAudioChunk,
  onError,
  deviceId = null
}: UseAudioStreamerOptions) => {
  const { isRecording, setIsRecording } = useAppStore();
  const audioContextRef = useRef<AudioContext | null>(null);
  const mediaStreamSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const pcmWorkletNodeRef = useRef<AudioWorkletNode | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null); // To keep track of the raw media stream for stopping tracks
  const [currentStream, setCurrentStream] = useState<MediaStream | null>(null); // For UI feedback if needed

  const { setMicPermissionsError } = useAppStore();

  const stopMediaTracksAndContext = useCallback(() => {
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(track => track.stop());
      mediaStreamRef.current = null;
      setCurrentStream(null);
    }
    if (pcmWorkletNodeRef.current) {
      pcmWorkletNodeRef.current.disconnect();
      // pcmWorkletNodeRef.current.port.close(); // Not strictly necessary as node disconnect handles it
      pcmWorkletNodeRef.current = null;
    }
    if (mediaStreamSourceRef.current) {
      mediaStreamSourceRef.current.disconnect();
      mediaStreamSourceRef.current = null;
    }
    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      audioContextRef.current.close().then(() => {
        console.log('AudioContext closed.');
        audioContextRef.current = null;
      }).catch(err => console.error('Error closing AudioContext:', err));
    }
  }, []);

  const startStreaming = useCallback(async () => {
    if (isRecording) {
      console.warn('Audio streaming is already in progress.');
      return;
    }
    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
        await audioContextRef.current.close(); // Close existing context before starting new one
        audioContextRef.current = null;
    }
    stopMediaTracksAndContext(); // Clear any previous stream/context fully
    setMicPermissionsError(null);

    try {
      // 1. Get User Media (Microphone Stream)
      const audioConstraints: MediaTrackConstraints = {
        echoCancellation: true,
        noiseSuppression: true,
        // channelCount: 1, // Explicitly request mono if possible, though worklet will handle it
        // sampleRate: 16000, // Requesting specific sample rate here might fail if not supported
                          // Rely on worklet for resampling to target 16kHz
      };
      if (deviceId) {
        audioConstraints.deviceId = { exact: deviceId };
        console.log(`Attempting to use microphone: ${deviceId}`);
      } else {
        console.log('Attempting to use default microphone.');
      }

      const stream = await navigator.mediaDevices.getUserMedia({ audio: audioConstraints });
      mediaStreamRef.current = stream;
      setCurrentStream(stream);

      // 2. Create Audio Context & Source Node
      const context = new AudioContext();
      audioContextRef.current = context;
      mediaStreamSourceRef.current = context.createMediaStreamSource(stream);

      // 3. Load and Connect Audio Worklet
      try {
        // const processorUrl = new URL('../audio/pcm-processor.ts', import.meta.url).href; // Previous attempt
        const processorUrl = PcmProcessorWorkerModuleURL;
        await context.audioWorklet.addModule(processorUrl, { type: 'module' } as WorkletOptions);
      } catch (e: any) {
        // Construct the URL again for the error message, or ensure it's in scope
        // const processorUrlForError = new URL('../audio/pcm-processor.ts', import.meta.url).href; // Previous attempt
        const processorUrlForError = PcmProcessorWorkerModuleURL; // Use the same variable
        console.error('Error adding audio worklet module:', e);
        onError(new Error(`Failed to load audio processor: ${e.message}. Check console for details. Path used: ${processorUrlForError}`));
        stopMediaTracksAndContext();
        setIsRecording(false);
        return;
      }
      
      const pcmNode = new AudioWorkletNode(context, 'pcm-processor', {
        processorOptions: {
          targetSampleRate: 16000 // Pass the target sample rate to the worklet
        }
      });
      pcmWorkletNodeRef.current = pcmNode;

      pcmNode.port.onmessage = (event: MessageEvent) => {
        if (event.data instanceof ArrayBuffer) { // We expect ArrayBuffer of Int16 data
          onAudioChunk(event.data);
        } else {
          console.warn('Received non-ArrayBuffer message from PCMProcessor worklet:', event.data);
        }
      };
      
      pcmNode.port.onmessageerror = (event: MessageEvent) => {
        console.error('Error message from PCMProcessor worklet:', event);
        onError(new Error('PCMProcessor worklet encountered a message error.'));
      };

      mediaStreamSourceRef.current.connect(pcmNode);
      // The worklet node does not need to be connected to context.destination if it only posts messages.
      // If you wanted to *hear* the processed audio (e.g., for debugging), you would connect it:
      // pcmNode.connect(context.destination);

      setIsRecording(true);
      console.log('Audio streaming started with AudioWorklet.');

    } catch (err: any) {
      console.error('Error starting audio stream with AudioWorklet:', err);
      let message = "Failed to start audio stream.";
      if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
        message = "Microphone permission denied. Please allow access in your browser settings.";
      } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
        message = deviceId ? `Selected microphone (ID: ${deviceId}) not found.` : "No microphone found.";
      } else if (err.name === 'OverconstrainedError' || err.name === 'ConstraintNotSatisfiedError') {
        message = deviceId ? `Selected microphone (ID: ${deviceId}) does not support required constraints.` : "Microphone does not support required constraints.";
      }
      setMicPermissionsError(message);
      onError(new Error(message));
      stopMediaTracksAndContext();
      setIsRecording(false);
    }
  }, [isRecording, setIsRecording, onAudioChunk, onError, deviceId, stopMediaTracksAndContext, setMicPermissionsError]);

  const stopStreaming = useCallback(() => {
    stopMediaTracksAndContext();
    if (useAppStore.getState().isRecording) {
        setIsRecording(false);
    }
    console.log('stopStreaming called, AudioContext and tracks stopped.');
  }, [stopMediaTracksAndContext, setIsRecording]);

  useEffect(() => {
    return () => {
      stopMediaTracksAndContext();
    };
  }, [stopMediaTracksAndContext]);

  return { startStreaming, stopStreaming, isRecording, stream: currentStream };
};

export default useAudioStreamer; 