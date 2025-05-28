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
import CoreGraphics
import ImageIO
import AppKit
import UniformTypeIdentifiers
import AVFoundation

// MARK: - Data Models

struct ChatMessage: Identifiable, Codable {
    let id: UUID
    let type: MessageType
    let content: String
    let timestamp: Date
    
    enum MessageType: String, Codable, CaseIterable {
        case user = "user"
        case assistant = "assistant"
        case toolStatus = "tool_status"
        case partialTranscript = "partial_transcript"
    }
    
    // CRITICAL FIX: Allow custom ID to be provided
    init(id: UUID = UUID(), type: MessageType, content: String, timestamp: Date) {
        self.id = id
        self.type = type
        self.content = content
        self.timestamp = timestamp
    }
}

// MARK: - App State

@MainActor
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
    @Published var inputDevices: [AudioDevice] = []
    @Published var outputDevices: [AudioDevice] = []
    @Published var selectedInputDevice: AudioDevice?
    @Published var selectedOutputDevice: AudioDevice?
    @Published var outputVolume: Float = 1.0
    
    // MARK: - Error State
    @Published var lastError: String?
    @Published var microphonePermissionGranted = false
    
    // MARK: - Tool State (Phase 1)
    @Published var isToolExecuting = false
    @Published var lastToolResult: String?
    @Published var lastToolError: String?
    
    // MARK: - Managers
    private var audioManager: AudioManager?
    private var webSocketManager: WebSocketManager?
    private var clientToolManager = ClientToolManager()
    
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
            Task { @MainActor in
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
        
        // Set up ClientToolManager
        clientToolManager.setWebSocketManager(webSocketManager!)
        
        // Observe tool execution state
        clientToolManager.$isToolExecuting
            .receive(on: DispatchQueue.main)
            .assign(to: \.isToolExecuting, on: self)
            .store(in: &cancellables)
        
        clientToolManager.$lastToolResult
            .receive(on: DispatchQueue.main)
            .assign(to: \.lastToolResult, on: self)
            .store(in: &cancellables)
        
        clientToolManager.$lastToolError
            .receive(on: DispatchQueue.main)
            .assign(to: \.lastToolError, on: self)
            .store(in: &cancellables)
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
                self?.inputDevices = inputDevices
                self?.outputDevices = outputDevices
                
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
                
                // Register client capabilities with the ClientToolManager
                clientToolManager.registerCapabilities(conversationId: conversationId)
            }
            
        case "partial_transcript":
            if let transcript = message["text"] as? String {
                partialTranscript = transcript
                print("Received partial transcript: '\(transcript)'")
            } else {
                print("Partial transcript message missing 'text' field: \(message)")
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
                print("🚨 RECEIVED user_interrupted - CALLING stopAudioPlayback()")
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
                audioManager?.startRealTimeAudioPlayback(sampleRate: sampleRate, channels: channels, outputDevice: selectedOutputDevice)
            }
            
        case "raw_audio_chunk":
            if let conversationId = message["conversation_id"] as? String,
               conversationId == activeConversationId,
               let audioData = message["data"] as? Data {
                print("Received audio chunk: \(audioData.count) bytes for conversation \(conversationId)")
                audioManager?.playAudioChunkImmediately(audioData)
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
                audioManager?.finishRealTimeAudioPlayback()
            }
            
        case "audio_stream_error":
            if let conversationId = message["conversation_id"] as? String,
               conversationId == activeConversationId,
               let error = message["error"] as? String {
                print("🚨 RECEIVED audio_stream_error - CALLING stopAudioPlayback()")
                stopAudioPlayback()
                clearCurrentAssistantMessage()
                lastError = "Audio stream error: \(error)"
            }
            
        case "barge_in_notification":
            if let conversationId = message["conversation_id"] as? String,
               conversationId == activeConversationId {
                print("🚨 RECEIVED barge_in_notification - CALLING stopAudioPlayback()")
                stopAudioPlayback()
                clearCurrentAssistantMessage()
            }
            
        // Delegate tool requests to ClientToolManager
        case "tool_request":
            if let conversationId = message["conversation_id"] as? String,
               conversationId == activeConversationId {
                print("🔧 Received tool request for conversation \(conversationId) - delegating to ClientToolManager")
                clientToolManager.handleToolRequest(message)
            } else {
                print("🔧 Ignoring tool request for different conversation: \(message["conversation_id"] as? String ?? "none") (active: \(activeConversationId ?? "none"))")
            }
            
        default:
            print("Unknown message type: \(messageType)")
        }
    }
    
    // MARK: - Tool handling is now delegated to ClientToolManager
    // All tool implementations (takeScreenshot, launchApplication, getSystemInfo) 
    // have been moved to ClientToolManager.swift for better separation of concerns
    
    private func addChatMessage(type: ChatMessage.MessageType, content: String) {
        let message = ChatMessage(type: type, content: content, timestamp: Date())
        chatMessages.append(message)
    }
    
    private func startAssistantMessage() {
        // CRITICAL FIX: Create message ID synchronously, then update UI on main thread
        let messageId = UUID()
        currentAssistantMessageId = messageId
        
        print("📝 Starting assistant message with ID: \(messageId)")
        
        // Ensure UI updates happen on main thread
        DispatchQueue.main.async { [weak self] in
            guard let self = self else { 
                print("📝 ERROR: Self is nil in startAssistantMessage")
                return 
            }
            
            // CRITICAL FIX: Use the messageId when creating the ChatMessage
            let message = ChatMessage(id: messageId, type: .assistant, content: "", timestamp: Date())
            self.chatMessages.append(message)
            print("📝 Created assistant message in UI with ID: \(messageId). Total messages: \(self.chatMessages.count)")
            
            // Force UI update
            self.objectWillChange.send()
        }
    }
    
    private func appendToCurrentAssistantMessage(_ content: String) {
        print("📝 Attempting to append '\(content)' to currentAssistantMessageId: \(currentAssistantMessageId?.uuidString ?? "nil")")
        
        // Ensure UI updates happen on main thread
        DispatchQueue.main.async { [weak self] in
            guard let self = self else {
                print("📝 ERROR: Self is nil in appendToCurrentAssistantMessage")
                return
            }
            
            guard let messageId = self.currentAssistantMessageId else {
                print("📝 ERROR: No currentAssistantMessageId set")
                return
            }
            
            guard let index = self.chatMessages.firstIndex(where: { $0.id == messageId }) else {
                print("📝 ERROR: Could not find message with ID \(messageId) in \(self.chatMessages.count) messages")
                for (i, msg) in self.chatMessages.enumerated() {
                    print("📝   Message \(i): ID=\(msg.id), type=\(msg.type), content='\(msg.content.prefix(50))'")
                }
                return
            }
            
            // Create a new ChatMessage with updated content using the SAME ID
            let oldContent = self.chatMessages[index].content
            let newContent = oldContent + content
            let updatedMessage = ChatMessage(
                id: messageId,  // CRITICAL FIX: Use the same messageId
                type: .assistant,
                content: newContent,
                timestamp: self.chatMessages[index].timestamp
            )
            
            // Replace the message in the array to trigger UI update
            self.chatMessages[index] = updatedMessage
            print("📝 Updated assistant message: '\(oldContent)' + '\(content)' = '\(newContent)'")
            
            // Force UI update by triggering objectWillChange
            self.objectWillChange.send()
        }
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
        
        // Load audio device preferences (just check if they exist)
        if defaults.string(forKey: "selectedInputDeviceId") != nil {
            // Input device preference exists
        }
        if defaults.string(forKey: "selectedOutputDeviceId") != nil {
            // Output device preference exists
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
