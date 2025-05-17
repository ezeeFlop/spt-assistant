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
  error: string | null;
}

const useStreamedAudioPlayer = (): UseStreamedAudioPlayerReturn => {
  const audioContextRef = useRef<AudioContext | null>(null);
  
  // For the sentence currently being received from the server
  const currentSentenceChunksRef = useRef<ArrayBuffer[]>([]);
  const currentSentenceSampleRateRef = useRef<number>(0);
  const currentSentenceChannelsRef = useRef<number>(0);

  // Queue for fully processed sentences ready for playback
  const sentenceQueueRef = useRef<AudioSentence[]>([]);
  const currentSourceNodeRef = useRef<AudioBufferSourceNode | null>(null);
  
  const [isPlaying, setIsPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Internal state to trigger processing the queue
  const [triggerPlay, setTriggerPlay] = useState<number>(0);

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

  const playNextSentenceFromQueue = useCallback(() => {
    if (isPlaying || sentenceQueueRef.current.length === 0) {
      return;
    }

    const audioCtx = getAudioContext();
    if (!audioCtx) {
      console.error("StreamedAudioPlayer: No AudioContext available to play next sentence.");
      return;
    }

    const nextSentence = sentenceQueueRef.current.shift(); // Get and remove the next sentence
    if (!nextSentence) return;

    try {
      if (currentSourceNodeRef.current) {
        // This should ideally not happen if isPlaying is managed correctly
        console.warn("StreamedAudioPlayer: Existing source node found when trying to play next. Stopping it.");
        currentSourceNodeRef.current.onended = null;
        currentSourceNodeRef.current.stop();
        currentSourceNodeRef.current = null;
      }

      const sourceNode = audioCtx.createBufferSource();
      sourceNode.buffer = nextSentence.buffer;
      sourceNode.connect(audioCtx.destination);
      
      sourceNode.onended = () => {
        setIsPlaying(false);
        currentSourceNodeRef.current = null;
        console.log("StreamedAudioPlayer: Sentence playback ended.");
        setTriggerPlay(prev => prev + 1); // Trigger check for next sentence
      };
      
      sourceNode.start();
      currentSourceNodeRef.current = sourceNode;
      setIsPlaying(true);
      setError(null);
      console.log("StreamedAudioPlayer: Sentence playback started.");
    } catch (e) {
      console.error("StreamedAudioPlayer: Error playing next sentence:", e);
      setError(e instanceof Error ? e.message : "Failed to play audio sentence.");
      setIsPlaying(false);
      // Attempt to play the next one if this fails
      setTriggerPlay(prev => prev + 1);
    }
  }, [isPlaying, getAudioContext]);

  // Effect to process queue when triggerPlay changes or isPlaying becomes false
  useEffect(() => {
    playNextSentenceFromQueue();
  }, [triggerPlay, isPlaying, playNextSentenceFromQueue]);

  const stopAudioPlayback = useCallback(() => {
    if (currentSourceNodeRef.current) {
      try {
        currentSourceNodeRef.current.onended = null; // Important to prevent onended from triggering playNext
        currentSourceNodeRef.current.stop();
      } catch (e) {
        // console.warn("StreamedAudioPlayer: Error stopping source node:", e);
      }
      currentSourceNodeRef.current = null;
    }
    sentenceQueueRef.current = []; // Clear the queue of pending sentences
    currentSentenceChunksRef.current = []; // Clear any partially received sentence
    setIsPlaying(false);
    console.log("StreamedAudioPlayer: Playback stopped and queue cleared.");
  }, []);

  const startAudioStream = useCallback((sampleRate: number, channels: number) => {
    console.log(`StreamedAudioPlayer: Starting new sentence stream. SR=${sampleRate}, Channels=${channels}`);
    const audioCtx = getAudioContext(); // Ensure context is ready/resumed
    if (!audioCtx) {
        setError("AudioContext not available when starting stream.");
        return;
    }

    // Reset for the new incoming sentence, but don't stop current playback here
    currentSentenceChunksRef.current = [];
    currentSentenceSampleRateRef.current = sampleRate;
    currentSentenceChannelsRef.current = channels;
    // setError(null); // Don't clear general errors, only playback ones during play
  }, [getAudioContext]);

  const enqueueAudioChunk = useCallback((chunk: ArrayBuffer) => {
    if (!currentSentenceSampleRateRef.current || !getAudioContext()) {
      // console.warn("StreamedAudioPlayer: Sentence stream not started or no AudioContext, cannot enqueue chunk.");
      return;
    }
    currentSentenceChunksRef.current.push(chunk);
  }, [getAudioContext]);

  const endAudioStream = useCallback(async () => {
    const audioCtx = getAudioContext();
    if (!audioCtx || !currentSentenceSampleRateRef.current || currentSentenceChunksRef.current.length === 0) {
      console.log(`StreamedAudioPlayer: No AudioContext, sentence stream not properly started (SR: ${currentSentenceSampleRateRef.current}), or no audio data for current sentence.`);
      currentSentenceChunksRef.current = []; // Clear if any partial data exists for a failed stream
      // Do not set isPlaying false here, as another sentence might be playing from the queue.
      return;
    }

    const concatenatedBuffer = concatenateArrayBuffers(currentSentenceChunksRef.current);
    currentSentenceChunksRef.current = []; // Reset for next sentence after consuming current chunks

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
      setTriggerPlay(prev => prev + 1); // Trigger the queue processor

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
    error,
  };
};

export default useStreamedAudioPlayer; 