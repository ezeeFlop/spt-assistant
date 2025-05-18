import torch
from TTS.api import TTS
import asyncio
import os
from typing import AsyncIterator, Optional, List, Dict, Union
import torch
import torchaudio.transforms as T
import numpy as np

from tts_worker.logging_config import get_logger # Use tts_service logger
from tts_worker.core.tts_abc import AbstractTTSService # Use tts_service ABC

logger = get_logger(__name__)

class CoquiTTSService(AbstractTTSService):
    def __init__(
        self,
        default_model_name: str = "tts_models/multilingual/multi-dataset/xtts_v2",
        default_language: str = "fr",
        native_sample_rate: int = 24000,  # XTTS v2 default, will try to update from model
        target_sample_rate: int = 22050,
    ):
        self.default_model_name = default_model_name
        self.default_language = default_language
        # This will be the configured native_sample_rate, possibly updated by model info
        self._configured_native_sample_rate = native_sample_rate
        self.target_sample_rate = target_sample_rate
        self.tts_instance: Optional[TTS] = None

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Initializing CoquiTTSService on device: {self.device}")
        logger.info(f"Attempting to load default Coqui TTS model: {self.default_model_name}")

        try:
            self.tts_instance = TTS(model_name=self.default_model_name).to(self.device)
            logger.info(f"Successfully loaded Coqui TTS model: {self.default_model_name}")
            
            # Try to determine actual native sample rate from the loaded model
            current_native_sr = self._configured_native_sample_rate
            if hasattr(self.tts_instance, 'synthesizer') and \
               hasattr(self.tts_instance.synthesizer, 'output_sample_rate'):
                current_native_sr = self.tts_instance.synthesizer.output_sample_rate
                logger.info(f"Model's native sample rate (from synthesizer): {current_native_sr} Hz")
            elif hasattr(self.tts_instance, 'config') and \
                 hasattr(self.tts_instance.config, 'audio') and \
                 isinstance(self.tts_instance.config.audio, dict) and \
                 'sample_rate' in self.tts_instance.config.audio:
                current_native_sr = self.tts_instance.config.audio['sample_rate']
                logger.info(f"Model's native sample rate (from config.audio): {current_native_sr} Hz")
            elif hasattr(self.tts_instance, 'model_config') and \
                 hasattr(self.tts_instance.model_config, 'audio') and \
                 isinstance(self.tts_instance.model_config.audio, dict) and \
                 'sample_rate' in self.tts_instance.model_config.audio: # XTTS specific path often
                current_native_sr = self.tts_instance.model_config.audio['sample_rate']
                logger.info(f"Model's native sample rate (from model_config.audio): {current_native_sr} Hz")
            else:
                logger.warning(f"Could not automatically determine native sample rate for {self.default_model_name}. Using configured value: {self._configured_native_sample_rate} Hz.")
            self.native_sample_rate = current_native_sr

        except Exception as e:
            logger.error(f"Failed to initialize Coqui TTS model ({self.default_model_name}): {e}", exc_info=True)
            # Allow initialization to somewhat complete so service doesn't crash worker, but it won't work.
            # synthesize_stream and get_available_voices should handle self.tts_instance being None.
            self.tts_instance = None # Ensure it's None on failure
            self.native_sample_rate = self._configured_native_sample_rate # Use configured if model load fails

        if self.tts_instance and hasattr(self.tts_instance, 'speakers') and self.tts_instance.speakers:
            logger.info(f"Available internal speakers for {self.default_model_name}: {self.tts_instance.speakers}")
        elif self.tts_instance:
            logger.info(f"Model {self.default_model_name} loaded, but no internal speakers listed (or speaker list is empty).")

        self.resampler = None
        if self.native_sample_rate != self.target_sample_rate:
            logger.info(f"Initializing resampler from {self.native_sample_rate} Hz to {self.target_sample_rate} Hz")
            try:
                self.resampler = T.Resample(
                    orig_freq=self.native_sample_rate,
                    new_freq=self.target_sample_rate,
                    dtype=torch.float32  # Coqui typically outputs float32
                )
            except Exception as e:
                logger.error(f"Failed to initialize resampler: {e}", exc_info=True)
                self.resampler = None # Proceed without resampling if it fails
        else:
            logger.info(f"CoquiTTS: Resampling not needed (native: {self.native_sample_rate}, target: {self.target_sample_rate}).")

        self._stop_event: Optional[asyncio.Event] = None
        # No external process for Coqui Python API, so current_synthesis_process is not applicable in the same way.

    async def synthesize_stream(self, text_to_speak: str, voice_id: Optional[str] = None, language: Optional[str] = None, stop_event: Optional[asyncio.Event] = None, **kwargs) -> AsyncIterator[bytes]:
        if not self.tts_instance:
            logger.error("Coqui TTS instance not available. Synthesis cannot proceed.")
            return

        self._stop_event = stop_event or asyncio.Event()
        
        tts_params: Dict[str, Union[str, bool, float]] = {"text": text_to_speak}
        selected_language = language or self.default_language
        if selected_language: # Ensure language is only passed if not None/empty
            tts_params["language"] = selected_language

        # speaker_wav_path: Optional[str] = None # Not strictly needed as a separate var
        potential_speaker_name: Optional[str] = None

        if voice_id:
            if os.path.isfile(voice_id) and voice_id.lower().endswith((".wav", ".mp3", ".flac")):
                logger.info(f"Using speaker_wav for voice cloning: {voice_id}")
                tts_params["speaker_wav"] = voice_id
            else:
                # Not a file path, so treat as a potential speaker identifier
                # Check if it's a composite ID like model_name::speaker_name
                composite_id_parts = voice_id.split("::", 1)
                if len(composite_id_parts) == 2 and composite_id_parts[0] == self.default_model_name:
                    # It's a composite ID for the current model
                    potential_speaker_name = composite_id_parts[1]
                    logger.info(f"Parsed speaker name '{potential_speaker_name}' from composite ID '{voice_id}'")
                else:
                    # Treat as a direct speaker name
                    potential_speaker_name = voice_id

                if potential_speaker_name and self.tts_instance and hasattr(self.tts_instance, 'speakers') and self.tts_instance.speakers:
                    if potential_speaker_name in self.tts_instance.speakers:
                        logger.info(f"Using internal speaker name: {potential_speaker_name}")
                        tts_params["speaker"] = potential_speaker_name
                    else:
                        logger.warning(
                            f"Provided speaker identifier '{potential_speaker_name}' (from voice_id '{voice_id}') "
                            f"is not in the known internal speaker list for model {self.default_model_name} ({self.tts_instance.speakers}). "
                            f"Synthesis will proceed without this specific 'speaker' argument, relying on defaults or speaker_wav if set."
                        )
                elif potential_speaker_name:
                     logger.warning(
                        f"Provided speaker identifier '{potential_speaker_name}' (from voice_id '{voice_id}'), "
                        f"but the loaded model {self.default_model_name} has no enumerable speakers or speakers attribute. "
                        f"Cannot validate. Will attempt to pass to Coqui if model handles it, or rely on speaker_wav/defaults."
                    )
                    # Potentially still pass it if the model might handle it in a non-standard way, though XTTS expects known speakers.
                    # For XTTS, if it's not a known speaker, it would error. So, it's safer not to set tts_params["speaker"] here
                    # unless it was validated against self.tts_instance.speakers.

        # If no voice_id, or if voice_id was unrecognized or not a file,
        # tts_params["speaker"] might not be set. Coqui will use defaults.
        # If voice_id was a file, tts_params["speaker_wav"] is set.
        # XTTS can work with:
        # 1. 'speaker_wav' + 'language'
        # 2. 'speaker' (internal name) + 'language'
        # 3. Just 'language' (uses a default voice for that language)
        
        # Handle specific kwargs for Coqui, e.g., split_sentences for XTTS
        if "split_sentences" in kwargs:
            tts_params["split_sentences"] = bool(kwargs["split_sentences"])
        if "emotion" in kwargs and isinstance(kwargs["emotion"], str): # XTTS supports emotion
             tts_params["emotion"] = kwargs["emotion"]
        if "speed" in kwargs: # XTTS supports speed
            try:
                tts_params["speed"] = float(kwargs["speed"])
            except ValueError:
                logger.warning(f"Invalid speed value: {kwargs['speed']}. Ignoring.")


        logger.info(f"CoquiTTSService: Synthesizing with params: {tts_params}, Text='{text_to_speak[:50]}...'")

        try:
            if self._stop_event.is_set():
                logger.info("CoquiTTSService stream: Stop event received before synthesis.")
                return

            loop = asyncio.get_event_loop()
            # Coqui tts.tts() can be blocking. Run in executor.
            # It returns a list of float audio samples (waveform)
            raw_audio_data = await loop.run_in_executor(None, lambda: self.tts_instance.tts(**tts_params)) # type: ignore

            if self._stop_event.is_set(): # Check immediately after blocking call
                logger.info("CoquiTTSService stream: Stop event received after synthesis completed but before streaming.")
                return

            if not raw_audio_data:
                logger.error("Coqui TTS returned no audio data.")
                return

            if isinstance(raw_audio_data, list):
                audio_np_float32 = np.array(raw_audio_data, dtype=np.float32)
            elif isinstance(raw_audio_data, np.ndarray):
                audio_np_float32 = raw_audio_data.astype(np.float32)
            else:
                logger.error(f"Unexpected audio data type from Coqui TTS: {type(raw_audio_data)}")
                return
            
            # Ensure it's 1D before unsqueezing
            if audio_np_float32.ndim > 1:
                 audio_np_float32 = audio_np_float32.squeeze() # Remove extra dims if any, assume mono focus
            if audio_np_float32.ndim == 0: # Handle scalar case if it ever occurs
                logger.error("Audio data is scalar, cannot process.")
                return


            audio_torch_float32 = torch.from_numpy(audio_np_float32).to(self.device)
            if audio_torch_float32.ndim == 1:
                audio_torch_float32 = audio_torch_float32.unsqueeze(0)  # Add channel dim for resampler [C, T]

            if self.resampler:
                # Resampler expects [C, T] or [B, C, T]
                resampled_audio_torch_float32 = self.resampler(audio_torch_float32)
            else:
                resampled_audio_torch_float32 = audio_torch_float32

            resampled_audio_np_float32 = resampled_audio_torch_float32.squeeze(0).cpu().numpy()
            
            # Normalize to [-1, 1] if not already, then convert to int16
            # Coqui TTS output is generally expected to be normalized.
            # Max value check to prevent clipping very quiet audio if it's not normalized
            max_val = np.max(np.abs(resampled_audio_np_float32))
            if max_val > 1.0: # If data is not in [-1, 1], normalize it
                logger.warning(f"Audio data not in [-1,1] range (max abs: {max_val}). Normalizing.")
                resampled_audio_np_float32 = resampled_audio_np_float32 / max_val
            elif max_val == 0: # All zero audio
                 logger.warning("Audio data is all zeros.") # Avoid division by zero if all zeros

            audio_np_s16le = (resampled_audio_np_float32 * np.iinfo(np.int16).max).astype(np.int16)
            output_bytes = audio_np_s16le.tobytes()

            chunk_size = 4096  # Bytes per chunk
            for i in range(0, len(output_bytes), chunk_size):
                if self._stop_event.is_set():
                    logger.info("CoquiTTSService stream: Stop event received during chunking.")
                    break
                chunk = output_bytes[i:i + chunk_size]
                yield chunk
                await asyncio.sleep(0.001) # Slight yield to allow other tasks

        except RuntimeError as e: # Catch PyTorch/CUDA runtime errors
             logger.error(f"Runtime error during Coqui TTS synthesis: {e}", exc_info=True)
             raise # Re-raise to signal failure
        except Exception as e:
            logger.error(f"Error during Coqui TTS synthesis stream: {e}", exc_info=True)
            raise # Re-raise to signal failure
        finally:
            logger.info(f"Coqui TTS synthesis stream finished or stopped for: '{text_to_speak[:50]}...'")

    async def get_available_voices(self) -> List[Dict[str, str]]:
        voices: List[Dict[str, str]] = []
        try:
            # TTS().list_models() might be slow if it involves network I/O or heavy parsing.
            # Consider caching or alternative if this is too slow for frequent calls.
            # For now, direct call.
            model_manager_output = TTS().list_models()

            def _parse_model_list_from_dict(data_dict: Dict, model_type_prefix: str) -> List[str]:
                parsed_list = []
                for lang_code, datasets in data_dict.items():
                    if isinstance(datasets, dict):
                        for dataset_name, model_names_list in datasets.items():
                            if isinstance(model_names_list, list):
                                for model_variant_name in model_names_list:
                                    parsed_list.append(f"{model_type_prefix}/{lang_code}/{dataset_name}/{model_variant_name}")
                return parsed_list

            tts_model_names: List[str] = []
            if isinstance(model_manager_output, dict):
                if "tts_models" in model_manager_output and isinstance(model_manager_output["tts_models"], dict):
                    tts_model_names.extend(_parse_model_list_from_dict(model_manager_output["tts_models"], "tts_models"))
                # Could also parse "voice_conversion_models", etc. if desired
            elif isinstance(model_manager_output, list): # Old format
                 tts_model_names = [m for m in model_manager_output if isinstance(m, str)]
            else:
                logger.warning(f"TTS().list_models() returned an unexpected structure: {type(model_manager_output)}.")

            for model_full_name in tts_model_names:
                lang_from_name = "unknown"
                name_to_display = model_full_name
                parts = model_full_name.split('/')
                if len(parts) > 2 and parts[0] == "tts_models":
                    lang_from_name = parts[1]
                    name_to_display = "/".join(parts[1:]) 
                
                voices.append({
                    "id": model_full_name, 
                    "name": name_to_display, 
                    "language": lang_from_name, 
                    "provider": "coqui"
                })
            
            # Add speakers from the currently loaded default model, if any and if it has speakers
            if self.tts_instance and self.tts_instance.speakers:
                loaded_model_base_name = self.default_model_name.replace("tts_models/", "")
                
                # Determine language of the loaded model
                model_lang = self.default_language # Fallback
                if hasattr(self.tts_instance, 'language') and self.tts_instance.language: # XTTS has this
                    model_lang = self.tts_instance.language
                elif hasattr(self.tts_instance, 'model_name') and self.tts_instance.model_name:
                    m_parts = self.tts_instance.model_name.split('/')
                    if len(m_parts) > 2 and m_parts[0] == "tts_models":
                        model_lang = m_parts[1]
                
                for speaker_name in self.tts_instance.speakers:
                    speaker_id = f"{self.default_model_name}::{speaker_name}"
                    voices.append({
                        "id": speaker_id,
                        "name": f"{loaded_model_base_name} - {speaker_name}",
                        "language": model_lang,
                        "provider": "coqui"
                    })

            logger.info(f"Found {len(voices)} available Coqui TTS models/speakers.")
        except Exception as e:
            logger.error(f"Error listing Coqui TTS models/speakers: {e}", exc_info=True)
            # Return empty list on error, but log it.
        return voices

    async def stop_synthesis(self) -> None:
        logger.info("Attempting to stop current Coqui TTS synthesis stream...")
        if self._stop_event:
            self._stop_event.set()
        # This primarily affects the chunking loop in synthesize_stream.
        # It won't interrupt a Coqui tts.tts() call that is already in progress in the executor. 