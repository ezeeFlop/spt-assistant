"""Audio processing module for the SPT Assistant Python client."""

import asyncio
import logging
import numpy as np
import pyaudio
import threading
import time
from collections import deque
from typing import Callable, Optional, List, Any
from scipy import signal
import adaptfilt

from .config import settings


logger = logging.getLogger(__name__)


class AudioProcessor:
    """Handles audio capture, processing, and playback exactly like browser getUserMedia."""
    
    def __init__(self, on_audio_chunk: Callable[[bytes], None], on_playback_finished: Optional[Callable[[], None]] = None):
        self.on_audio_chunk = on_audio_chunk
        self.on_playback_finished = on_playback_finished
        self.pyaudio_instance = pyaudio.PyAudio()
        
        # Audio streams
        self.input_stream: Optional[pyaudio.Stream] = None
        self.output_stream: Optional[pyaudio.Stream] = None
        
        # Recording state
        self.is_recording = False
        self.recording_thread: Optional[threading.Thread] = None
        
        # Playback state
        self.is_playing = False
        self.playback_queue = deque()
        self.playback_thread: Optional[threading.Thread] = None
        self.playback_lock = threading.Lock()
        self.stream_ended = False  # Flag to indicate if the stream has ended
        self.last_audio_time = 0.0  # Track when we last received audio
        
        # Audio level monitoring
        self.mic_audio_level = 0.0
        self.playback_audio_level = 0.0
        
        # Volume control
        self.output_volume = settings.OUTPUT_VOLUME  # 0.0 to 2.0 (200% max)
        
        # Audio processing
        self.audio_buffer = np.array([], dtype=np.float32)
        
        # Sample rate tracking for resampling
        self.original_sample_rate = 16000  # Default
        self.target_sample_rate = 16000    # Default
        self.playback_channels = 1         # Default
        
        # Get default devices
        self.default_input_device = self.pyaudio_instance.get_default_input_device_info()
        self.default_output_device = self.pyaudio_instance.get_default_output_device_info()
        
        logger.info("AudioProcessor initialized with system-level echo cancellation")
        logger.info(f"Default input device: {self.default_input_device['name']}")
        logger.info(f"Default output device: {self.default_output_device['name']}")
    
    def list_audio_devices(self) -> List[dict]:
        """List available audio devices with enhanced information."""
        devices = []
        for i in range(self.pyaudio_instance.get_device_count()):
            try:
                device_info = self.pyaudio_instance.get_device_info_by_index(i)
                devices.append({
                    'index': i,
                    'name': device_info['name'],
                    'max_input_channels': device_info['maxInputChannels'],
                    'max_output_channels': device_info['maxOutputChannels'],
                    'default_sample_rate': device_info['defaultSampleRate'],
                    'is_default_input': i == self.default_input_device['index'],
                    'is_default_output': i == self.default_output_device['index'],
                    'host_api': device_info['hostApi']
                })
            except Exception as e:
                logger.warning(f"Could not get info for device {i}: {e}")
        return devices
    
    def get_best_output_device(self) -> Optional[int]:
        """Find the best available output device."""
        devices = self.list_audio_devices()
        
        # First try the configured device
        if settings.OUTPUT_DEVICE_INDEX is not None:
            for device in devices:
                if device['index'] == settings.OUTPUT_DEVICE_INDEX and device['max_output_channels'] > 0:
                    logger.info(f"Using configured output device: {device['name']}")
                    return device['index']
        
        # Try default output device
        for device in devices:
            if device['is_default_output'] and device['max_output_channels'] > 0:
                logger.info(f"Using default output device: {device['name']}")
                return device['index']
        
        # Find any device with output channels
        for device in devices:
            if device['max_output_channels'] > 0:
                logger.info(f"Using available output device: {device['name']}")
                return device['index']
        
        logger.error("No suitable output device found")
        return None
    
    def set_output_volume(self, volume: float):
        """Set output volume (0.0 to 2.0)."""
        self.output_volume = max(0.0, min(2.0, volume))
        logger.info(f"Output volume set to {self.output_volume:.2f}")
    
    def start_recording(self, device_index: Optional[int] = None) -> bool:
        """Start recording audio with system-level echo cancellation (like browser getUserMedia)."""
        if self.is_recording:
            logger.warning("Recording already in progress")
            return False
        
        try:
            # Use provided device or configured device or default
            input_device = device_index or settings.INPUT_DEVICE_INDEX
            
            # Configure input stream exactly like browser getUserMedia with:
            # echoCancellation: true, noiseSuppression: true, autoGainControl: true
            # This relies on the system's built-in audio processing
            self.input_stream = self.pyaudio_instance.open(
                format=pyaudio.paInt16,  # 16-bit
                channels=settings.CHANNELS,
                rate=settings.SAMPLE_RATE,
                input=True,
                input_device_index=input_device,
                frames_per_buffer=settings.CHUNK_SIZE,
                stream_callback=self._audio_input_callback,
                # Let the system handle echo cancellation, noise suppression, and AGC
                # This is equivalent to browser's getUserMedia with audio processing enabled
            )
            
            self.is_recording = True
            self.input_stream.start_stream()
            
            device_name = "default"
            if input_device is not None:
                try:
                    device_info = self.pyaudio_instance.get_device_info_by_index(input_device)
                    device_name = device_info['name']
                except:
                    pass
            
            logger.info(f"Started recording audio at {settings.SAMPLE_RATE}Hz on device: {device_name}")
            logger.info("Using system's built-in audio processing (echo cancellation, noise suppression, AGC)")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start recording: {e}")
            return False
    
    def stop_recording(self):
        """Stop recording audio."""
        if not self.is_recording:
            return
        
        self.is_recording = False
        
        if self.input_stream:
            self.input_stream.stop_stream()
            self.input_stream.close()
            self.input_stream = None
        
        logger.info("Stopped recording audio")
    
    def _audio_input_callback(self, in_data, frame_count, time_info, status):
        """Callback for audio input stream - system handles echo cancellation."""
        if status:
            logger.warning(f"Audio input status: {status}")
        
        try:
            # Convert bytes to numpy array for level monitoring
            audio_data = np.frombuffer(in_data, dtype=np.int16)
            
            # Calculate audio level for monitoring
            if len(audio_data) > 0:
                rms = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2))
                self.mic_audio_level = min(rms / 32768.0, 1.0)
            
            # Send raw PCM data directly - system already handled echo cancellation
            # This is exactly how browser getUserMedia works
            self.on_audio_chunk(in_data)
            
        except Exception as e:
            logger.error(f"Error in audio input callback: {e}")
            # Fallback to original audio
            self.on_audio_chunk(in_data)
        
        return (None, pyaudio.paContinue)
    
    def start_audio_playback(self, sample_rate: int, channels: int):
        """Start audio playback stream for TTS audio."""
        try:
            if self.output_stream:
                self.stop_audio_playback()
            
            # Get the best output device
            output_device = self.get_best_output_device()
            if output_device is None:
                logger.error("No output device available for playback")
                return
            
            # Reset stream state
            self.stream_ended = False
            self.last_audio_time = time.time()
            
            # Store original sample rate for resampling
            self.original_sample_rate = sample_rate
            self.playback_channels = channels
            
            # Use the original sample rate directly - most modern devices support 24kHz
            # Only resample if absolutely necessary
            supported_rates = [48000, 44100, 24000, 22050, 16000]
            target_sample_rate = sample_rate
            
            # Only resample if the rate is truly unsupported
            if sample_rate not in supported_rates:
                # Find the closest supported rate
                higher_rates = [rate for rate in supported_rates if rate >= sample_rate]
                if higher_rates:
                    target_sample_rate = min(higher_rates)
                else:
                    target_sample_rate = max(supported_rates)
                logger.info(f"Resampling from {sample_rate}Hz to {target_sample_rate}Hz (unsupported rate)")
            else:
                # Use the original rate - no resampling needed
                target_sample_rate = sample_rate
                logger.info(f"Using original sample rate: {sample_rate}Hz")
            
            self.target_sample_rate = target_sample_rate
            
            # Calculate appropriate buffer size for the target sample rate
            # Aim for ~50ms latency
            buffer_duration_ms = 50
            frames_per_buffer = int(target_sample_rate * buffer_duration_ms / 1000)
            # Round to nearest power of 2 for efficiency
            frames_per_buffer = 2 ** int(np.log2(frames_per_buffer) + 0.5)
            frames_per_buffer = max(256, min(frames_per_buffer, 4096))  # Clamp between 256-4096
            
            # Try to open the output stream with error handling
            stream_opened = False
            for attempt_rate in [target_sample_rate] + [r for r in supported_rates if r != target_sample_rate]:
                try:
                    self.output_stream = self.pyaudio_instance.open(
                        format=pyaudio.paInt16,
                        channels=channels,
                        rate=attempt_rate,
                        output=True,
                        output_device_index=output_device,
                        frames_per_buffer=frames_per_buffer
                    )
                    self.target_sample_rate = attempt_rate
                    stream_opened = True
                    logger.info(f"Opened audio stream at {attempt_rate}Hz with buffer size {frames_per_buffer}")
                    break
                except Exception as e:
                    logger.warning(f"Failed to open stream at {attempt_rate}Hz: {e}")
                    continue
            
            if not stream_opened:
                # Last resort: try with default device and no specific parameters
                try:
                    self.output_stream = self.pyaudio_instance.open(
                        format=pyaudio.paInt16,
                        channels=channels,
                        rate=44100,  # Most common fallback
                        output=True,
                        frames_per_buffer=1024
                    )
                    self.target_sample_rate = 44100
                    stream_opened = True
                    logger.info("Opened audio stream with fallback settings (44100Hz)")
                except Exception as e:
                    logger.error(f"Failed to open any audio stream: {e}")
                    return
            
            self.is_playing = True
            
            # Start playback thread
            self.playback_thread = threading.Thread(target=self._playback_worker)
            self.playback_thread.daemon = True
            self.playback_thread.start()
            
            device_name = "default"
            if output_device is not None:
                try:
                    device_info = self.pyaudio_instance.get_device_info_by_index(output_device)
                    device_name = device_info['name']
                except:
                    pass
            
            logger.info(f"Started audio playback at {self.target_sample_rate}Hz, {channels} channels on device: {device_name}")
            logger.info(f"Output volume: {self.output_volume:.2f}")
            if self.original_sample_rate != self.target_sample_rate:
                logger.info(f"Will resample audio chunks from {self.original_sample_rate}Hz to {self.target_sample_rate}Hz")
            else:
                logger.info(f"No resampling needed - using native {self.original_sample_rate}Hz")
            
        except Exception as e:
            logger.error(f"Failed to start audio playback: {e}")
    
    def enqueue_audio_chunk(self, audio_data: bytes):
        """Add audio chunk to playback queue."""
        with self.playback_lock:
            self.playback_queue.append(audio_data)
            self.last_audio_time = time.time()  # Update last audio time
            # Reset stream_ended flag when we receive new audio
            self.stream_ended = False
            logger.debug(f"Enqueued audio chunk: {len(audio_data)} bytes, queue size: {len(self.playback_queue)}")
    
    def signal_stream_ended(self):
        """Signal that the audio stream has ended - playback will stop when queue is empty."""
        self.stream_ended = True
        logger.debug("Audio stream end signaled - will stop when queue is empty")
    
    def stop_audio_playback(self):
        """Stop audio playback and clear queue."""
        self.is_playing = False
        self.stream_ended = False  # Reset stream state
        
        # Wait a moment for the playback thread to finish current chunk
        import time
        time.sleep(0.05)
        
        with self.playback_lock:
            queue_size = len(self.playback_queue)
            self.playback_queue.clear()
            if queue_size > 0:
                logger.debug(f"Cleared {queue_size} audio chunks from queue")
        
        # Stop the playback thread first
        if self.playback_thread and self.playback_thread.is_alive():
            self.playback_thread.join(timeout=2.0)
            if self.playback_thread.is_alive():
                logger.warning("Playback thread did not stop gracefully")
        
        # Then stop the audio stream
        if self.output_stream:
            try:
                # Check if stream is still active before stopping
                if self.output_stream.is_active():
                    self.output_stream.stop_stream()
                if not self.output_stream.is_stopped():
                    time.sleep(0.01)  # Brief pause
                self.output_stream.close()
            except Exception as e:
                logger.warning(f"Error stopping output stream: {e}")
            finally:
                self.output_stream = None
        
        logger.info("Stopped audio playback")
    
    def _playback_worker(self):
        """Worker thread for audio playback."""
        logger.info("Playback worker started")
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while self.is_playing:
            try:
                with self.playback_lock:
                    if self.playback_queue:
                        audio_chunk = self.playback_queue.popleft()
                    else:
                        audio_chunk = None
                
                if audio_chunk and self.output_stream:
                    try:
                        # Convert bytes to numpy array
                        audio_data = np.frombuffer(audio_chunk, dtype=np.int16)
                        
                        # Only resample if sample rates are actually different
                        if (hasattr(self, 'original_sample_rate') and hasattr(self, 'target_sample_rate') 
                            and self.original_sample_rate != self.target_sample_rate):
                            # Convert to float for resampling
                            audio_float = audio_data.astype(np.float32) / 32768.0
                            
                            # Resample
                            resampled = AudioResampler.resample_audio(
                                audio_float, 
                                self.original_sample_rate, 
                                self.target_sample_rate
                            )
                            
                            # Convert back to int16
                            audio_data = (resampled * 32767).astype(np.int16)
                            logger.debug(f"Resampled audio chunk from {self.original_sample_rate}Hz to {self.target_sample_rate}Hz")
                        
                        # Apply volume control
                        if self.output_volume != 1.0:
                            # Apply volume scaling
                            audio_data = audio_data.astype(np.float32) * self.output_volume
                            # Clip to prevent overflow
                            audio_data = np.clip(audio_data, -32768, 32767).astype(np.int16)
                        
                        # Calculate playback audio level
                        if len(audio_data) > 0:
                            rms = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2))
                            self.playback_audio_level = min(rms / 32768.0, 1.0)
                        
                        # Convert back to bytes
                        audio_chunk = audio_data.tobytes()
                        
                        # Play audio chunk with retry logic
                        try:
                            # Check if we should stop before writing
                            if not self.is_playing:
                                break
                                
                            # Check if stream is still valid
                            if not self.output_stream or self.output_stream.is_stopped():
                                logger.debug("Output stream stopped, ending playback")
                                break
                                
                            self.output_stream.write(audio_chunk)
                            logger.debug(f"Played audio chunk: {len(audio_chunk)} bytes")
                            consecutive_errors = 0  # Reset error count on success
                        except Exception as e:
                            consecutive_errors += 1
                            
                            # Check if this is just because we're stopping
                            if not self.is_playing:
                                logger.debug("Playback stopped during write, exiting gracefully")
                                break
                            
                            logger.error(f"Error writing to output stream (attempt {consecutive_errors}): {e}")
                            
                            if consecutive_errors >= max_consecutive_errors:
                                logger.error("Too many consecutive audio errors, stopping playback")
                                break
                            
                            # Try to recover by recreating the stream (but only if we're still supposed to be playing)
                            if consecutive_errors == 3 and self.is_playing:
                                logger.info("Attempting to recover audio stream...")
                                try:
                                    if self.output_stream:
                                        self.output_stream.close()
                                    # Recreate stream with current settings
                                    self.output_stream = self.pyaudio_instance.open(
                                        format=pyaudio.paInt16,
                                        channels=self.playback_channels,
                                        rate=self.target_sample_rate,
                                        output=True,
                                        frames_per_buffer=1024
                                    )
                                    logger.info("Audio stream recovered")
                                except Exception as recovery_error:
                                    logger.error(f"Failed to recover audio stream: {recovery_error}")
                                    break
                            
                            # Small delay before retry
                            time.sleep(0.01)
                            
                    except Exception as e:
                        logger.error(f"Error processing audio chunk: {e}")
                        consecutive_errors += 1
                        if consecutive_errors >= max_consecutive_errors:
                            break
                else:
                    # No audio to play, check if we should stop
                    current_time = time.time()
                    time_since_last_audio = current_time - self.last_audio_time
                    
                    if self.stream_ended and not self.playback_queue:
                        # Stream has ended and queue is empty
                        # Wait a bit longer in case more audio streams are coming
                        if time_since_last_audio > 1.0:  # 1 second timeout
                            logger.info("Stream ended, queue empty, and timeout reached - stopping playback naturally")
                            # Set is_playing to False before calling callback
                            logger.info("Setting is_playing=False due to timeout, calling playback finished callback")
                            self.is_playing = False
                            # Notify that playback has finished
                            if self.on_playback_finished:
                                try:
                                    self.on_playback_finished()
                                except Exception as e:
                                    logger.error(f"Error in playback finished callback: {e}")
                            break
                        else:
                            logger.debug(f"Stream ended but waiting for potential new streams (waited {time_since_last_audio:.2f}s)")
                    
                    # Sleep briefly and continue waiting for more audio
                    time.sleep(0.01)
                    
            except Exception as e:
                logger.error(f"Error in playback worker: {e}")
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    break
                time.sleep(0.1)  # Longer delay for general errors
        
        # Ensure is_playing is set to False when worker exits (for any reason)
        logger.info("Playback worker exiting, setting is_playing=False")
        self.is_playing = False
        logger.info("Playback worker stopped")
    
    def get_audio_levels(self) -> tuple[float, float]:
        """Get current microphone and playback audio levels."""
        return self.mic_audio_level, self.playback_audio_level
    
    def test_audio_output(self):
        """Test audio output by playing a simple tone."""
        try:
            logger.info("Testing audio output...")
            
            # Generate a 1-second 440Hz sine wave
            sample_rate = 44100  # Use a common sample rate for testing
            duration = 1.0
            frequency = 440.0
            
            t = np.linspace(0, duration, int(sample_rate * duration), False)
            tone = np.sin(2 * np.pi * frequency * t) * 0.3  # 30% volume
            
            # Convert to 16-bit PCM
            tone_pcm = (tone * 32767).astype(np.int16)
            
            # Start playback
            self.start_audio_playback(sample_rate, 1)
            
            if not self.output_stream:
                logger.error("Failed to start audio playback for test")
                return
            
            # Enqueue the tone in smaller chunks for smoother playback
            chunk_size = 2048
            for i in range(0, len(tone_pcm), chunk_size):
                chunk = tone_pcm[i:i + chunk_size]
                self.enqueue_audio_chunk(chunk.tobytes())
                # Small delay to prevent overwhelming the queue
                time.sleep(0.01)
            
            # Wait for playback to finish
            time.sleep(duration + 0.5)
            self.stop_audio_playback()
            
            logger.info("Audio output test completed")
            
        except Exception as e:
            logger.error(f"Audio output test failed: {e}")
            # Make sure to stop playback even if test fails
            try:
                self.stop_audio_playback()
            except:
                pass
    
    def close(self):
        """Clean up audio resources."""
        self.stop_recording()
        self.stop_audio_playback()
        
        if self.pyaudio_instance:
            self.pyaudio_instance.terminate()
        
        logger.info("AudioProcessor closed")


