import { useState, useRef, useCallback, useEffect } from 'react';

// Helper to convert s16le ArrayBuffer to Float32Array
const pcmS16LEToFloat32 = (arrayBuffer: ArrayBuffer): Float32Array => {
  const inputView = new Int16Array(arrayBuffer);
  const outputArray = new Float32Array(inputView.length);
  for (let i = 0; i < inputView.length; i++) {
    // Normalize to [-1.0, 1.0]
    outputArray[i] = inputView[i] / 32768.0;
  }
  return outputArray;
};

// Helper to concatenate ArrayBuffers
const concatenateArrayBuffers = (buffers: ArrayBuffer[]): ArrayBuffer => {
  let totalLength = 0;
  for (const buffer of buffers) {
    totalLength += buffer.byteLength;
  }
  const result = new Uint8Array(totalLength);
  let offset = 0;
  for (const buffer of buffers) {
    result.set(new Uint8Array(buffer), offset);
    offset += buffer.byteLength;
  }
  return result.buffer;
};


export interface UseStreamedAudioPlayerReturn {
  startAudioStream: (sampleRate: number, channels: number) => void;
  enqueueAudioChunk: (chunk: ArrayBuffer) => void;
  endAudioStream: () => Promise<void>;
  stopAudioPlayback: () => void;
  isPlaying: boolean;
  error: string | null;
}

const useStreamedAudioPlayer = (): UseStreamedAudioPlayerReturn => {
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioBufferQueueRef = useRef<ArrayBuffer[]>([]);
  const currentSourceNodeRef = useRef<AudioBufferSourceNode | null>(null);
  
  const [isPlaying, setIsPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const streamSampleRate = useRef<number>(0);
  const streamChannels = useRef<number>(0);

  const getAudioContext = useCallback(() => {
    if (!audioContextRef.current) {
      try {
        audioContextRef.current = new (window.AudioContext || (window as any).webkitAudioContext)();
      } catch (e) {
        console.error("StreamedAudioPlayer: Failed to create AudioContext:", e);
        setError("AudioContext not supported or failed to initialize.");
        return null;
      }
    }
    if (audioContextRef.current && audioContextRef.current.state === 'suspended') {
      audioContextRef.current.resume().catch(err => 
        console.error("StreamedAudioPlayer: Error resuming AudioContext:", err)
      );
    }
    return audioContextRef.current;
  }, []);

  const stopAudioPlayback = useCallback(() => {
    if (currentSourceNodeRef.current) {
      try {
        currentSourceNodeRef.current.onended = null; 
        currentSourceNodeRef.current.stop();
      } catch (e) {
        // console.warn("StreamedAudioPlayer: Error stopping source node:", e); // Can be noisy
      }
      currentSourceNodeRef.current = null;
    }
    setIsPlaying(false);
  }, []);

  const startAudioStream = useCallback((sampleRate: number, channels: number) => {
    console.log(`StreamedAudioPlayer: Starting stream. Received SR=${sampleRate}, Channels=${channels}`);
    const audioCtx = getAudioContext();
    if (!audioCtx) return;

    stopAudioPlayback(); 
    audioBufferQueueRef.current = [];
    streamSampleRate.current = sampleRate;
    streamChannels.current = channels;
    setIsPlaying(false); 
    setError(null);
  }, [getAudioContext, stopAudioPlayback]);

  const enqueueAudioChunk = useCallback((chunk: ArrayBuffer) => {
    if (!streamSampleRate.current || !getAudioContext()) {
      // console.warn("StreamedAudioPlayer: Stream not started or no AudioContext, cannot enqueue chunk.");
      return;
    }
    audioBufferQueueRef.current.push(chunk);
  }, [getAudioContext]);

  const endAudioStream = useCallback(async () => {
    const audioCtx = getAudioContext();
    if (!audioCtx || !streamSampleRate.current || audioBufferQueueRef.current.length === 0) {
      console.log(`StreamedAudioPlayer: No AudioContext, stream not started (SR: ${streamSampleRate.current}), or no audio data to play.`);
      setIsPlaying(false); 
      audioBufferQueueRef.current = []; 
      return;
    }
    
    if (isPlaying && currentSourceNodeRef.current) { 
        console.warn("StreamedAudioPlayer: endAudioStream called while already playing. This indicates accumulate-then-play logic might need review or this is an unexpected call.");
    }

    const concatenatedBuffer = concatenateArrayBuffers(audioBufferQueueRef.current);
    audioBufferQueueRef.current = [];

    if (concatenatedBuffer.byteLength === 0) {
        console.log("StreamedAudioPlayer: Concatenated buffer is empty. Nothing to play.");
        setIsPlaying(false);
        return;
    }

    const float32PcmData = pcmS16LEToFloat32(concatenatedBuffer);
    
    if (float32PcmData.length === 0) {
        console.log("StreamedAudioPlayer: Float32 PCM data is empty. Nothing to play.");
        setIsPlaying(false);
        return;
    }

    try {
      // Ensure correct frame count for the number of channels
      const frameCount = float32PcmData.length / streamChannels.current;
      if (frameCount <= 0) {
        console.error("StreamedAudioPlayer: Frame count is zero or negative. Cannot create AudioBuffer.");
        setError("Processed audio data resulted in zero frames.");
        setIsPlaying(false);
        return;
      }

      const audioBuffer = audioCtx.createBuffer(
        streamChannels.current,
        frameCount, 
        streamSampleRate.current
      );
      
      console.log(`StreamedAudioPlayer: Creating AudioBuffer with SR: ${streamSampleRate.current}, Channels: ${streamChannels.current}, FrameCount: ${frameCount}`);
      
      for (let channel = 0; channel < streamChannels.current; channel++) {
        const channelData = audioBuffer.getChannelData(channel);
        for (let i = 0; i < frameCount; i++) {
          channelData[i] = float32PcmData[i * streamChannels.current + channel];
        }
      }
      
      stopAudioPlayback(); // Stop any previous node before playing new one

      const sourceNode = audioCtx.createBufferSource();
      sourceNode.buffer = audioBuffer;
      sourceNode.connect(audioCtx.destination);
      sourceNode.onended = () => {
        setIsPlaying(false);
        currentSourceNodeRef.current = null;
        console.log("StreamedAudioPlayer: Playback ended.");
      };
      sourceNode.start();
      currentSourceNodeRef.current = sourceNode;
      setIsPlaying(true);
      setError(null);
      console.log("StreamedAudioPlayer: Playback started.");

    } catch (e) {
      console.error("StreamedAudioPlayer: Error processing or playing audio buffer:", e);
      setError(e instanceof Error ? e.message : "Failed to play audio.");
      setIsPlaying(false);
    }
  }, [getAudioContext, /* isPlaying, */ stopAudioPlayback]);

  return {
    startAudioStream,
    enqueueAudioChunk,
    endAudioStream,
    stopAudioPlayback,
    isPlaying,
    error,
  };
};

export default useStreamedAudioPlayer; 