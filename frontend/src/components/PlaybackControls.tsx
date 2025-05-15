import React, { useEffect, useRef } from 'react';
import useAppStore from '../store/useAppStore';

const PlaybackControls: React.FC = () => {
  const {
    currentAudioUrl,
    // @ts-ignore

    isPlayingAudio,
    audioPlaybackError,
    setCurrentAudioUrl,
    setIsPlayingAudio,
    setAudioPlaybackError,
    // Progress state and actions
    audioCurrentTime,
    audioDuration,
    setAudioPlaybackProgress,
    resetAudioPlaybackProgress,
  } = useAppStore();

  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    if (!audioRef.current) {
      audioRef.current = new Audio();
      const audio = audioRef.current; // Alias for convenience

      audio.onplay = () => {
        setIsPlayingAudio(true);
        setAudioPlaybackError(null);
      };

      audio.onpause = () => {
        if (useAppStore.getState().isPlayingAudio && !audio.ended) {
            setIsPlayingAudio(false);
        }
      };

      audio.onended = () => {
        // setIsPlayingAudio(false); // resetAudioPlaybackProgress handles this
        // setCurrentAudioUrl(null);
        resetAudioPlaybackProgress(); // Resets time, duration, isPlayingAudio, and currentAudioUrl
      };

      audio.onerror = () => { 
        const audio = audioRef.current;
        let errMsg = "Audio playback failed.";
        if (audio && audio.error) {
            switch (audio.error.code) {
                case 1: errMsg = 'Audio playback aborted.'; break;
                case 2: errMsg = 'Audio download failed due to network error.'; break;
                case 3: errMsg = 'Audio decoding error.'; break;
                case 4: errMsg = 'Audio format not supported or source error.'; break;
                default: errMsg = `Audio playback error (code: ${audio.error.code}).`;
            }
            console.error('Audio playback error details:', audio.error);
        } else {
            errMsg = "An unknown audio playback error occurred.";
            console.error(errMsg, 'onError event triggered but audio.error was null.');
        }
        setAudioPlaybackError(errMsg);
        // setIsPlayingAudio(false); // resetAudioPlaybackProgress handles this indirectly if called
        // setCurrentAudioUrl(null);
        resetAudioPlaybackProgress(); // Also reset progress and stop audio state
      };

      audio.onloadedmetadata = () => {
        if (audio) {
          setAudioPlaybackProgress({ 
            currentTime: audio.currentTime,
            duration: audio.duration 
          });
        }
      };

      audio.ontimeupdate = () => {
        if (audio) {
          setAudioPlaybackProgress({ 
            currentTime: audio.currentTime, 
            duration: audio.duration 
          });
        }
      };
    }
  }, [setIsPlayingAudio, setCurrentAudioUrl, setAudioPlaybackError, setAudioPlaybackProgress, resetAudioPlaybackProgress]);

  useEffect(() => {
    const audio = audioRef.current;
    if (audio) {
      if (currentAudioUrl && audio.src !== currentAudioUrl) {
        console.log('Setting audio src:', currentAudioUrl);
        resetAudioPlaybackProgress(); // Reset progress for new audio
        audio.src = currentAudioUrl;
        audio.load();
        audio.play().catch(err => {
          console.error("Error attempting to play audio:", err);
          setAudioPlaybackError(`Could not play audio: ${err.message}`);
          // setIsPlayingAudio(false); // resetAudioPlaybackProgress would handle this if play fails immediately
          resetAudioPlaybackProgress();
        });
      } else if (!currentAudioUrl && (!audio.paused || audio.currentTime > 0)) {
        audio.pause();
        audio.src = '';
        resetAudioPlaybackProgress(); // Ensure reset when URL is cleared
      }
    }
  }, [currentAudioUrl, setAudioPlaybackError, resetAudioPlaybackProgress]);

  const formatTime = (timeInSeconds: number): string => {
    const minutes = Math.floor(timeInSeconds / 60);
    const seconds = Math.floor(timeInSeconds % 60).toString().padStart(2, '0');
    return `${minutes}:${seconds}`;
  };

  return (
    // The root div now uses the class given by App.tsx: "panel-section playback-controls"
    // We can add more specific styling if needed here or in App.css
    <>
      {currentAudioUrl && (
        <div className="tts-playback-info" style={{display: 'flex', alignItems: 'center', gap: 'var(--spacing-sm)', width: '100%'}}>
          <span style={{ flexShrink: 0 }}>TTS:</span>
          <progress value={audioCurrentTime} max={audioDuration || 1} style={{flexGrow: 1, height: '12px'}} />
          <span style={{ flexShrink: 0, fontFamily: 'var(--font-family-monospace)', fontSize: '0.9rem' }}>
            {formatTime(audioCurrentTime)} / {formatTime(audioDuration)}
          </span>
        </div>
      )}
      {/* Removed: {isPlayingAudio && !currentAudioUrl && <p>Playing audio (no URL)...</p>} as it's an unlikely state with resetAudioPlaybackProgress */}
      {audioPlaybackError && <p className="text-error mt-1">Audio Error: {audioPlaybackError}</p>}
    </>
  );
};

export default PlaybackControls; 