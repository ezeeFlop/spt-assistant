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
  const { isRecording, setIsRecording, setMicPermissionsError } = useAppStore();
  const audioContextRef = useRef<AudioContext | null>(null);
  const mediaStreamSourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const pcmWorkletNodeRef = useRef<AudioWorkletNode | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null); // To keep track of the raw media stream for stopping tracks
  const analyserNodeRef = useRef<AnalyserNode | null>(null); // For mic volume analysis
  const animationFrameIdRef = useRef<number | null>(null); // For volume analysis loop

  const [micAudioLevel, setMicAudioLevel] = useState(0); // Normalized 0-1
  const [currentStream, setCurrentStream] = useState<MediaStream | null>(null); // For UI feedback if needed

  const stopMediaTracksAndContext = useCallback(() => {
    if (animationFrameIdRef.current) {
      cancelAnimationFrame(animationFrameIdRef.current);
      animationFrameIdRef.current = null;
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(track => track.stop());
      mediaStreamRef.current = null;
      setCurrentStream(null);
    }
    if (pcmWorkletNodeRef.current) {
      pcmWorkletNodeRef.current.disconnect();
      pcmWorkletNodeRef.current = null;
    }
    if (analyserNodeRef.current) { // Disconnect and nullify analyser
        analyserNodeRef.current.disconnect();
        analyserNodeRef.current = null;
    }
    if (mediaStreamSourceRef.current) {
      mediaStreamSourceRef.current.disconnect();
      mediaStreamSourceRef.current = null;
    }
    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
      audioContextRef.current.close().then(() => {
        console.log('AudioContext closed by useAudioStreamer.');
        audioContextRef.current = null;
      }).catch(err => console.error('Error closing AudioContext:', err));
    }
    setMicAudioLevel(0); // Reset audio level
  }, []);

  const processMicVolume = useCallback(() => {
    if (!analyserNodeRef.current) {
      setMicAudioLevel(0);
      return;
    }
    const dataArray = new Uint8Array(analyserNodeRef.current.frequencyBinCount);
    analyserNodeRef.current.getByteFrequencyData(dataArray);
    let sum = 0;
    for (const amplitude of dataArray) {
      sum += amplitude * amplitude; // Sum of squares for better energy representation
    }
    // Calculate RMS and normalize. Max value for Uint8Array element is 255.
    // Normalization factor can be tweaked based on observed levels.
    const rms = Math.sqrt(sum / dataArray.length);
    const normalizedLevel = Math.min(rms / 128, 1); // Normalize (128 is a common divisor, adjust if needed)
    setMicAudioLevel(normalizedLevel);

    animationFrameIdRef.current = requestAnimationFrame(processMicVolume);
  }, []);

  const startStreaming = useCallback(async () => {
    if (isRecording) {
      console.warn('Audio streaming is already in progress.');
      return;
    }
    if (audioContextRef.current && audioContextRef.current.state !== 'closed') {
        console.log('Closing existing AudioContext before starting new one...');
        await audioContextRef.current.close();
        audioContextRef.current = null;
    }
    stopMediaTracksAndContext();
    setMicPermissionsError(null);

    try {
      const audioConstraints: MediaTrackConstraints = {
        echoCancellation: true,
        noiseSuppression: true,
      };
      if (deviceId) {
        audioConstraints.deviceId = { exact: deviceId };
      }

      const stream = await navigator.mediaDevices.getUserMedia({ audio: audioConstraints });
      mediaStreamRef.current = stream;
      setCurrentStream(stream);

      const context = new AudioContext();
      audioContextRef.current = context;
      mediaStreamSourceRef.current = context.createMediaStreamSource(stream);

      // Setup AnalyserNode for mic volume
      analyserNodeRef.current = context.createAnalyser();
      analyserNodeRef.current.fftSize = 256; // Smaller FFT for faster processing, adjust as needed
      mediaStreamSourceRef.current.connect(analyserNodeRef.current);
      // Start processing volume
      if (animationFrameIdRef.current) cancelAnimationFrame(animationFrameIdRef.current);
      processMicVolume(); 

      // Setup AudioWorklet for PCM processing
      try {
        await context.audioWorklet.addModule(PcmProcessorWorkerModuleURL, { type: 'module' } as WorkletOptions);
      } catch (e: any) {
        console.error('Error adding audio worklet module:', e);
        onError(new Error(`Failed to load audio processor: ${e.message}. Path: ${PcmProcessorWorkerModuleURL}`));
        stopMediaTracksAndContext();
        setIsRecording(false);
        return;
      }
      
      pcmWorkletNodeRef.current = new AudioWorkletNode(context, 'pcm-processor', {
        processorOptions: { targetSampleRate: 16000 }
      });

      pcmWorkletNodeRef.current.port.onmessage = (event: MessageEvent) => {
        if (event.data instanceof ArrayBuffer) {
          onAudioChunk(event.data);
        } else {
          console.warn('Non-ArrayBuffer message from PCMProcessor:', event.data);
        }
      };
      pcmWorkletNodeRef.current.port.onmessageerror = (event: MessageEvent) => {
        console.error('Error message from PCMProcessor:', event);
        onError(new Error('PCMProcessor worklet message error.'));
      };

      // Connect source to PCM worklet (source can connect to multiple nodes)
      mediaStreamSourceRef.current.connect(pcmWorkletNodeRef.current);

      setIsRecording(true);
      console.log('Audio streaming started with AudioWorklet and volume analysis.');

    } catch (err: any) {
      console.error('Error starting audio stream:', err);
      let message = "Failed to start audio stream.";
      if (err.name === 'NotAllowedError') message = "Microphone permission denied.";
      else if (err.name === 'NotFoundError') message = deviceId ? `Mic (ID: ${deviceId}) not found.` : "No microphone found.";
      else if (err.name === 'OverconstrainedError') message = deviceId ? `Mic (ID: ${deviceId}) doesn't support constraints.` : "Mic doesn't support constraints.";
      setMicPermissionsError(message);
      onError(new Error(message));
      stopMediaTracksAndContext();
      setIsRecording(false);
    }
  }, [
    isRecording, deviceId, stopMediaTracksAndContext, setMicPermissionsError, 
    onError, onAudioChunk, setIsRecording, processMicVolume // Added processMicVolume dependency
  ]);

  const stopStreaming = useCallback(() => {
    stopMediaTracksAndContext();
    if (useAppStore.getState().isRecording) {
        setIsRecording(false);
    }
    console.log('stopStreaming called, useAudioStreamer resources released.');
  }, [stopMediaTracksAndContext, setIsRecording]);

  useEffect(() => {
    // Cleanup on unmount
    return () => {
      stopMediaTracksAndContext();
    };
  }, [stopMediaTracksAndContext]);

  return { startStreaming, stopStreaming, isRecording, stream: currentStream, micAudioLevel };
};

export default useAudioStreamer; 