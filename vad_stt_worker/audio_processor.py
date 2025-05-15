# Placeholder for VAD and STT logic (now with streaming enhancements)
# This file will contain the AudioProcessor class/functions

import torch
from faster_whisper import WhisperModel
import numpy as np
from typing import Iterator, Tuple, List, Dict, Any
import time
import scipy.signal

from vad_stt_worker.config import worker_settings
from vad_stt_worker.logging_config import get_logger

# logger = get_logger(__name__) # Module-level logger, can be used if class logger is not preferred

# Minimum audio length in seconds to feed to STT, helps avoid tiny/noisy segments
MIN_STT_AUDIO_S = 0.6 
# How much audio (in seconds) to keep in the buffer before the start of the last VAD segment.
# This helps provide left-context to Whisper for better accuracy.
AUDIO_BUFFER_PREFIX_S = 2 
# Minimum audio buffer (in seconds) required before running VAD.
# This helps ensure more of an initial utterance is captured before segmentation.
MIN_AUDIO_BUFFER_S_BEFORE_VAD = 2

class AudioProcessor:
    def __init__(self):
        self.logger = get_logger(__name__) # Initialize instance logger
        self.logger.info("Initializing AudioProcessor (PCM input mode)...")
        self.audio_buffer = np.array([], dtype=np.float32)
        
        # VAD and STT should operate at the same configured sample rate
        self.target_sample_rate = worker_settings.VAD_SAMPLING_RATE # VAD and STT expect this rate
        self.logger.info(f"Target sample rate set to: {self.target_sample_rate} Hz")

        self.vad_model, vad_utils_tuple = self._load_vad_model()
        if self.vad_model is None or vad_utils_tuple is None:
            self.logger.error("Failed to load Silero VAD model or its utilities.")
            raise RuntimeError("VAD model loading failed.") # Fail fast
        else:
            try:
                (self.get_speech_timestamps, 
                 _save_audio, 
                 self.read_audio, 
                 _VADIterator, _collect_chunks) = vad_utils_tuple
                self.logger.info("Silero VAD model and utils loaded successfully.")
            except ValueError as e:
                self.logger.error(f"Error unpacking VAD utils tuple: {e}", exc_info=True)
                raise RuntimeError(f"Failed to unpack Silero VAD utility functions: {e}")

        self.logger.info(f"Loading STT model: {worker_settings.STT_MODEL_NAME} on device: {worker_settings.FINAL_STT_DEVICE} with compute_type: {worker_settings.STT_COMPUTE_TYPE}")
        try:
            self.stt_model = WhisperModel(
                worker_settings.STT_MODEL_NAME,
                device=worker_settings.FINAL_STT_DEVICE,
                compute_type=worker_settings.STT_COMPUTE_TYPE
            )
            self.logger.info("faster-whisper STT model loaded successfully.")
        except Exception as e:
            self.logger.error(f"Failed to load faster-whisper STT model: {e}", exc_info=True)
            raise RuntimeError(f"Failed to load faster-whisper STT model: {e}")
        
        self.last_stt_processed_sample_idx = 0
        self.last_partial_yield_time = 0
        self.current_transcript_words = []
        
        self.logger.info("AudioProcessor initialized for raw PCM processing.")

    def close(self):
        self.logger.info("AudioProcessor.close() called. Buffers will be cleared on next processing if any.")
        # Resetting buffers or STT context might be done here if needed for explicit cleanup
        # For now, main buffer clearing is handled by _reset_stt_context and general trimming
        # No complex process or threads to shut down.
        self.audio_buffer = np.array([], dtype=np.float32)
        self.last_stt_processed_sample_idx = 0
        self.current_transcript_words = []
        self.logger.info("AudioProcessor internal state reset on close.")

    def _load_vad_model(self):
        """Loads the Silero VAD model from torch.hub."""
        try:
            # Silero VAD is loaded via torch.hub
            # FR-02 specifies silero-vad version 0.4. The torch.hub call usually gets the latest from the repo.
            # To pin to a specific version/commit, a more specific hubconf.py or commit hash might be needed.
            # For now, using the standard way which gets the repo's default.
            model, utils = torch.hub.load(
                repo_or_dir=worker_settings.VAD_MODEL_REPO, 
                model=worker_settings.VAD_MODEL_NAME, 
                force_reload=False, # Set to True to always re-download, False to use cache
                onnx=worker_settings.VAD_ONNX # Use ONNX setting from config
            )
            # Return the model and the entire utils object
            return model, utils
        except Exception as e:
            self.logger.error(f"Error loading Silero VAD model: {e}", exc_info=True)
            return None, None

    def _convert_pcm_s16le_to_float32(self, pcm_s16le_bytes: bytes) -> np.ndarray:
        """Converts raw PCM S16LE bytes to a NumPy array of float32 samples."""
        if not pcm_s16le_bytes:
            return np.array([], dtype=np.float32)
        
        # Ensure byte string length is a multiple of 2 (each sample is 2 bytes for int16)
        if len(pcm_s16le_bytes) % 2 != 0:
            self.logger.warning(f"Received PCM S16LE byte string with odd length: {len(pcm_s16le_bytes)}. Truncating last byte.")
            pcm_s16le_bytes = pcm_s16le_bytes[:-1]
            if not pcm_s16le_bytes:
                return np.array([], dtype=np.float32)

        try:
            # Interpret bytes as int16 little-endian
            pcm_int16 = np.frombuffer(pcm_s16le_bytes, dtype=np.int16)
            # Convert to float32 and normalize to [-1.0, 1.0]
            pcm_float32 = pcm_int16.astype(np.float32) / 32768.0 
            return pcm_float32
        except Exception as e:
            self.logger.error(f"Error converting S16LE PCM bytes to float32: {e}", exc_info=True)
            return np.array([], dtype=np.float32)

    def _resample_audio(self, audio_data: np.ndarray, original_sr: int, target_sr: int) -> np.ndarray:
        """Resamples audio data to the target sample rate if necessary."""
        if original_sr == target_sr:
            return audio_data
        
        self.logger.warning(f"Resampling audio from {original_sr}Hz to {target_sr}Hz. This should ideally be handled by the client.")
        if original_sr <= 0:
            self.logger.error(f"Invalid original_sr ({original_sr}) for resampling. Skipping resampling.")
            return audio_data

        num_samples = len(audio_data)
        target_num_samples = int(num_samples * target_sr / original_sr)
        
        try:
            resampled_audio = scipy.signal.resample(audio_data, target_num_samples)
            return resampled_audio.astype(np.float32)
        except Exception as e:
            self.logger.error(f"Error during resampling from {original_sr}Hz to {target_sr}Hz: {e}", exc_info=True)
            return audio_data

    def _reset_stt_context(self, last_processed_end_sample: int | None = None):
        """Resets context for the current utterance being transcribed."""
        # self.logger.debug(f"Resetting STT context. Last processed end sample for potential trim: {last_processed_end_sample}")
        self.current_transcript_words = []
        self.last_partial_yield_time = 0
        
        if last_processed_end_sample is not None:
            # self.logger.debug(f"Updating last_stt_processed_sample_idx from {self.last_stt_processed_sample_idx} to {last_processed_end_sample}")
            self.last_stt_processed_sample_idx = last_processed_end_sample
            
            # Aggressively trim the buffer after a final utterance, keeping only a prefix for the next one.
            # The prefix should be *before* where new speech might start relative to the *new* buffer.
            # If last_stt_processed_sample_idx is now the end of the utterance in the *old* buffer state:
            prefix_samples = int(AUDIO_BUFFER_PREFIX_S * self.target_sample_rate)
            
            # We want to effectively discard up to self.last_stt_processed_sample_idx,
            # but ensure the part of the buffer we keep, if any, has its `last_stt_processed_sample_idx` correctly relative to its new start.
            # If we trim up to `trim_from = self.last_stt_processed_sample_idx`
            # The new buffer would be `self.audio_buffer[trim_from:]`
            # And the new `last_stt_processed_sample_idx` should be 0 relative to this new buffer.

            # More simply: After an utterance is final, the next utterance starts fresh from STT perspective.
            # The audio buffer should be trimmed to remove most of the processed utterance, only keeping tail for context.
            
            # Cut point in the current buffer: effectively the end of the finalized utterance.
            cut_point = self.last_stt_processed_sample_idx 

            # Determine how much of the tail (prefix for next utterance) to keep from *before* this cut_point.
            context_to_keep_from_before_cut = self.audio_buffer[max(0, cut_point - prefix_samples) : cut_point]
            remaining_audio_after_cut = self.audio_buffer[cut_point:]
            
            self.audio_buffer = np.concatenate((context_to_keep_from_before_cut, remaining_audio_after_cut))
            # After this, last_stt_processed_sample_idx should be relative to the new buffer start.
            # The 'processed' part is now the 'context_to_keep_from_before_cut'.
            self.last_stt_processed_sample_idx = len(context_to_keep_from_before_cut)
            # self.logger.debug(f"Buffer aggressively trimmed. New size: {len(self.audio_buffer)}. New last_stt_idx: {self.last_stt_processed_sample_idx}")
        else:
            # This case is for resets not tied to a final utterance end (e.g. initial state, error)
            # Standard buffer trimming will apply later in process_audio_chunk
            pass

    def process_audio_chunk(self, raw_pcm_s16le_bytes: bytes) -> Iterator[Tuple[str, bool, float]]:
        # This method now takes raw PCM s16le bytes (FR-01 conformity)
        
        # 1. Convert raw PCM S16LE bytes to float32 NumPy array
        decoded_audio_np = self._convert_pcm_s16le_to_float32(raw_pcm_s16le_bytes)

        if decoded_audio_np.size == 0:
            # self.logger.debug("Empty audio chunk after PCM conversion.")
            yield from []
            return
        
        # At this point, decoded_audio_np should be 16kHz float32 mono as per frontend's PCMProcessor
        # If there was a mismatch, _resample_audio could be called here, but we assume client conformity.
        # Example: if client_sample_rate != self.target_sample_rate:
        #    decoded_audio_np = self._resample_audio(decoded_audio_np, client_sample_rate, self.target_sample_rate)

        # --- Start of VAD/STT processing logic (largely unchanged from before) ---
        self.audio_buffer = np.concatenate((self.audio_buffer, decoded_audio_np))
        # self.logger.debug(f"Appended {len(decoded_audio_np)} decoded samples to buffer. Buffer size: {len(self.audio_buffer)}")

        min_buffer_samples_for_vad = int(MIN_AUDIO_BUFFER_S_BEFORE_VAD * self.target_sample_rate)
        if len(self.audio_buffer) < min_buffer_samples_for_vad: 
            yield from []
            return

        try:
            contiguous_audio_buffer = np.ascontiguousarray(self.audio_buffer)
            audio_tensor = torch.from_numpy(contiguous_audio_buffer)
            if not hasattr(self, 'get_speech_timestamps') or not self.vad_model:
                 self.logger.error("VAD model/utils not loaded properly. Cannot perform VAD.")
                 yield from []
                 return
            speech_timestamps: List[Dict[str, int]] = self.get_speech_timestamps(
                audio_tensor, 
                self.vad_model, 
                sampling_rate=self.target_sample_rate, # Assumes audio_buffer is at target_sample_rate
                threshold=worker_settings.VAD_THRESHOLD,
                min_silence_duration_ms=worker_settings.VAD_MIN_SILENCE_DURATION_MS,
                speech_pad_ms=worker_settings.VAD_SPEECH_PAD_MS
            )
        except Exception as e:
            self.logger.error(f"Error during VAD processing: {e}", exc_info=True)
            yield from []
            return

        if not speech_timestamps:
            # MODIFIED: Removed immediate finalization of self.current_transcript_words here.
            # Finalization should be handled by the main STT loop when VAD segments are processed
            # or by a more robust end-of-speech timeout mechanism if speech truly ends with silence.
            # if self.current_transcript_words:
            #     final_text = " ".join(w["word"].strip() for w in self.current_transcript_words if w["word"].strip())
            #     final_text = " ".join(final_text.split()).strip()
            #     yield (final_text, True, time.time() * 1000)
            #     self._reset_stt_context(len(self.audio_buffer) -1) # Use end of current buffer for reset
            
            # Trim buffer if no speech detected for a while to prevent excessive growth (existing logic)
            prefix_samples = int(AUDIO_BUFFER_PREFIX_S * self.target_sample_rate)
            if len(self.audio_buffer) > prefix_samples * 2: # Keep a bit more than just prefix if silent
                 self.audio_buffer = self.audio_buffer[-prefix_samples:]
                 self.last_stt_processed_sample_idx = min(self.last_stt_processed_sample_idx, len(self.audio_buffer))
            yield from [] # Yield nothing if no VAD activity and we are not finalizing here.
            return

        buffer_processed_up_to_sample = 0
        any_transcript_yielded_this_call = False

        for i, segment_ts in enumerate(speech_timestamps):
            start_sample = segment_ts['start']
            end_sample = segment_ts['end']

            if start_sample < self.last_stt_processed_sample_idx - self.target_sample_rate * 0.1:
                buffer_processed_up_to_sample = max(buffer_processed_up_to_sample, end_sample)
                continue
                
            segment_audio = self.audio_buffer[start_sample:end_sample]
            segment_duration_s = len(segment_audio) / self.target_sample_rate

            if segment_duration_s < MIN_STT_AUDIO_S:
                buffer_processed_up_to_sample = max(buffer_processed_up_to_sample, end_sample)
                continue 

            try:
                whisper_segments, info = self.stt_model.transcribe(
                    segment_audio, 
                    beam_size=worker_settings.STT_BEAM_SIZE,
                    language=worker_settings.STT_LANGUAGE,
                    word_timestamps=True,
                )
                is_last_vad_segment_in_buffer = (i == len(speech_timestamps) - 1)
                # Adjust end condition: consider final if VAD segment ends near the current end of the audio_buffer
                # This is more robust than just checking if it's the last VAD segment from the *current VAD run*
                # as more audio might have arrived since VAD ran.
                # For simplicity here, using the previous logic:
                # Increased from 0.5s to 1.0s to be less aggressive with finalization
                ends_near_buffer_end = (len(self.audio_buffer) - end_sample) < (self.target_sample_rate * 1.0)                 
                
                for word_segment in whisper_segments: 
                    # self.logger.info(f"STT segment: {word_segment}") # Can be very verbose
                    if not word_segment.words: # Handle cases where Whisper gives text but no word timestamps
                        if word_segment.text.strip(): 
                            self.current_transcript_words.append({"word": word_segment.text.strip(), "start": word_segment.start, "end": word_segment.end})
                    else:
                        for word_info in word_segment.words:
                            self.current_transcript_words.append({"word": word_info.word, "start": word_info.start, "end": word_info.end})
                        
                    # Yield partial transcript based on accumulated words if conditions met
                    now = time.time()
                    # Condition: interval passed OR new word is reasonably long (suggests meaningful change)
                    if self.current_transcript_words and ((now - self.last_partial_yield_time) * 1000 >= worker_settings.STT_PARTIAL_TRANSCRIPT_INTERVAL_MS or \
                       (self.current_transcript_words[-1]["word"].strip() and len(self.current_transcript_words[-1]["word"].strip()) > 2)):
                        current_words_for_partial = [w["word"].strip() for w in self.current_transcript_words if w["word"].strip()]
                        partial_text = " ".join(current_words_for_partial)
                        partial_text = " ".join(partial_text.split()).strip() # Normalize spaces
                        if partial_text: # Only yield if there's actual text
                            # self.logger.debug(f"Yielding partial transcript: {partial_text}")
                            yield (partial_text, False, now * 1000)
                            self.last_partial_yield_time = now
                            any_transcript_yielded_this_call = True
                
                utterance_is_final = is_last_vad_segment_in_buffer and ends_near_buffer_end

                if self.current_transcript_words and utterance_is_final: 
                    final_text_segment = " ".join(w["word"].strip() for w in self.current_transcript_words if w["word"].strip())
                    final_text_for_segment_or_utterance = " ".join(final_text_segment.split()).strip() # Normalize spaces

                    # self.logger.info(f"AUDIO_PROCESSOR: PREPARING TO YIELD transcript='{final_text_for_segment_or_utterance}', final={utterance_is_final}")
                    if final_text_for_segment_or_utterance: # Only yield if there's text
                        yield (final_text_for_segment_or_utterance, True, time.time() * 1000) # True for final
                        any_transcript_yielded_this_call = True
                        self._reset_stt_context(end_sample) # Pass end_sample of the final VAD segment
                
                buffer_processed_up_to_sample = max(buffer_processed_up_to_sample, end_sample)

            except Exception as e:
                self.logger.error(f"Error during STT processing for a segment: {e}", exc_info=True)
                # Yield an error marker, consider it final for this attempt
                yield ("[STT Processing Error]", True, time.time() * 1000) 
                any_transcript_yielded_this_call = True
                self._reset_stt_context() 
                buffer_processed_up_to_sample = max(buffer_processed_up_to_sample, end_sample) # Still advance buffer
        
        # General buffer trimming logic (from before, ensure it's still valid)
        if not (any_transcript_yielded_this_call and not self.current_transcript_words): # If a final transcript was yielded, current_transcript_words would be empty
            prefix_samples = int(AUDIO_BUFFER_PREFIX_S * self.target_sample_rate)
            effective_trim_start = max(0, buffer_processed_up_to_sample - prefix_samples)
            
            if effective_trim_start > 0 and effective_trim_start < len(self.audio_buffer):
                self.audio_buffer = self.audio_buffer[effective_trim_start:]
                self.last_stt_processed_sample_idx = max(0, self.last_stt_processed_sample_idx - effective_trim_start)
            elif buffer_processed_up_to_sample >= len(self.audio_buffer) - 10: # If almost entire buffer was processed
                 self.audio_buffer = self.audio_buffer[max(0, len(self.audio_buffer) - prefix_samples):] # Keep only prefix
                 self.last_stt_processed_sample_idx = min(len(self.audio_buffer), prefix_samples) 
            elif not speech_timestamps and len(self.audio_buffer) > self.target_sample_rate * 10: # Trim long silent buffer
                self.audio_buffer = self.audio_buffer[-prefix_samples:]
                self.last_stt_processed_sample_idx = len(self.audio_buffer)
        
        if not any_transcript_yielded_this_call and self.current_transcript_words:
            # This case can happen if speech is detected, words are accumulated,
            # but no partial/final condition was met within this specific call to process_audio_chunk.
            # We don't necessarily need to yield here unless a timeout or other logic forces it.
            # The words remain in self.current_transcript_words for the next chunk.
            pass

        # Ensure that if nothing was yielded but there were words, they are not lost if no more audio comes
        # This might be better handled by a timeout mechanism in the main worker loop for finalization.
        # For now, if no transcript yielded and we have words, they stay for next round.

        if not any_transcript_yielded_this_call:
             yield from []

# Example Usage (for testing this file directly, not part of worker main loop)
# if __name__ == '__main__':
#     processor = AudioProcessor()
#     # Create a dummy audio chunk (e.g., 1 second of silence or noise at 16kHz)
#     SAMPLE_RATE = 16000
#     duration = 1  # seconds
#     num_samples = SAMPLE_RATE * duration
#     dummy_audio_bytes = (np.random.uniform(-0.5, 0.5, num_samples) * np.iinfo(np.int16).max).astype(np.int16).tobytes()
    
#     print("Processing dummy audio chunk...")
#     for transcript, is_final, timestamp_ms in processor.process_audio_chunk(dummy_audio_bytes):
#         print(f"Transcript (final={is_final}): {transcript}, Timestamp: {timestamp_ms}ms") 