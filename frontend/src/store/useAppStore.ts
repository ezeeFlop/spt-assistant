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

// Define ChatMessage interface
export interface ChatMessage {
  id: string; // Unique ID for the message (e.g., timestamp + random)
  type: 'user' | 'assistant' | 'tool_status';
  content: string;
  timestamp: number; // Unix timestamp
}

interface AppState {
  isRecording: boolean;
  partialTranscript: string;
  chatMessages: ChatMessage[]; // NEW: Array to store all chat messages
  currentAssistantMessageId: string | null; // NEW: To track active assistant message for streaming

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

  // NEW Chat Actions
  addChatMessage: (data: { type: 'user' | 'tool_status'; content: string }) => void;
  startAssistantMessage: (initialContent?: string) => void;
  appendContentToCurrentAssistantMessage: (contentChunk: string) => void;
  clearCurrentAssistantMessageId: () => void;
  clearChat: () => void;
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
  { id: 'tts_models/multilingual/multi-dataset/xtts_v2', name: 'Coqui - XTTS (FR)', engine: 'coqui', language: 'fr' },
  { id: 'tts_models/multilingual/multi-dataset/xtts_v2', name: 'Coqui - XTTS (EN)', engine: 'coqui', language: 'en' },
  { id: 'tts_models/multilingual/multi-dataset/xtts_v2', name: 'Coqui - XTTS (DE)', engine: 'coqui', language: 'de' },
];

// Default values for new settings
const defaultVadAggressiveness: VadAggressivenessLevel = 2; // A sensible default
const defaultLlmEndpoint: string = "http://localhost:11434/api/chat"; // Example, common for Ollama
// @ts-ignore
const useAppStore = create<AppState>((set, get) => ({
  isRecording: false,
  partialTranscript: "",
  chatMessages: [], // NEW
  currentAssistantMessageId: null, // NEW

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

  // NEW Chat Actions Implementation
  addChatMessage: (data) => {
    const trimmedContent = data.content.trim();
    if (!trimmedContent) {
      // If content is empty or only whitespace, do not add the message
      // Also, if it was a user message, still clear the partial transcript
      if (data.type === 'user') {
        set({ partialTranscript: "" });
      }
      return;
    }
    const newMessage: ChatMessage = {
      id: `${Date.now()}-${Math.random().toString(36).substring(2, 9)}`,
      type: data.type,
      content: trimmedContent, // Use trimmed content
      timestamp: Date.now(),
    };
    set((state) => ({ 
      chatMessages: [...state.chatMessages, newMessage],
      partialTranscript: data.type === 'user' ? "" : state.partialTranscript 
    }));
  },
  startAssistantMessage: (initialContent = "") => {
    const newMessageId = `${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
    const newMessage: ChatMessage = {
      id: newMessageId,
      type: 'assistant',
      content: initialContent, // Start with potentially empty or whitespace initial content, will be trimmed upon finalization
      timestamp: Date.now(),
    };
    set((state) => ({
      chatMessages: [...state.chatMessages, newMessage],
      currentAssistantMessageId: newMessageId,
    }));
  },
  appendContentToCurrentAssistantMessage: (contentChunk) => {
    set((state) => {
      if (!state.currentAssistantMessageId) return state;
      return {
        chatMessages: state.chatMessages.map((msg) =>
          msg.id === state.currentAssistantMessageId
            ? { ...msg, content: msg.content + contentChunk }
            : msg
        ),
      };
    });
  },
  clearCurrentAssistantMessageId: () => {
    const endedAssistantMessageId = get().currentAssistantMessageId;
    set((state) => {
      if (!endedAssistantMessageId) {
        return { currentAssistantMessageId: null };
      }
      // Check the content of the assistant message that just ended
      const updatedChatMessages = state.chatMessages.filter(msg => {
        if (msg.id === endedAssistantMessageId) {
          return msg.content.trim() !== ''; // Keep if not empty after trim
        }
        return true; // Keep other messages
      });
      return {
        chatMessages: updatedChatMessages,
        currentAssistantMessageId: null,
      };
    });
  },
  clearChat: () => set({ 
    chatMessages: [], 
    partialTranscript: "", 
    currentAssistantMessageId: null,
    // Also consider resetting other related states if necessary
    // toolStatus: "" // If you had a separate toolStatus outside messages
  }),
}));

export default useAppStore; 