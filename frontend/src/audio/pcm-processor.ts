// Ignore this line if you don't have @types/audioworklet installed
// @ts-ignore
/// <reference types="audioworklet" />

// --- Temporary TypeScript Workaround for AudioWorklet ---
// In a real project, ensure you have @types/audioworklet or similar installed
// and your tsconfig.json is set up to include web worker/worklet types.

declare var globalThis: AudioWorkletGlobalScope;

interface AudioWorkletProcessor {
  readonly port: MessagePort;
  process(inputs: Float32Array[][], outputs: Float32Array[][], parameters: Record<string, Float32Array>): boolean;
}

declare var AudioWorkletProcessor: {
  prototype: AudioWorkletProcessor;
  new (options?: AudioWorkletNodeOptions): AudioWorkletProcessor;
};

declare function registerProcessor(
  name: string,
  processorCtor: (new (options?: AudioWorkletNodeOptions) => AudioWorkletProcessor)
): void;

interface AudioWorkletGlobalScope {
  readonly currentFrame: number;
  readonly currentTime: number;
  readonly sampleRate: number;
  registerProcessor: typeof registerProcessor;
}
// --- End of Temporary TypeScript Workaround ---

class PCMProcessor extends AudioWorkletProcessor {
  private targetSampleRate = 16000;
  private internalBuffer: Float32Array | null = null;
  private internalBufferCurrentLength = 0;

  constructor(options?: AudioWorkletNodeOptions) {
    super();
    if (options && options.processorOptions && options.processorOptions.targetSampleRate) {
      this.targetSampleRate = options.processorOptions.targetSampleRate;
    }
    this.port.onmessage = (event: MessageEvent) => {
      if (event.data.type === 'setTargetSampleRate') {
        this.targetSampleRate = event.data.sampleRate;
        console.log(`PCMProcessor: Target sample rate changed to ${this.targetSampleRate}`);
      }
    };
    console.log(`PCMProcessor initialized. Worklet sampleRate: ${globalThis.sampleRate}, Target SR: ${this.targetSampleRate}`);
  }
  // @ts-ignore
  process(inputs: Float32Array[][], outputs: Float32Array[][], parameters: Record<string, Float32Array>): boolean {
    const inputChannelData = inputs[0]?.[0];
    
    if (!inputChannelData || inputChannelData.length === 0) {
      return true; // Keep processor alive
    }

    const inputSR = globalThis.sampleRate;

    // Append new data to our internal buffer
    if (!this.internalBuffer || this.internalBufferCurrentLength + inputChannelData.length > this.internalBuffer.length) {
      const newRequiredLength = (this.internalBufferCurrentLength + inputChannelData.length) * 2; // Allocate more space
      const newBuffer = new Float32Array(Math.max(newRequiredLength, inputSR * 1)); // Ensure at least 1s buffer at inputSR
      if (this.internalBuffer && this.internalBufferCurrentLength > 0) {
        newBuffer.set(this.internalBuffer.slice(0, this.internalBufferCurrentLength));
      }
      this.internalBuffer = newBuffer;
    }
    this.internalBuffer.set(inputChannelData, this.internalBufferCurrentLength);
    this.internalBufferCurrentLength += inputChannelData.length;

    // Determine how many full output blocks we can produce
    const downsampleRatio = inputSR / this.targetSampleRate;
    // Process in chunks that correspond to roughly 128 samples at the output rate
    const desiredOutputBlockSize = 4096; // Increased from 128 to 512 (32ms chunks at 16kHz)
    const requiredInputSamplesPerOutputBlock = Math.ceil(desiredOutputBlockSize * downsampleRatio);

    while (this.internalBufferCurrentLength >= requiredInputSamplesPerOutputBlock) {
      // Extract the exact number of input samples needed for one output block
      const samplesToProcess = requiredInputSamplesPerOutputBlock;
      const currentProcessingBlock = this.internalBuffer.slice(0, samplesToProcess);
      
      // Shift the remaining data in the internal buffer
      if (this.internalBufferCurrentLength > samplesToProcess) {
        this.internalBuffer.copyWithin(0, samplesToProcess, this.internalBufferCurrentLength);
      }
      this.internalBufferCurrentLength -= samplesToProcess;

      // Downsample and convert
      const resampledAudio = this.downsample(currentProcessingBlock, inputSR, this.targetSampleRate);
      const pcm16 = this.convertToPCM16(resampledAudio);

      if (pcm16.length > 0) {
        this.port.postMessage(pcm16.buffer, [pcm16.buffer]);
      }
    }
    return true; // Keep processor alive
  }

  downsample(buffer: Float32Array, inputSR: number, outputSR: number): Float32Array {
    if (inputSR === outputSR) {
      return buffer;
    }
    const ratio = inputSR / outputSR;
    const outputLength = Math.floor(buffer.length / ratio);
    const result = new Float32Array(outputLength);
    // Basic linear interpolation for downsampling
    for (let i = 0; i < outputLength; i++) {
      const P = i * ratio;
      const Pfloor = Math.floor(P);
      const Pceil = Math.ceil(P);
      if (Pceil < buffer.length) {
        result[i] = buffer[Pfloor] + (P - Pfloor) * (buffer[Pceil] - buffer[Pfloor]);
      } else {
        result[i] = buffer[Pfloor]; // Fallback for the last sample
      }
    }
    return result;
  }

  convertToPCM16(buffer: Float32Array): Int16Array {
    const pcm16 = new Int16Array(buffer.length);
    for (let i = 0; i < buffer.length; i++) {
      const s = Math.max(-1, Math.min(1, buffer[i])); // Clamp to [-1, 1]
      pcm16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;    // Convert to 16-bit signed int
    }
    return pcm16;
  }
}

registerProcessor('pcm-processor', PCMProcessor); 