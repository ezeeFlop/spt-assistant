//
//  AppState.swift
//  SPTAssistant
//
//  Created by SPT Assistant Team
//  Copyright © 2025 SPT Assistant. All rights reserved.
//

import Foundation
import SwiftUI
import Combine

// MARK: - Data Models

struct ChatMessage: Identifiable, Codable {
    let id = UUID()
    let type: MessageType
    let content: String
    let timestamp: Date
    
    enum MessageType: String, Codable, CaseIterable {
        case user = "user"
        case assistant = "assistant"
        case toolStatus = "tool_status"
        case partialTranscript = "partial_transcript"
    }
}

// MARK: - App State

class AppState: ObservableObject {
    
    // MARK: - Connection State
    @Published var isConnected = false
    @Published var connectionStatus = "Disconnected"
    @Published var serverURL = "ws://localhost:8000/api/v1/ws/audio"
    
    // MARK: - Recording State
    @Published var isRecording = false
    @Published var isPlayingAudio = false
    @Published var partialTranscript = ""
    @Published var micAudioLevel: Float = 0.0
    @Published var playbackAudioLevel: Float = 0.0
    
    // MARK: - Chat State
    @Published var chatMessages: [ChatMessage] = []
    @Published var currentAssistantMessageId: UUID?
    @Published var activeConversationId: String?
    
    // MARK: - Audio Device Settings
    @Published var availableInputDevices: [AudioDevice] = []
    @Published var availableOutputDevices: [AudioDevice] = []
    @Published var selectedInputDevice: AudioDevice?
    @Published var selectedOutputDevice: AudioDevice?
    @Published var outputVolume: Float = 1.0
    
    // MARK: - Error State
    @Published var lastError: String?
    @Published var microphonePermissionGranted = false
    
    // MARK: - Managers
    private var audioManager: AudioManager?
    private var webSocketManager: WebSocketManager?
    
    // MARK: - Cancellables
    private var cancellables = Set<AnyCancellable>()
    
    init() {
        setupManagers()
        loadSettings()
        refreshAudioDevices()
    }
    
    // MARK: - Setup
    
    private func setupManagers() {
        audioManager = AudioManager()
        webSocketManager = WebSocketManager()
        
        // Bind audio manager to state
        audioManager?.$isRecording
            .receive(on: DispatchQueue.main)
            .assign(to: \.isRecording, on: self)
            .store(in: &cancellables)
        
        audioManager?.$isPlayingAudio
            .receive(on: DispatchQueue.main)
            .assign(to: \.isPlayingAudio, on: self)
            .store(in: &cancellables)
        
        audioManager?.$micAudioLevel
            .receive(on: DispatchQueue.main)
            .assign(to: \.micAudioLevel, on: self)
            .store(in: &cancellables)
        
        audioManager?.$playbackAudioLevel
            .receive(on: DispatchQueue.main)
            .assign(to: \.playbackAudioLevel, on: self)
            .store(in: &cancellables)
        
        audioManager?.$microphonePermissionGranted
            .receive(on: DispatchQueue.main)
            .assign(to: \.microphonePermissionGranted, on: self)
            .store(in: &cancellables)
        
        // Bind WebSocket manager to state
        webSocketManager?.$isConnected
            .receive(on: DispatchQueue.main)
            .assign(to: \.isConnected, on: self)
            .store(in: &cancellables)
        
        webSocketManager?.$connectionStatus
            .receive(on: DispatchQueue.main)
            .assign(to: \.connectionStatus, on: self)
            .store(in: &cancellables)
        
        // Setup message handling
        webSocketManager?.onMessageReceived = { [weak self] message in
            DispatchQueue.main.async {
                self?.handleWebSocketMessage(message)
            }
        }
        
        // Setup audio chunk sending
        audioManager?.onAudioChunk = { [weak self] audioData in
            self?.webSocketManager?.sendAudioChunk(audioData)
        }
        
        // Setup audio playback finished callback
        audioManager?.onPlaybackFinished = { [weak self] in
            DispatchQueue.main.async {
                self?.clearCurrentAssistantMessage()
            }
        }
    }
    
    // MARK: - Public Methods
    
    func connect() {
        webSocketManager?.connect(to: serverURL)
    }
    
    func disconnect() {
        webSocketManager?.disconnect()
        stopRecording()
    }
    
    func startRecording() {
        guard microphonePermissionGranted else {
            lastError = "Microphone permission not granted"
            return
        }
        
        guard isConnected else {
            lastError = "Not connected to server"
            return
        }
        
        clearChat()
        stopAudioPlayback()
        audioManager?.startRecording(inputDevice: selectedInputDevice)
    }
    
    func stopRecording() {
        audioManager?.stopRecording()
    }
    
    func stopAudioPlayback() {
        audioManager?.stopAudioPlayback()
    }
    
    func clearChat() {
        chatMessages.removeAll()
        partialTranscript = ""
        currentAssistantMessageId = nil
    }
    
    func refreshAudioDevices() {
        audioManager?.refreshAudioDevices { [weak self] inputDevices, outputDevices in
            DispatchQueue.main.async {
                self?.availableInputDevices = inputDevices
                self?.availableOutputDevices = outputDevices
                
                // Set default devices if none selected
                if self?.selectedInputDevice == nil {
                    self?.selectedInputDevice = inputDevices.first { $0.isDefault }
                }
                if self?.selectedOutputDevice == nil {
                    self?.selectedOutputDevice = outputDevices.first { $0.isDefault }
                }
            }
        }
    }
    
    func setOutputVolume(_ volume: Float) {
        outputVolume = max(0.0, min(2.0, volume))
        audioManager?.setOutputVolume(outputVolume)
        saveSettings()
    }
    
    func setServerURL(_ url: String) {
        serverURL = url
        saveSettings()
    }
    
