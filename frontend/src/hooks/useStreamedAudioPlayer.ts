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

export interface AudioSentence {
  buffer: AudioBuffer;
  sampleRate: number;
  channels: number;
}

export interface UseStreamedAudioPlayerReturn {
  startAudioStream: (sampleRate: number, channels: number) => void;
  enqueueAudioChunk: (chunk: ArrayBuffer) => void;
  endAudioStream: () => Promise<void>;
  stopAudioPlayback: () => void;
  isPlaying: boolean;
  playbackAudioLevel: number;
  error: string | null;
}

const useStreamedAudioPlayer = (): UseStreamedAudioPlayerReturn => {
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserNodeRef = useRef<AnalyserNode | null>(null);
  const animationFrameIdRef = useRef<number | null>(null);
  const dataArrayRef = useRef<Uint8Array | null>(null);
  
  // For the sentence currently being received from the server
  const currentSentenceChunksRef = useRef<ArrayBuffer[]>([]);
  const currentSentenceSampleRateRef = useRef<number>(0);
  const currentSentenceChannelsRef = useRef<number>(0);

  // Queue for fully processed sentences ready for playback
  const sentenceQueueRef = useRef<AudioSentence[]>([]);
  const currentSourceNodeRef = useRef<AudioBufferSourceNode | null>(null);
  
  const [isPlaying, setIsPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [playbackAudioLevel, setPlaybackAudioLevel] = useState<number>(0);

  // Internal state to trigger processing the queue
  const [triggerPlay, setTriggerPlay] = useState<number>(0);

  const getAudioContext = useCallback(() => {
    if (!audioContextRef.current) {
      try {
        audioContextRef.current = new (window.AudioContext || (window as any).webkitAudioContext)();
        analyserNodeRef.current = audioContextRef.current.createAnalyser();
        analyserNodeRef.current.fftSize = 2048;
        const bufferLength = analyserNodeRef.current.frequencyBinCount;
        dataArrayRef.current = new Uint8Array(bufferLength);
      } catch (e) {
        console.error("StreamedAudioPlayer: Failed to create AudioContext or AnalyserNode:", e);
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

  const stopAudioLevelMonitoring = useCallback(() => {
    if (animationFrameIdRef.current) {
      cancelAnimationFrame(animationFrameIdRef.current);
      animationFrameIdRef.current = null;
    }
    setPlaybackAudioLevel(0);
  }, []);

  const monitorAudioLevel = useCallback(() => {
    if (!analyserNodeRef.current || !dataArrayRef.current || !currentSourceNodeRef.current) {
      stopAudioLevelMonitoring();
      return;
    }

    analyserNodeRef.current.getByteTimeDomainData(dataArrayRef.current);
    
    let sumSquares = 0.0;
    for (let i = 0; i < dataArrayRef.current.length; i++) {
      const normSample = (dataArrayRef.current[i] / 128.0) - 1.0;
      sumSquares += normSample * normSample;
    }
    const rms = Math.sqrt(sumSquares / dataArrayRef.current.length);
    
    const normalizedLevel = Math.min(rms * 1.5, 1.0);

    setPlaybackAudioLevel(normalizedLevel);

    animationFrameIdRef.current = requestAnimationFrame(monitorAudioLevel);
  }, [stopAudioLevelMonitoring]);

  const playNextSentenceFromQueue = useCallback(() => {
    if (isPlaying || sentenceQueueRef.current.length === 0) {
      return;
    }

    const audioCtx = getAudioContext();
    if (!audioCtx || !analyserNodeRef.current) {
      console.error("StreamedAudioPlayer: No AudioContext or AnalyserNode available to play next sentence.");
      return;
    }

    const nextSentence = sentenceQueueRef.current.shift();
    if (!nextSentence) return;

    try {
      if (currentSourceNodeRef.current) {
        console.warn("StreamedAudioPlayer: Existing source node found when trying to play next. Stopping it.");
        currentSourceNodeRef.current.onended = null;
        currentSourceNodeRef.current.stop();
        currentSourceNodeRef.current.disconnect();
        currentSourceNodeRef.current = null;
      }

      const sourceNode = audioCtx.createBufferSource();
      sourceNode.buffer = nextSentence.buffer;
      
      sourceNode.connect(analyserNodeRef.current);
      analyserNodeRef.current.connect(audioCtx.destination);
      
      sourceNode.onended = () => {
        setIsPlaying(false);
        if (currentSourceNodeRef.current) {
            currentSourceNodeRef.current.disconnect();
            analyserNodeRef.current?.disconnect();
        }
        currentSourceNodeRef.current = null;
        stopAudioLevelMonitoring();
        console.log("StreamedAudioPlayer: Sentence playback ended.");
        setTriggerPlay(prev => prev + 1);
      };
      
      sourceNode.start();
      currentSourceNodeRef.current = sourceNode;
      setIsPlaying(true);
      setError(null);
      animationFrameIdRef.current = requestAnimationFrame(monitorAudioLevel);
      console.log("StreamedAudioPlayer: Sentence playback started.");
    } catch (e) {
      console.error("StreamedAudioPlayer: Error playing next sentence:", e);
      setError(e instanceof Error ? e.message : "Failed to play audio sentence.");
      setIsPlaying(false);
      stopAudioLevelMonitoring();
      setTriggerPlay(prev => prev + 1);
    }
  }, [isPlaying, getAudioContext, monitorAudioLevel, stopAudioLevelMonitoring]);

  // Effect to process queue when triggerPlay changes or isPlaying becomes false
  useEffect(() => {
    playNextSentenceFromQueue();
  }, [triggerPlay, isPlaying, playNextSentenceFromQueue]);

  const stopAudioPlayback = useCallback(() => {
    if (currentSourceNodeRef.current) {
      try {
        currentSourceNodeRef.current.onended = null;
        currentSourceNodeRef.current.stop();
        currentSourceNodeRef.current.disconnect();
        if (analyserNodeRef.current) {
            analyserNodeRef.current.disconnect();
        }
      } catch (e) {
        // console.warn("StreamedAudioPlayer: Error stopping source node:", e);
      }
      currentSourceNodeRef.current = null;
    }
    stopAudioLevelMonitoring();
    sentenceQueueRef.current = [];
    currentSentenceChunksRef.current = [];
    setIsPlaying(false);
    console.log("StreamedAudioPlayer: Playback stopped and queue cleared.");
  }, [stopAudioLevelMonitoring]);

  const startAudioStream = useCallback((sampleRate: number, channels: number) => {
    console.log(`StreamedAudioPlayer: Starting new sentence stream. SR=${sampleRate}, Channels=${channels}`);
    const audioCtx = getAudioContext();
    if (!audioCtx) {
        setError("AudioContext not available when starting stream.");
        return;
    }

    currentSentenceChunksRef.current = [];
    currentSentenceSampleRateRef.current = sampleRate;
    currentSentenceChannelsRef.current = channels;
  }, [getAudioContext]);

  const enqueueAudioChunk = useCallback((chunk: ArrayBuffer) => {
    if (!currentSentenceSampleRateRef.current || !getAudioContext()) {
      return;
    }
    currentSentenceChunksRef.current.push(chunk);
  }, [getAudioContext]);

  const endAudioStream = useCallback(async () => {
    const audioCtx = getAudioContext();
    if (!audioCtx || !currentSentenceSampleRateRef.current || currentSentenceChunksRef.current.length === 0) {
      console.log(`StreamedAudioPlayer: No AudioContext, sentence stream not properly started (SR: ${currentSentenceSampleRateRef.current}), or no audio data for current sentence.`);
      currentSentenceChunksRef.current = [];
      return;
    }

    const concatenatedBuffer = concatenateArrayBuffers(currentSentenceChunksRef.current);
    currentSentenceChunksRef.current = [];

    if (concatenatedBuffer.byteLength === 0) {
        console.log("StreamedAudioPlayer: Concatenated buffer for sentence is empty.");
        return;
    }

    const float32PcmData = pcmS16LEToFloat32(concatenatedBuffer);
    
    if (float32PcmData.length === 0) {
        console.log("StreamedAudioPlayer: Float32 PCM data for sentence is empty.");
        return;
    }

    try {
      const frameCount = float32PcmData.length / currentSentenceChannelsRef.current;
      if (frameCount <= 0) {
        console.error("StreamedAudioPlayer: Frame count for sentence is zero or negative.");
        setError("Processed audio data for sentence resulted in zero frames.");
        return;
      }

      const audioBuffer = audioCtx.createBuffer(
        currentSentenceChannelsRef.current,
        frameCount, 
        currentSentenceSampleRateRef.current
      );
      
      console.log(`StreamedAudioPlayer: Creating AudioBuffer for sentence with SR: ${currentSentenceSampleRateRef.current}, Channels: ${currentSentenceChannelsRef.current}, FrameCount: ${frameCount}`);
      
      for (let channel = 0; channel < currentSentenceChannelsRef.current; channel++) {
        const channelData = audioBuffer.getChannelData(channel);
        for (let i = 0; i < frameCount; i++) {
          channelData[i] = float32PcmData[i * currentSentenceChannelsRef.current + channel];
        }
      }
      
      sentenceQueueRef.current.push({
        buffer: audioBuffer,
        sampleRate: currentSentenceSampleRateRef.current,
        channels: currentSentenceChannelsRef.current
      });
      console.log(`StreamedAudioPlayer: Sentence added to queue. Queue size: ${sentenceQueueRef.current.length}`);
      setTriggerPlay(prev => prev + 1);

    } catch (e) {
      console.error("StreamedAudioPlayer: Error processing sentence audio buffer:", e);
      setError(e instanceof Error ? e.message : "Failed to process sentence audio.");
    }
  }, [getAudioContext]);

  return {
    startAudioStream,
    enqueueAudioChunk,
    endAudioStream,
    stopAudioPlayback,
    isPlaying,
    playbackAudioLevel,
    error,
  };
};

export default useStreamedAudioPlayer; 