class AudioResampler:
    """Utility class for audio resampling."""
    
    @staticmethod
    def resample_audio(audio_data: np.ndarray, original_sr: int, target_sr: int) -> np.ndarray:
        """Resample audio data to target sample rate."""
        if original_sr == target_sr:
            return audio_data
        
        # Calculate number of samples for target rate
        num_samples = len(audio_data)
        target_num_samples = int(num_samples * target_sr / original_sr)
        
        # Use scipy's resample function
        resampled_audio = signal.resample(audio_data, target_num_samples)
        return resampled_audio.astype(np.float32)
    
    @staticmethod
    def convert_float32_to_pcm16(audio_data: np.ndarray) -> bytes:
        """Convert float32 audio data to 16-bit PCM bytes."""
        # Clamp to [-1, 1] range
        audio_data = np.clip(audio_data, -1.0, 1.0)
        
        # Convert to 16-bit integers
        pcm16_data = (audio_data * 32767).astype(np.int16)
        
        return pcm16_data.tobytes()
    
    @staticmethod
    def convert_pcm16_to_float32(pcm_data: bytes) -> np.ndarray:
        """Convert 16-bit PCM bytes to float32 array."""
        pcm16_array = np.frombuffer(pcm_data, dtype=np.int16)
        return pcm16_array.astype(np.float32) / 32768.0 