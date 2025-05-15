import { create } from 'zustand';

// Define a more specific type for MediaDeviceInfo if needed, or use the default
// For simplicity, we'll use MediaDeviceInfo directly from TypeScript's lib.dom.d.ts

// --- TTS Voice Settings --- 
// FR-07: Piper (fr-siwis / fr-gilles) by default; allow plug-ins for Coqui-TTS, Parler-TTS, or XTTS.
// For now, we will hardcode a list based on Piper defaults mentioned.
export interface TtsVoice {
  id: string;       // e.g., "fr-siwis-medium" or "piper_fr_gilles_high"
  name: string;     // e.g., "French - Siwis (Medium)" or "Gilles (High Quality)"
  engine?: string;  // e.g., "piper", "coqui-tts"
  language?: string;// e.g., "fr-FR"
}

// --- VAD Settings ---
// Typically an integer from 0 (least aggressive) to 3 (most aggressive)
export type VadAggressivenessLevel = 0 | 1 | 2 | 3;

interface AppState {
  isRecording: boolean;
  partialTranscript: string;
  finalTranscript: string;
  llmResponse: string;
  toolStatus: string;
  isPlayingAudio: boolean;
  currentAudioUrl: string | null; // For TTS audio playback
  audioPlaybackError: string | null;

  // Microphone Settings
  availableMics: MediaDeviceInfo[];
  selectedMicId: string | null; // Store the deviceId
  micPermissionsError: string | null; // For errors like permission denied

  // TTS Voice Settings
  availableTtsVoices: TtsVoice[];
  selectedTtsVoiceId: string | null;

  // VAD Settings
  vadAggressiveness: VadAggressivenessLevel;

  // LLM Settings
  llmEndpoint: string;

  // Audio Playback Progress
  audioCurrentTime: number; // in seconds
  audioDuration: number;    // in seconds

  activeConversationId: string | null; // ADDED: To track the current conversation

  // TODO: Add other state variables as needed, e.g., settings for voice, VAD, LLM
  // Voice Settings
  // availableVoices: string[]; (example)
  // selectedVoice: string | null; (example)

  // Actions
  setIsRecording: (isRecording: boolean) => void;
  setPartialTranscript: (partial: string) => void;
  appendPartialTranscript: (partial: string) => void;
  setFinalTranscript: (final: string) => void;
  appendFinalTranscript: (final: string) => void;
  setLlmResponse: (response: string) => void;
  appendLlmResponse: (token: string) => void;
  setToolStatus: (status: string) => void;
  setIsPlayingAudio: (isPlaying: boolean) => void;
  setCurrentAudioUrl: (url: string | null) => void;
  setAudioPlaybackError: (error: string | null) => void;

  // Mic Actions
  setAvailableMics: (mics: MediaDeviceInfo[]) => void;
  setSelectedMicId: (micId: string | null) => void;
  setMicPermissionsError: (error: string | null) => void;

  // TTS Voice Actions
  setAvailableTtsVoices: (voices: TtsVoice[]) => void;
  setSelectedTtsVoiceId: (voiceId: string | null) => void;

  // VAD Actions
  setVadAggressiveness: (level: VadAggressivenessLevel) => void;

  // LLM Actions
  setLlmEndpoint: (endpoint: string) => void;

  // Audio Playback Progress Actions
  setAudioPlaybackProgress: (progress: { currentTime: number; duration: number }) => void;
  resetAudioPlaybackProgress: () => void;

  setActiveConversationId: (id: string | null) => void; // ADDED
}