    func cleanup() {
        stopRecording()
        stopAudioPlayback()
        webSocketManager?.disconnect()
        saveSettings()
    }
    
    // MARK: - Private Methods
    
    private func handleWebSocketMessage(_ message: [String: Any]) {
        guard let messageType = message["type"] as? String else { return }
        
        switch messageType {
        case "system_event":
            if let event = message["event"] as? String,
               event == "conversation_started",
               let conversationId = message["conversation_id"] as? String {
                activeConversationId = conversationId
                webSocketManager?.activeConversationId = conversationId
                clearChat()
                stopAudioPlayback()
                print("Conversation started with ID: \(conversationId)")
            }
            
        case "partial_transcript":
            if let transcript = message["transcript"] as? String {
                partialTranscript = transcript
                print("Received partial transcript: '\(transcript)'")
            } else {
                print("Partial transcript message missing 'transcript' field: \(message)")
            }
            
        case "final_transcript":
            if let transcript = message["transcript"] as? String {
                addChatMessage(type: .user, content: transcript)
                partialTranscript = ""
                clearCurrentAssistantMessage()
                print("Received final transcript: '\(transcript)'")
            } else {
                print("Final transcript message missing 'transcript' field: \(message)")
            }
            
        case "token":
            if let content = message["content"] as? String {
                if currentAssistantMessageId == nil {
                    startAssistantMessage()
                    print("Started new assistant message for token: '\(content)'")
                }
                appendToCurrentAssistantMessage(content)
                print("Received LLM token: '\(content)'")
            } else {
                print("Token message missing 'content' field: \(message)")
            }
            
        case "tool":
            if let name = message["name"] as? String,
               let status = message["status"] as? String {
                addChatMessage(type: .toolStatus, content: "\(name): \(status)")
            }
            
        case "user_interrupted":
            if let conversationId = message["conversation_id"] as? String,
               conversationId == activeConversationId {
                stopAudioPlayback()
                clearCurrentAssistantMessage()
            }
            
        case "audio_stream_start":
            if let conversationId = message["conversation_id"] as? String,
               conversationId == activeConversationId,
               let sampleRate = message["sample_rate"] as? Int,
               let channels = message["channels"] as? Int {
                
                if currentAssistantMessageId == nil {
                    startAssistantMessage()
                }
                audioManager?.startAudioPlayback(sampleRate: sampleRate, channels: channels, outputDevice: selectedOutputDevice)
            }
            
        case "raw_audio_chunk":
            if let conversationId = message["conversation_id"] as? String,
               conversationId == activeConversationId,
               let audioData = message["data"] as? Data {
                print("Received audio chunk: \(audioData.count) bytes for conversation \(conversationId)")
                audioManager?.enqueueAudioChunk(audioData)
            } else {
                print("Skipping audio chunk - conversation ID mismatch or missing data")
                if let conversationId = message["conversation_id"] as? String {
                    print("  Message conversation ID: \(conversationId), Active: \(activeConversationId ?? "none")")
                }
                if message["data"] == nil {
                    print("  Missing audio data in message")
                }
            }
            
        case "audio_stream_end":
            if let conversationId = message["conversation_id"] as? String,
               conversationId == activeConversationId {
                audioManager?.signalStreamEnded()
            }
            
        case "audio_stream_error":
            if let conversationId = message["conversation_id"] as? String,
               conversationId == activeConversationId,
               let error = message["error"] as? String {
                stopAudioPlayback()
                clearCurrentAssistantMessage()
                lastError = "Audio stream error: \(error)"
            }
            
        case "barge_in_notification":
            if let conversationId = message["conversation_id"] as? String,
               conversationId == activeConversationId {
                stopAudioPlayback()
                clearCurrentAssistantMessage()
            }
            
        default:
            print("Unknown message type: \(messageType)")
        }
    }
    
    private func addChatMessage(type: ChatMessage.MessageType, content: String) {
        let message = ChatMessage(type: type, content: content, timestamp: Date())
        chatMessages.append(message)
    }
    
    private func startAssistantMessage() {
        currentAssistantMessageId = UUID()
        let message = ChatMessage(type: .assistant, content: "", timestamp: Date())
        chatMessages.append(message)
    }
    
    private func appendToCurrentAssistantMessage(_ content: String) {
        guard let messageId = currentAssistantMessageId,
              let index = chatMessages.firstIndex(where: { $0.id == messageId }) else { return }
        
        let updatedMessage = ChatMessage(
            type: .assistant,
            content: chatMessages[index].content + content,
            timestamp: chatMessages[index].timestamp
        )
        chatMessages[index] = updatedMessage
    }
    
    private func clearCurrentAssistantMessage() {
        currentAssistantMessageId = nil
    }
    
    // MARK: - Settings Persistence
    
    private func loadSettings() {
        let defaults = UserDefaults.standard
        serverURL = defaults.string(forKey: "serverURL") ?? "ws://localhost:8000/api/v1/ws/audio"
        outputVolume = defaults.float(forKey: "outputVolume")
        if outputVolume == 0 { outputVolume = 1.0 } // Default value
        
        if let inputDeviceId = defaults.string(forKey: "selectedInputDeviceId") {
            // Will be set when devices are refreshed
        }
        if let outputDeviceId = defaults.string(forKey: "selectedOutputDeviceId") {
            // Will be set when devices are refreshed
        }
    }
    
    private func saveSettings() {
        let defaults = UserDefaults.standard
        defaults.set(serverURL, forKey: "serverURL")
        defaults.set(outputVolume, forKey: "outputVolume")
        defaults.set(selectedInputDevice?.id, forKey: "selectedInputDeviceId")
        defaults.set(selectedOutputDevice?.id, forKey: "selectedOutputDeviceId")
    }
} 