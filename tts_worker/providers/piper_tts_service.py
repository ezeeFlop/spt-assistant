import asyncio
import os
from typing import AsyncIterator, Optional, List, Dict
import torch
import torchaudio.transforms as T
import numpy as np

from tts_worker.logging_config import get_logger # Use tts_service logger
from tts_worker.core.tts_abc import AbstractTTSService # Use tts_service ABC

logger = get_logger(__name__)

class PiperTTSService(AbstractTTSService):
    def __init__(
        self,
        executable_path: str,
        voices_dir: str,
        default_voice_model: str,
        native_sample_rate: int,
        target_sample_rate: int
    ):
        self.piper_executable = executable_path
        self.voices_dir = voices_dir
        self.default_voice_model = default_voice_model
        self.native_sample_rate = native_sample_rate
        self.target_sample_rate = target_sample_rate
        
        logger.info(f"Initializing PiperTTSService with executable: {self.piper_executable}, voices_dir: {self.voices_dir}")

        if not os.path.exists(self.piper_executable):
            logger.error(f"Piper TTS executable not found at: {self.piper_executable}")
            raise FileNotFoundError(f"Piper TTS executable not found at: {self.piper_executable}")
        if not os.path.isdir(self.voices_dir):
            logger.warning(f"Piper voices directory not found at: {self.voices_dir}. Voice discovery might fail for relative voice IDs.")

        self.resampler = None
        if self.native_sample_rate != self.target_sample_rate:
            logger.info(f"Initializing resampler from {self.native_sample_rate} Hz to {self.target_sample_rate} Hz")
            try:
                self.resampler = T.Resample(
                    orig_freq=self.native_sample_rate,
                    new_freq=self.target_sample_rate,
                    dtype=torch.float32
                )
            except Exception as e:
                logger.error(f"Failed to initialize resampler: {e}", exc_info=True)
                raise RuntimeError(f"Failed to initialize audio resampler: {e}")
        else:
            print(f"PiperTTS: Resampling not needed (native: {self.native_sample_rate}, target: {self.target_sample_rate}).", flush=True)

        self.current_synthesis_process: Optional[asyncio.subprocess.Process] = None
        self._stop_event: Optional[asyncio.Event] = None

    async def synthesize_stream(self, text_to_speak: str, voice_id: Optional[str] = None, stop_event: Optional[asyncio.Event] = None, **kwargs) -> AsyncIterator[bytes]:
        selected_voice = voice_id or self.default_voice_model
        
        if self.voices_dir and not os.path.isabs(selected_voice) and not selected_voice.startswith(self.voices_dir):
            voice_model_path = os.path.join(self.voices_dir, selected_voice)
        else:
            voice_model_path = selected_voice

        if not voice_model_path.endswith(".onnx"):
             logger.warning(f"Voice model '{voice_model_path}' does not end with .onnx. Attempting to append.")
             voice_model_path += ".onnx"

        voice_config_path = voice_model_path + ".json"

        if not os.path.exists(voice_model_path):
            logger.error(f"Voice model file not found: {voice_model_path}")
            return 
        if not os.path.exists(voice_config_path):
            logger.error(f"Voice model config file not found: {voice_config_path}")
            return

        self._stop_event = stop_event or asyncio.Event()
        
        logger.info(f"PiperTTSService: Synthesizing with Model='{voice_model_path}', Text='{text_to_speak[:50]}...'")
        command = [
            self.piper_executable,
            "--model", voice_model_path,
            "--output-raw",
            "--stdout"
        ]
        speaker_idx = kwargs.get("speaker_idx")
        if speaker_idx is not None:
            command.extend(["--speaker", str(speaker_idx)])
            logger.info(f"Using speaker index: {speaker_idx}")

        self.current_synthesis_process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        process = self.current_synthesis_process

        try:
            if process.stdin:
                process.stdin.write(text_to_speak.encode('utf-8'))
                await process.stdin.drain()
                process.stdin.close()
            
            piper_read_chunk_size = 4096
            if process.stdout:
                while True:
                    if self._stop_event.is_set():
                        logger.info("PiperTTSService stream: Stop event received, terminating Piper.")
                        if process.returncode is None: process.terminate()
                        break 
                    
                    try:
                        raw_piper_chunk = await asyncio.wait_for(process.stdout.read(piper_read_chunk_size), timeout=0.1)
                    except asyncio.TimeoutError: continue 
                    
                    if not raw_piper_chunk: break
                    
                    audio_np_s16le = np.frombuffer(raw_piper_chunk, dtype=np.int16)
                    audio_torch_float32 = torch.from_numpy(audio_np_s16le.astype(np.float32) / np.iinfo(np.int16).max)
                    if audio_torch_float32.ndim == 1: audio_torch_float32 = audio_torch_float32.unsqueeze(0)

                    if self.resampler: resampled_audio_torch_float32 = self.resampler(audio_torch_float32)
                    else: resampled_audio_torch_float32 = audio_torch_float32

                    resampled_audio_np_float32 = resampled_audio_torch_float32.squeeze(0).numpy()
                    resampled_audio_np_s16le = (resampled_audio_np_float32 * np.iinfo(np.int16).max).astype(np.int16)
                    output_chunk_bytes = resampled_audio_np_s16le.tobytes()
                    yield output_chunk_bytes
            
            if process.returncode is None: await process.wait()
        except Exception as e:
            logger.error(f"Error during Piper synthesis stream: {e}", exc_info=True)
            raise
        finally:
            if process and process.returncode is None:
                logger.warning("PiperTTSService stream: Terminating Piper process in finally block.")
                try:
                    process.terminate()
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    logger.warning("Timeout waiting for Piper process to terminate, killing.")
                    process.kill()
                except Exception as e_term:
                    logger.error(f"Error during Piper process termination: {e_term}", exc_info=True)
            self.current_synthesis_process = None

        if process.returncode is not None and process.returncode != 0:
            stderr_output = b''
            if process.stderr and not process.stderr.at_eof(): stderr_output = await process.stderr.read()
            logger.error(f"Piper TTS process failed (exit code {process.returncode}): {stderr_output.decode('utf-8', errors='ignore') if stderr_output else 'No stderr output or already read'}")
        else:
            logger.info(f"Piper TTS synthesis completed/stopped for: '{text_to_speak[:50]}...'")

    async def get_available_voices(self) -> List[Dict[str, str]]:
        voices: List[Dict[str, str]] = []
        if not self.voices_dir or not os.path.isdir(self.voices_dir):
            logger.warning(f"Cannot list Piper voices, directory not found or not configured: {self.voices_dir}")
            return []
        try:
            for filename in os.listdir(self.voices_dir):
                if filename.endswith(".onnx"):
                    voice_id = filename
                    voice_name = os.path.splitext(filename)[0]
                    language_code = voice_id.split('-')[0] if '-' in voice_id else "unknown"
                    voices.append({"id": voice_id, "name": voice_name, "language": language_code, "provider": "piper"})
            logger.info(f"Found {len(voices)} available Piper voices in {self.voices_dir}")
        except OSError as e:
            logger.error(f"Error listing voices in {self.voices_dir}: {e}", exc_info=True)
        return voices

    async def stop_synthesis(self) -> None:
        logger.info("Attempting to stop current Piper TTS synthesis...")
        if self._stop_event: self._stop_event.set() 