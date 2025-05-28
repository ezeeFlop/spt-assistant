//
//  ChatView.swift
//  SPTAssistant
//
//  Created by SPT Assistant Team
//  Copyright © 2025 SPT Assistant. All rights reserved.
//

import SwiftUI

struct ChatView: View {
    @EnvironmentObject var appState: AppState
    @State private var isHovering = false
    
    var body: some View {
        VStack(spacing: 0) {
            // Chat Messages
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(spacing: 12) {
                        ForEach(appState.chatMessages) { message in
                            MessageBubble(message: message)
                        }
                        
                        // Partial transcript
                        if !appState.partialTranscript.isEmpty {
                            PartialTranscriptView(text: appState.partialTranscript)
                        }
                    }
                    .padding()
                }
                .onChange(of: appState.chatMessages.count) { _ in
                    // Auto-scroll to bottom when new messages arrive
                    if let lastMessage = appState.chatMessages.last {
                        withAnimation(.easeOut(duration: 0.3)) {
                            proxy.scrollTo(lastMessage.id, anchor: .bottom)
                        }
                    }
                }
            }
            
            Divider()
            
            // Recording Controls
            RecordingControlsView()
        }
        .background(Color(NSColor.textBackgroundColor))
    }
}

struct MessageBubble: View {
    let message: ChatMessage
    
    var body: some View {
        HStack {
            if message.type == .user {
                Spacer()
            }
            
            VStack(alignment: message.type == .user ? .trailing : .leading, spacing: 4) {
                Text(message.content)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(backgroundColor)
                    .foregroundColor(textColor)
                    .cornerRadius(16)
                    .textSelection(.enabled)
                
                Text(formatTime(message.timestamp))
                    .font(.caption2)
                    .foregroundColor(.secondary)
            }
            
            if message.type == .assistant {
                Spacer()
            }
        }
    }
    
    private var backgroundColor: Color {
        switch message.type {
        case .user:
            return Color.blue
        case .assistant:
            return Color(NSColor.controlBackgroundColor)
        case .toolStatus:
            return Color.orange.opacity(0.3)
        case .partialTranscript:
            return Color.gray.opacity(0.3)
        }
    }
    
    private var textColor: Color {
        switch message.type {
        case .user:
            return Color.white
        case .assistant, .toolStatus, .partialTranscript:
            return Color.primary
        }
    }
    
    private func formatTime(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.timeStyle = .short
        return formatter.string(from: date)
    }
}

struct PartialTranscriptView: View {
    let text: String
    
    var body: some View {
        HStack {
            Spacer()
            
            VStack(alignment: .trailing, spacing: 4) {
                Text(text)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(Color.blue.opacity(0.3))
                    .foregroundColor(.primary)
                    .cornerRadius(16)
                    .overlay(
                        RoundedRectangle(cornerRadius: 16)
                            .stroke(Color.blue.opacity(0.5), lineWidth: 1)
                            .animation(.easeInOut(duration: 1.0).repeatForever(), value: text)
                    )
                
                Text("Listening...")
                    .font(.caption2)
                    .foregroundColor(.secondary)
                    .italic()
            }
        }
    }
}

struct RecordingControlsView: View {
    @EnvironmentObject var appState: AppState
    @State private var isHovering = false
    
    var body: some View {
        VStack(spacing: 16) {
            // Error Display
            if let error = appState.lastError {
                HStack {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundColor(.orange)
                    Text(error)
                        .font(.caption)
                        .foregroundColor(.secondary)
                    Spacer()
                    Button("Dismiss") {
                        appState.lastError = nil
                    }
                    .font(.caption)
                }
                .padding(.horizontal)
            }
            
            // Phase 1: Tool execution status
            if appState.isToolExecuting {
                HStack {
                    ProgressView()
                        .scaleEffect(0.7)
                    Text("Executing tool...")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    Spacer()
                }
                .padding(.horizontal)
            }
            
            // Phase 1: Tool result display
            if let toolResult = appState.lastToolResult {
                HStack {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundColor(.green)
                    Text("Tool completed successfully")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    Spacer()
                    Button("Dismiss") {
                        appState.lastToolResult = nil
                    }
                    .font(.caption)
                }
                .padding(.horizontal)
            }
            
            // Phase 1: Tool error display
            if let toolError = appState.lastToolError {
                HStack {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundColor(.red)
                    Text("Tool error: \(toolError)")
                        .font(.caption)
                        .foregroundColor(.secondary)
                        .lineLimit(2)
                    Spacer()
                    Button("Dismiss") {
                        appState.lastToolError = nil
                    }
                    .font(.caption)
                }
                .padding(.horizontal)
            }
            
            // Recording Button
            HStack {
                Spacer()
                
                Button(action: {
                    if appState.isRecording {
                        appState.stopRecording()
                    } else {
                        appState.startRecording()
                    }
                }) {
                    ZStack {
                        Circle()
                            .fill(recordingButtonColor)
                            .frame(width: 80, height: 80)
                            .scaleEffect(isHovering ? 1.1 : 1.0)
                            .animation(.easeInOut(duration: 0.2), value: isHovering)
                        
                        Image(systemName: recordingButtonIcon)
                            .font(.title)
                            .foregroundColor(.white)
                    }
                }
                .buttonStyle(PlainButtonStyle())
                .onHover { hovering in
                    isHovering = hovering
                }
                .disabled(!appState.isConnected || !appState.microphonePermissionGranted)
                .help(recordingButtonTooltip)
                
                Spacer()
            }
            
            // Status Text
            Text(statusText)
                .font(.caption)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding()
        .background(Color(NSColor.controlBackgroundColor))
    }
    
    private var recordingButtonColor: Color {
        if !appState.isConnected || !appState.microphonePermissionGranted {
            return Color.gray
        }
        return appState.isRecording ? Color.red : Color.blue
    }
    
    private var recordingButtonIcon: String {
        appState.isRecording ? "stop.fill" : "mic.fill"
    }
    
    private var recordingButtonTooltip: String {
        if !appState.isConnected {
            return "Connect to server first"
        } else if !appState.microphonePermissionGranted {
            return "Microphone permission required"
        } else if appState.isRecording {
            return "Stop recording"
        } else {
            return "Start recording"
        }
    }
    
    private var statusText: String {
        if !appState.isConnected {
            return "Connect to server to start conversation"
        } else if !appState.microphonePermissionGranted {
            return "Microphone permission required"
        } else if appState.isRecording {
            return "Recording... Click to stop"
        } else if appState.isPlayingAudio {
            return "Assistant is speaking..."
        } else {
            return "Click to start recording"
        }
    }
}

#Preview {
    ChatView()
        .environmentObject(AppState())
        .frame(width: 400, height: 500)
} 