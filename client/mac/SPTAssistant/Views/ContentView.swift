//
//  ContentView.swift
//  SPTAssistant
//
//  Created by SPT Assistant Team
//  Copyright © 2025 SPT Assistant. All rights reserved.
//

import SwiftUI

struct ContentView: View {
    @EnvironmentObject var appState: AppState
    @State private var selectedTab = 0
    
    var body: some View {
        VStack(spacing: 0) {
            // Header
            HeaderView()
            
            // Tab View
            TabView(selection: $selectedTab) {
                // Main Chat Tab
                ChatView()
                    .tabItem {
                        Image(systemName: "message.circle")
                        Text("Chat")
                    }
                    .tag(0)
                
                // Settings Tab
                SettingsView()
                    .tabItem {
                        Image(systemName: "gear")
                        Text("Settings")
                    }
                    .tag(1)
            }
            .frame(height: 500)
        }
        .frame(width: 400, height: 600)
        .background(Color(NSColor.windowBackgroundColor))
        .onAppear {
            // Auto-connect on startup
            if !appState.isConnected {
                appState.connect()
            }
        }
    }
}

struct HeaderView: View {
    @EnvironmentObject var appState: AppState
    
    var body: some View {
        VStack(spacing: 8) {
            // Title and Status
            HStack {
                Image(systemName: "waveform.circle.fill")
                    .foregroundColor(.blue)
                    .font(.title2)
                
                VStack(alignment: .leading, spacing: 2) {
                    Text("SPT Assistant")
                        .font(.headline)
                        .fontWeight(.semibold)
                    
                    HStack(spacing: 4) {
                        Circle()
                            .fill(appState.isConnected ? Color.green : Color.red)
                            .frame(width: 8, height: 8)
                        
                        Text(appState.connectionStatus)
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
                
                Spacer()
                
                // Connection Button
                Button(action: {
                    if appState.isConnected {
                        appState.disconnect()
                    } else {
                        appState.connect()
                    }
                }) {
                    Image(systemName: appState.isConnected ? "wifi.slash" : "wifi")
                        .foregroundColor(appState.isConnected ? .red : .blue)
                }
                .buttonStyle(PlainButtonStyle())
                .help(appState.isConnected ? "Disconnect" : "Connect")
                
                // Quit Button
                Button(action: {
                    appState.cleanup()
                    NSApplication.shared.terminate(nil)
                }) {
                    Image(systemName: "xmark.circle")
                        .foregroundColor(.secondary)
                }
                .buttonStyle(PlainButtonStyle())
                .help("Quit SPT Assistant")
            }
            
            // Audio Levels
            if appState.isRecording || appState.isPlayingAudio {
                AudioLevelsView()
            }
        }
        .padding()
        .background(Color(NSColor.controlBackgroundColor))
    }
}

struct AudioLevelsView: View {
    @EnvironmentObject var appState: AppState
    
    var body: some View {
        HStack(spacing: 12) {
            // Microphone Level
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 4) {
                    Image(systemName: "mic.fill")
                        .foregroundColor(appState.isRecording ? .red : .secondary)
                        .font(.caption)
                    Text("Mic")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }
                
                ProgressView(value: Double(appState.micAudioLevel), total: 1.0)
                    .progressViewStyle(LinearProgressViewStyle(tint: .red))
                    .frame(height: 4)
            }
            
            // Playback Level
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 4) {
                    Image(systemName: "speaker.wave.2.fill")
                        .foregroundColor(appState.isPlayingAudio ? .blue : .secondary)
                        .font(.caption)
                    Text("Speaker")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }
                
                ProgressView(value: Double(appState.playbackAudioLevel), total: 1.0)
                    .progressViewStyle(LinearProgressViewStyle(tint: .blue))
                    .frame(height: 4)
            }
        }
    }
}

#Preview {
    ContentView()
        .environmentObject(AppState())
} 