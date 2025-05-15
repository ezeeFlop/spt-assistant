# Placeholder for VAD and STT logic (now with streaming enhancements)
# This file will contain the AudioProcessor class/functions

import torch
#import whisperx # Replaced faster_whisper
from faster_whisper import WhisperModel

import numpy as np
from typing import Iterator, List, Dict, Any, Optional, Callable, Tuple
from collections import deque # Added deque
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

# VAD processing window size in samples.
# 512 samples = 32ms at 16kHz. This is a common choice for Silero VAD.
VAD_WINDOW_SIZE_SAMPLES = 512

# Pre-roll amount in ms (how much audio we include before "start" is triggered)
PRE_ROLL_MS = 150

# Minimum duration of accumulated audio to be considered a "proper speech start"
# This also serves as a minimum for an utterance to be transcribed.
MIN_DURATION_FOR_PROPER_START_S = 0.75

class AudioProcessor:
    def __init__(self):
        self.logger = get_logger(__name__) # Initialize instance logger
        self.logger.info("Initializing AudioProcessor (whisperx & VADIterator pattern)...")
        self.audio_buffer = np.array([], dtype=np.float32)
        
        # VAD and STT should operate at the same configured sample rate
        self.target_sample_rate = worker_settings.VAD_SAMPLING_RATE # VAD and STT expect this rate
        self.logger.info(f"Target sample rate set to: {self.target_sample_rate} Hz")

        # VAD Model and VADIterator
        self.vad_model, vad_utils = self._load_vad_model()
        if self.vad_model is None or vad_utils is None:
            self.logger.error("Failed to load Silero VAD model or its utilities.")
            raise RuntimeError("VAD model loading failed.")
        
        try:
            # Unpack VADIterator specifically if it's a class, or store utils if VADIterator is created differently
            # Assuming VADIterator is a class within utils that needs the model
            if hasattr(vad_utils, 'VADIterator'):
                self.vad_iterator = vad_utils.VADIterator(self.vad_model, sampling_rate=self.target_sample_rate) # Pass sampling_rate if accepted
            else: # Fallback: get_speech_timestamps etc. are directly in utils
                 # This branch means the example pattern VADIterator(model) might be what we need from utils
                 # Let's assume vad_utils itself might contain VADIterator or we get it from torch.hub differently
                 # For now, if 'VADIterator' is not a direct attribute, we log an error,
                 # as the new pattern relies on it.
                 # The example pattern shows:
                 # model_vad, utils = torch.hub.load(...)
                 # VADIterator = utils.VADIterator # or similar, depends on silero_vad structure
                 # vad_iterator_instance = VADIterator(model_vad)
                 # Re-evaluating based on common silero-vad usage:
                 # (_ , _ , _, VADIteratorDirect, _) = vad_utils # Often VADIterator is one of the utils items
                 # self.vad_iterator = VADIteratorDirect(self.vad_model, sampling_rate=self.target_sample_rate)
                 # For safety, let's refine _load_vad_model to return VADIterator class directly if possible
                 # Or ensure self.vad_iterator is initialized correctly based on what _load_vad_model returns
                VADIteratorClass = getattr(vad_utils, 'VADIterator', None)
                if VADIteratorClass:
                    self.vad_iterator = VADIteratorClass(self.vad_model, sampling_rate=self.target_sample_rate)
                else:
                    # If VADIterator is directly returned by torch.hub.load as one of the utils like in the example:
                    # (get_speech_timestamps, _, _, VADIterator_class, _) = vad_utils
                    # self.vad_iterator = VADIterator_class(self.vad_model)
                    # This part is tricky without knowing the exact structure of 'utils' from snakers4/silero-vad
                    # We will assume VADIterator is findable and instantiable.
                    # The example code directly gets VADIterator from the utils tuple.
                    # Let's modify _load_vad_model to return the VADIterator *class*
                    if callable(vad_utils) and hasattr(vad_utils, '__name__') and vad_utils.__name__ == 'VADIterator':
                        # This case is unlikely, VADIterator is usually a class from the utils module
                        self.logger.warning("vad_utils seems to be VADIterator class itself. This is unusual.")
                        self.vad_iterator = vad_utils(self.vad_model, sampling_rate=self.target_sample_rate)
                    elif isinstance(vad_utils, tuple) and any(hasattr(item, '__name__') and item.__name__ == 'VADIterator' for item in vad_utils if callable(item)):
                        VADIterator_class_from_tuple = next(item for item in vad_utils if callable(item) and hasattr(item, '__name__') and item.__name__ == 'VADIterator')
                        self.vad_iterator = VADIterator_class_from_tuple(self.vad_model, sampling_rate=self.target_sample_rate)
                    else:
                        self.logger.error("Could not initialize VADIterator from loaded VAD utilities.")
                        raise RuntimeError("VADIterator initialization failed.")

            self.logger.info("Silero VAD model and VADIterator initialized.")
        except Exception as e:
            self.logger.error(f"Error initializing VADIterator: {e}", exc_info=True)
            raise RuntimeError(f"Failed to initialize VADIterator: {e}")

        # STT Model (WhisperX)
        self.logger.info(f"Loading STT model (WhisperX): {worker_settings.STT_MODEL_NAME} on device: {worker_settings.FINAL_STT_DEVICE} with compute_type: {worker_settings.STT_COMPUTE_TYPE}")
        try:
            # Ensure language is set, default to 'en' if not specified or invalid
            stt_language = worker_settings.STT_LANGUAGE if worker_settings.STT_LANGUAGE else "en"
            if len(stt_language) > 2 : # whisperx might expect 2-letter codes for language
                self.logger.warning(f"STT_LANGUAGE '{stt_language}' might be invalid for whisperX, attempting to use its first two letters or defaulting to 'en'.")
                stt_language_code = stt_language[:2].lower()
                # Basic check, whisperx has its own validation.
                if stt_language_code not in ["en", "fr", "es", "de", "it", "ja", "ko", "nl", "pt", "ru", "zh", "ar", "cs", "da", "el", "fi", "he", "hi", "hu", "id", "ms", "no", "pl", "ro", "sk", "sv", "th", "tr", "uk", "vi"]: # Common codes
                     self.logger.warning(f"Derived language code '{stt_language_code}' not in common list, WhisperX might default or error. Original: {stt_language}")
                stt_language = stt_language_code

            self.stt_model = WhisperModel(
                worker_settings.STT_MODEL_NAME,
                device=worker_settings.FINAL_STT_DEVICE,
                compute_type=worker_settings.STT_COMPUTE_TYPE
            )

            # self.stt_model = whisperx.load_model(
            #     worker_settings.STT_MODEL_NAME,
            #     device=worker_settings.FINAL_STT_DEVICE,
            #     compute_type=worker_settings.STT_COMPUTE_TYPE,
            #     language=stt_language if stt_language else None, # Pass None if empty to let whisperx use its default multi-language detection.
            #     # asap_options={"model_path": "some_path"} # For custom ASR alignment model path if needed
            #     # hf_token = "YOUR_HF_TOKEN" # If models are gated on Hugging Face
            # )
            self.stt_batch_size = getattr(worker_settings, 'STT_BATCH_SIZE', 16) # From example or config
            self.logger.info(f"WhisperX STT model loaded successfully. Language: {stt_language if stt_language else 'auto-detect'}. Batch size: {self.stt_batch_size}.")
        except Exception as e:
            self.logger.error(f"Failed to load WhisperX STT model: {e}", exc_info=True)
            raise RuntimeError(f"Failed to load WhisperX STT model: {e}")

        # Audio processing parameters & buffers
        self.frame_duration_ms = (VAD_WINDOW_SIZE_SAMPLES / self.target_sample_rate) * 1000.0
        if self.frame_duration_ms <= 0:
            self.logger.warning("Frame duration is zero or negative, pre-roll calculation might be affected.")
            self.num_pre_roll_frames = 0
        else:
            self.num_pre_roll_frames = int(PRE_ROLL_MS // self.frame_duration_ms)
        
        self.logger.info(f"VAD window: {VAD_WINDOW_SIZE_SAMPLES} samples (~{self.frame_duration_ms:.2f}ms). Pre-roll: {PRE_ROLL_MS}ms ({self.num_pre_roll_frames} frames).")

        self.min_samples_for_proper_start = int(MIN_DURATION_FOR_PROPER_START_S * self.target_sample_rate)

        # Buffers
        self.vad_processing_buffer = np.array([], dtype=np.float32) # Accumulates audio for VAD windowing
        self.ring_buffer = deque(maxlen=self.num_pre_roll_frames) # Stores recent non-speech chunks for pre-roll
        self.utterance_audio_buffer_float32 = np.array([], dtype=np.float32) # Accumulates current utterance including pre-roll

        # State flags
        self.is_speech_triggered = False
        self.proper_start_sent = False # Tracks if "proper_speech_start" has been sent for the current utterance

        self.logger.info("AudioProcessor initialized with whisperx & VADIterator.")

    def close(self):
        self.logger.info("AudioProcessor.close() called. Resetting internal state.")
        self.vad_processing_buffer = np.array([], dtype=np.float32)
        self.ring_buffer.clear()
        self.utterance_audio_buffer_float32 = np.array([], dtype=np.float32)
        self.is_speech_triggered = False
        self.proper_start_sent = False
        # self.vad_iterator.reset_states() # If VADIterator has a reset method
        self.logger.info("AudioProcessor internal state reset on close.")

    def _load_vad_model(self) -> Tuple[Optional[Any], Optional[Any]]:
        """Loads the Silero VAD model and its VADIterator utility class from torch.hub."""
        try:
            model, utils = torch.hub.load(
                repo_or_dir=worker_settings.VAD_MODEL_REPO,
                model=worker_settings.VAD_MODEL_NAME,
                force_reload=False,
                onnx=worker_settings.VAD_ONNX,
                trust_repo=True # Added as per example pattern
            )
            # The example pattern suggests VADIterator is one of the items in the utils tuple.
            # (get_speech_timestamps, save_audio, read_audio, VADIterator_class, collect_chunks) = utils
            # We need to locate VADIterator within 'utils'. This depends on silero-vad's current hubconf.py
            # For simplicity, let's assume utils itself is the tuple and VADIterator is the 4th element
            # This might need adjustment based on the actual structure of 'utils' from the 'snakers4/silero-vad' repo.
            
            # A more robust way to get VADIterator from the utils tuple:
            VADIterator_class = None
            if isinstance(utils, tuple):
                for item in utils:
                    if callable(item) and hasattr(item, '__name__') and item.__name__ == 'VADIterator':
                        VADIterator_class = item
                        break
            
            if VADIterator_class is None:
                # Fallback: Check if utils *is* VADIterator (less likely) or directly has it as an attribute
                if callable(utils) and hasattr(utils, '__name__') and utils.__name__ == 'VADIterator':
                     VADIterator_class = utils
                elif hasattr(utils, 'VADIterator'):
                    VADIterator_class = utils.VADIterator

            if VADIterator_class is None:
                self.logger.error("VADIterator class not found in Silero VAD utilities.")
                return model, None # Return model, but indicate VADIterator part failed

            # Return the model and the VADIterator *class* (or the whole utils if VADIterator needs it)
            # The __init__ will instantiate it.
            # The example `vad_iterator = VADIterator(model_vad)` implies VADIterator is a class.
            return model, VADIterator_class # Return the class to be instantiated
        except Exception as e:
            self.logger.error(f"Error loading Silero VAD model or VADIterator class: {e}", exc_info=True)
            return None, None

    def _convert_pcm_s16le_to_float32(self, pcm_s16le_bytes: bytes) -> np.ndarray:
        """Converts raw PCM S16LE bytes to a NumPy array of float32 samples."""
        if not pcm_s16le_bytes:
            return np.array([], dtype=np.float32)
        
        if len(pcm_s16le_bytes) % 2 != 0:
            self.logger.warning(f"Received PCM S16LE byte string with odd length: {len(pcm_s16le_bytes)}. Truncating last byte.")
            pcm_s16le_bytes = pcm_s16le_bytes[:-1]
            if not pcm_s16le_bytes:
                return np.array([], dtype=np.float32)

        try:
            pcm_int16 = np.frombuffer(pcm_s16le_bytes, dtype=np.int16)
            pcm_float32 = pcm_int16.astype(np.float32) / 32768.0 
            return pcm_float32
        except Exception as e:
            self.logger.error(f"Error converting S16LE PCM bytes to float32: {e}", exc_info=True)
            return np.array([], dtype=np.float32)

    def _resample_audio(self, audio_data: np.ndarray, original_sr: int, target_sr: int) -> np.ndarray:
        """Resamples audio data to the target sample rate if necessary."""
        if original_sr == target_sr:
            return audio_data
        
        self.logger.warning(f"Resampling audio from {original_sr}Hz to {target_sr}Hz. Client should ideally send at {target_sr}Hz.")
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

    def process_audio_chunk(self, raw_pcm_s16le_bytes: bytes) -> Iterator[Dict[str, Any]]:
        decoded_audio_np = self._convert_pcm_s16le_to_float32(raw_pcm_s16le_bytes)

        if decoded_audio_np.size == 0:
            # self.logger.debug("Empty audio chunk after PCM conversion.")
            return

        # Assuming client sends at target_sample_rate, or _resample_audio would be called here.
        # For simplicity, not adding resampling in this loop, relying on __init__ check or upstream handling.

        self.vad_processing_buffer = np.concatenate((self.vad_processing_buffer, decoded_audio_np))

        while len(self.vad_processing_buffer) >= VAD_WINDOW_SIZE_SAMPLES:
            current_vad_chunk = self.vad_processing_buffer[:VAD_WINDOW_SIZE_SAMPLES]
            self.vad_processing_buffer = self.vad_processing_buffer[VAD_WINDOW_SIZE_SAMPLES:]

            try:
                # VADIterator processes chunk by chunk and maintains its own state.
                # It expects audio chunks of fixed size (e.g., 30ms for 16kHz -> 480 samples, 32ms -> 512 samples)
                # The output 'speech_dict' contains 'start' or 'end' keys if speech segment boundaries are detected.
                speech_dict = self.vad_iterator(current_vad_chunk, return_seconds=False) # Pass return_seconds=False as per example
            except Exception as e:
                self.logger.error(f"Error during VADIterator processing: {e}", exc_info=True)
                yield {"event_type": "error", "message": "VAD processing error", "details": str(e), "timestamp_ms": time.time() * 1000}
                # Potentially reset VAD state if possible: self.vad_iterator.reset_states()
                continue # Skip to next chunk processing attempt


            is_speech_start = speech_dict is not None and 'start' in speech_dict
            is_speech_end = speech_dict is not None and 'end' in speech_dict
            
            # Handling VAD events and managing utterance buffer
            if is_speech_start and not self.is_speech_triggered:
                self.logger.debug(f"VAD start detected at sample (relative to chunk): {speech_dict['start'] if speech_dict else 'N/A'}")
                self.is_speech_triggered = True
                self.proper_start_sent = False # Reset for new utterance
                
                # Prepend audio from ring_buffer to utterance_audio_buffer
                if self.ring_buffer:
                    # self.logger.debug(f"Prepending {len(self.ring_buffer)} pre-roll chunks.")
                    pre_roll_audio_list = list(self.ring_buffer)
                    if pre_roll_audio_list: # Ensure not empty after conversion
                        full_pre_roll_audio = np.concatenate(pre_roll_audio_list)
                        self.utterance_audio_buffer_float32 = np.concatenate((full_pre_roll_audio, self.utterance_audio_buffer_float32))
                    self.ring_buffer.clear()
            
            if self.is_speech_triggered:
                # Append current VAD chunk to the utterance buffer
                # Note: VAD 'start' might be *within* current_vad_chunk.
                # For simplicity, we append the whole chunk when triggered.
                # More precise would be to use speech_dict['start'] offset if it refers to current_vad_chunk.
                # However, silero-vad's VADIterator typically signals start *after* enough speech is in its internal buffer.
                self.utterance_audio_buffer_float32 = np.concatenate((self.utterance_audio_buffer_float32, current_vad_chunk))
                self.logger.info("Barge-in start detected.")
                yield {"event_type": "vad_event", "status": "barge_in_start", "timestamp_ms": time.time() * 1000}
                # Check for "proper speech start"
                if len(self.utterance_audio_buffer_float32) >= self.min_samples_for_proper_start and not self.proper_start_sent:
                    self.logger.info("Proper speech start detected.")
                    yield {"event_type": "vad_event", "status": "proper_speech_start", "timestamp_ms": time.time() * 1000}
                    self.proper_start_sent = True
            else: # Not triggered (i.e., silence or before speech starts)
                self.ring_buffer.append(current_vad_chunk)

            if is_speech_end and self.is_speech_triggered:
                self.logger.debug(f"VAD end detected at sample (relative to chunk): {speech_dict['end'] if speech_dict else 'N/A'}")
                self.is_speech_triggered = False # Speech has ended for now

                # Process the accumulated utterance
                if len(self.utterance_audio_buffer_float32) >= self.min_samples_for_proper_start: # Using min_samples_for_proper_start as STT min length
                    self.logger.info(f"Attempting to transcribe utterance of {len(self.utterance_audio_buffer_float32)/self.target_sample_rate:.2f}s.")
                    try:
                        # WhisperX transcribe expects audio as float32 numpy array
                        # Align audio first if word timestamps are crucial and an alignment model is available/configured
                        # result = self.stt_model.align(audio_float32, result, device=self.stt_device)
                        
                        # Direct transcription
                        # Ensure utterance_audio_buffer_float32 is C-contiguous if whisperX requires
                        audio_to_transcribe = np.ascontiguousarray(self.utterance_audio_buffer_float32)
                        
                       #transcription_result = self.stt_model.transcribe(
                       #     audio_to_transcribe,
                       #     batch_size=self.stt_batch_size
                       #     # chunk_size = for long audio, but here utterance should be relatively short
                       # )
                        transcription_result, info = self.stt_model.transcribe(
                            audio_to_transcribe,
                            beam_size=self.stt_batch_size,
                            language=worker_settings.STT_LANGUAGE,
                            word_timestamps=True,

                            # chunk_size = for long audio, but here utterance should be relatively short
                        )
                        
                        #full_text = "".join(segment["text"] for segment in transcription_result.get("segments", [])).strip()
                        full_text = ""
                        current_transcript_words = []
                        for word_segment in transcription_result: 
                            # self.logger.info(f"STT segment: {word_segment}") # Can be very verbose
                            if not word_segment.words: # Handle cases where Whisper gives text but no word timestamps
                                if word_segment.text.strip(): 
                                    current_transcript_words.append({"word": word_segment.text.strip(), "start": word_segment.start, "end": word_segment.end})
                            else:
                                for word_info in word_segment.words:
                                    current_transcript_words.append({"word": word_info.word, "start": word_info.start, "end": word_info.end})
                        full_text = " ".join([word["word"] for word in current_transcript_words])



                        if full_text:
                            self.logger.info(f"Transcription result: '{full_text}'")
                            yield {
                                "event_type": "transcript", 
                                "transcript": full_text, 
                                "is_final": True, 
                                "timestamp_ms": time.time() * 1000,
                            }
                        else:
                            self.logger.info("Transcription resulted in empty text.")
                            # Optionally yield a specific event for empty transcription if needed
                            # yield {"event_type": "vad_event", "status": "empty_transcription", "timestamp_ms": time.time() * 1000}


                    except Exception as e:
                        self.logger.error(f"Error during WhisperX STT processing: {e}", exc_info=True)
                        yield {"event_type": "error", "message": "STT processing error", "details": str(e), "timestamp_ms": time.time() * 1000}
                else:
                    self.logger.info(f"Speech false detection: Utterance too short ({len(self.utterance_audio_buffer_float32)/self.target_sample_rate:.2f}s).")
                    yield {"event_type": "vad_event", "status": "speech_false_detection", "timestamp_ms": time.time() * 1000}
                
                # Reset for next utterance
                self.utterance_audio_buffer_float32 = np.array([], dtype=np.float32)
                self.proper_start_sent = False
                # self.vad_iterator.reset_states() # Reset VAD iterator state after speech end
                # Ring buffer is naturally managed by its maxlen and usage on next speech start.
        
        # If vad_processing_buffer has remaining audio less than VAD_WINDOW_SIZE_SAMPLES, it stays for the next call.

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