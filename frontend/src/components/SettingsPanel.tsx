import React, { useEffect, useState } from 'react';
import useAppStore from '../store/useAppStore';
import type { TtsVoice, VadAggressivenessLevel } from '../store/useAppStore';

const SettingsPanel: React.FC = () => {
  const {
    availableMics,
    selectedMicId,
    micPermissionsError,
    setAvailableMics,
    setSelectedMicId,
    setMicPermissionsError,
    
    availableTtsVoices,
    selectedTtsVoiceId,
    setSelectedTtsVoiceId,

    vadAggressiveness,
    setVadAggressiveness,

    llmEndpoint,
    setLlmEndpoint,
  } = useAppStore();

  const [isLoadingMics, setIsLoadingMics] = useState(false);

  useEffect(() => {
    const getAudioDevices = async () => {
      setIsLoadingMics(true);
      setMicPermissionsError(null);
      try {
        await navigator.mediaDevices.getUserMedia({ audio: true });
        const devices = await navigator.mediaDevices.enumerateDevices();
        const audioInputDevices = devices.filter(device => device.kind === 'audioinput');
        setAvailableMics(audioInputDevices);
        if (audioInputDevices.length > 0 && !selectedMicId) {
          const defaultDevice = audioInputDevices.find(d => d.deviceId === 'default');
          setSelectedMicId(defaultDevice ? defaultDevice.deviceId : audioInputDevices[0].deviceId);
        }
      } catch (err: any) {
        console.error("Error enumerating audio devices or getting permissions:", err);
        let message = "Could not get microphone list.";
        if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
          message = "Microphone permission denied. Please allow access in your browser settings.";
        } else if (err.name === 'NotFoundError') {
          message = "No microphone found.";
        }
        setMicPermissionsError(message);
        setAvailableMics([]);
      }
      setIsLoadingMics(false);
    };
    getAudioDevices();
  }, [setAvailableMics, setSelectedMicId, setMicPermissionsError, selectedMicId]);

  const handleMicChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedMicId(event.target.value || null);
  };

  const handleTtsVoiceChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedTtsVoiceId(event.target.value || null);
    console.log(`TTS Voice selected: ${event.target.value}`);
  };

  const handleVadChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const level = parseInt(event.target.value, 10) as VadAggressivenessLevel;
    setVadAggressiveness(level);
    console.log(`VAD Aggressiveness set to: ${level}`);
  };

  const handleLlmEndpointChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setLlmEndpoint(event.target.value);
    // Debounce or save on blur/submit later for API calls
  };

  const vadLevels: { value: VadAggressivenessLevel; label: string }[] = [
    { value: 0, label: '0 (Least Aggressive)' },
    { value: 1, label: '1' },
    { value: 2, label: '2 (Balanced)' },
    { value: 3, label: '3 (Most Aggressive)' },
  ];

  return (
    <div className="settings-panel-grid">
      <h3>Settings</h3>
      <label htmlFor="mic-select">Microphone:</label>
      {isLoadingMics ? <p>Loading...</p> : 
        availableMics.length > 0 ? (
          <select id="mic-select" value={selectedMicId || ''} onChange={handleMicChange}>
            {availableMics.map(mic => (
              <option key={mic.deviceId} value={mic.deviceId}>
                {mic.label || `Mic ${availableMics.indexOf(mic) + 1}`}
              </option>
            ))}
          </select>
        ) : <p className="text-error">No mics found or permission issue.</p>
      }
      {micPermissionsError && <p className="text-error" style={{ gridColumn: 'span 2' }}>{micPermissionsError}</p>}

      <label htmlFor="tts-voice-select">Voice (TTS):</label>
      {availableTtsVoices.length > 0 ? (
        <select id="tts-voice-select" value={selectedTtsVoiceId || ''} onChange={handleTtsVoiceChange}>
          {availableTtsVoices.map((voice: TtsVoice) => (
            <option key={voice.id} value={voice.id}>{voice.name}</option>
          ))}
        </select>
      ) : <p>No TTS voices.</p>}

      <label htmlFor="vad-select">VAD Level:</label>
      <select id="vad-select" value={vadAggressiveness} onChange={handleVadChange}>
        {vadLevels.map(level => (
          <option key={level.value} value={level.value}>{level.label}</option>
        ))}
      </select>

      <label htmlFor="llm-endpoint">LLM Endpoint:</label>
      <input 
        type="text" 
        id="llm-endpoint" 
        value={llmEndpoint} 
        onChange={handleLlmEndpointChange} 
        placeholder="e.g., http://localhost:11434/api/chat"
      />
    </div>
  );
};

export default SettingsPanel; 