// Hardcoded default voices
const defaultTtsVoices: TtsVoice[] = [
  // ElevenLabs voices - ID MUST be the actual Voice ID from ElevenLabs
  // Ensure the first voice is a valid ElevenLabs ID if TTS_PROVIDER in worker defaults to elevenlabs
  { id: 'pNInz6obpgDQGcFmaJgB', name: 'ElevenLabs - Rachel (Default EN)', engine: 'elevenlabs', language: 'en' },
  { id: 'VR6AewLTigWG4xSOh1pg', name: 'ElevenLabs - Drew (EN)', engine: 'elevenlabs', language: 'en' },
  { id: 'SOYHLrjzK2X1ezoPC6cr', name: 'ElevenLabs - Clyde (EN)', engine: 'elevenlabs', language: 'en' },
  
  // Piper voices - ID is typically the model filename
  { id: 'fr_FR-siwis-medium.onnx', name: 'Piper - Siwis (FR)', engine: 'piper', language: 'fr' },
  { id: 'fr_FR-gilles-high.onnx', name: 'Piper - Gilles (FR)', engine: 'piper', language: 'fr' },
  // Add more actual ElevenLabs voice IDs here as needed
];

// Default values for new settings
const defaultVadAggressiveness: VadAggressivenessLevel = 2; // A sensible default
const defaultLlmEndpoint: string = "http://localhost:11434/api/chat"; // Example, common for Ollama
// @ts-ignore
const useAppStore = create<AppState>((set, get) => ({
  isRecording: false,
  partialTranscript: "",
  finalTranscript: "",
  llmResponse: "",
  toolStatus: "",
  isPlayingAudio: false,
  currentAudioUrl: null,
  audioPlaybackError: null,

  availableMics: [],
  selectedMicId: null,
  micPermissionsError: null,

  availableTtsVoices: defaultTtsVoices, 
  selectedTtsVoiceId: defaultTtsVoices.length > 0 ? defaultTtsVoices[0].id : null, 

  vadAggressiveness: defaultVadAggressiveness,
  llmEndpoint: defaultLlmEndpoint,

  audioCurrentTime: 0,
  audioDuration: 0,

  activeConversationId: null, // ADDED

  setIsRecording: (isRecording) => set({ isRecording }),
  setPartialTranscript: (partial) => set({ partialTranscript: partial }),
  appendPartialTranscript: (partial) => set((state) => ({ partialTranscript: state.partialTranscript + partial })),
  setFinalTranscript: (final) => set({ finalTranscript: final }),
  appendFinalTranscript: (final) => set((state) => ({ finalTranscript: state.finalTranscript + final, partialTranscript: "" })), 
  setLlmResponse: (response) => set({ llmResponse: response }),
  appendLlmResponse: (token) => set((state) => ({ llmResponse: state.llmResponse + token })),
  setToolStatus: (status) => set({ toolStatus: status }),
  setIsPlayingAudio: (isPlaying) => set({ isPlayingAudio: isPlaying }),
  setCurrentAudioUrl: (url) => set({ currentAudioUrl: url, audioPlaybackError: null }), 
  setAudioPlaybackError: (error) => set({ audioPlaybackError: error, isPlayingAudio: false }),

  setAvailableMics: (mics) => set({ availableMics: mics }),
  setSelectedMicId: (micId) => set({ selectedMicId: micId, micPermissionsError: null }),
  setMicPermissionsError: (error) => set({ micPermissionsError: error }),

  // TTS Voice Actions Implementation
  setAvailableTtsVoices: (voices) => set({ availableTtsVoices: voices }),
  setSelectedTtsVoiceId: (voiceId) => set({ selectedTtsVoiceId: voiceId }),

  // VAD Action Implementation
  setVadAggressiveness: (level) => set({ vadAggressiveness: level }),

  // LLM Action Implementation
  setLlmEndpoint: (endpoint) => set({ llmEndpoint: endpoint }),

  setAudioPlaybackProgress: (progress) => set({
    audioCurrentTime: progress.currentTime,
    audioDuration: progress.duration,
  }),
  resetAudioPlaybackProgress: () => set({ audioCurrentTime: 0, audioDuration: 0, isPlayingAudio: false, currentAudioUrl: null }), // Also stop playback

  setActiveConversationId: (id) => set({ activeConversationId: id }), // ADDED
}));

export default useAppStore; 