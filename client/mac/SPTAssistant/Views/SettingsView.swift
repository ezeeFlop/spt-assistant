//
//  SettingsView.swift
//  SPTAssistant
//
//  Created by SPT Assistant Team
//  Copyright © 2025 SPT Assistant. All rights reserved.
//

import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var appState: AppState
    @State private var serverURL: String = ""
    @State private var outputVolume: Float = 1.0
    
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                // Server Configuration
                ServerConfigurationSection()
                
                Divider()
                
                // Audio Device Configuration
                AudioDeviceSection()
                
                Divider()
                
                // Audio Settings
                AudioSettingsSection()
                
                Divider()
                
                // Permissions
                PermissionsSection()
                
                Spacer()
            }
            .padding()
        }
        .background(Color(NSColor.textBackgroundColor))
        .onAppear {
            serverURL = appState.serverURL
            outputVolume = appState.outputVolume
        }
    }
}

struct ServerConfigurationSection: View {
    @EnvironmentObject var appState: AppState
    @State private var serverURL: String = ""
    
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Server Configuration")
                .font(.headline)
                .fontWeight(.semibold)
            
            VStack(alignment: .leading, spacing: 8) {
                Text("Server URL")
                    .font(.subheadline)
                    .foregroundColor(.secondary)
                
                HStack {
                    TextField("ws://localhost:8000/api/v1/ws/audio", text: $serverURL)
                        .textFieldStyle(RoundedBorderTextFieldStyle())
                        .onSubmit {
                            appState.setServerURL(serverURL)
                        }
                    
                    Button("Save") {
                        appState.setServerURL(serverURL)
                    }
                    .disabled(serverURL == appState.serverURL)
                }
                
                Text("Enter the WebSocket URL of your SPT Assistant backend")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
        }
        .onAppear {
            serverURL = appState.serverURL
        }
    }
}

struct AudioDeviceSection: View {
    @EnvironmentObject var appState: AppState
    
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Audio Devices")
                    .font(.headline)
                    .fontWeight(.semibold)
                
                Spacer()
                
                Button("Refresh") {
                    appState.refreshAudioDevices()
                }
                .font(.caption)
            }
            
            // Input Device
            VStack(alignment: .leading, spacing: 8) {
                Text("Input Device (Microphone)")
                    .font(.subheadline)
                    .foregroundColor(.secondary)
                
                Picker("Input Device", selection: Binding(
                    get: { appState.selectedInputDevice?.id ?? "" },
                    set: { deviceId in
                        appState.selectedInputDevice = appState.inputDevices.first { $0.id == deviceId }
                    }
                )) {
                    ForEach(appState.inputDevices, id: \.id) { device in
                        HStack {
                            Text(device.name)
                            if device.isDefault {
                                Text("(Default)")
                                    .foregroundColor(.secondary)
                            }
                        }
                        .tag(device.id)
                    }
                }
                .pickerStyle(MenuPickerStyle())
            }
            
            // Output Device
            VStack(alignment: .leading, spacing: 8) {
                Text("Output Device (Speakers)")
                    .font(.subheadline)
                    .foregroundColor(.secondary)
                
                Picker("Output Device", selection: Binding(
                    get: { appState.selectedOutputDevice?.id ?? "" },
                    set: { deviceId in
                        appState.selectedOutputDevice = appState.outputDevices.first { $0.id == deviceId }
                    }
                )) {
                    ForEach(appState.outputDevices, id: \.id) { device in
                        HStack {
                            Text(device.name)
                            if device.isDefault {
                                Text("(Default)")
                                    .foregroundColor(.secondary)
                            }
                        }
                        .tag(device.id)
                    }
                }
                .pickerStyle(MenuPickerStyle())
            }
        }
    }
}

struct AudioSettingsSection: View {
    @EnvironmentObject var appState: AppState
    
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Audio Settings")
                .font(.headline)
                .fontWeight(.semibold)
            
            // Output Volume
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Text("Output Volume")
                        .font(.subheadline)
                        .foregroundColor(.secondary)
                    
                    Spacer()
                    
                    Text("\(Int(appState.outputVolume * 100))%")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                
                Slider(
                    value: Binding(
                        get: { appState.outputVolume },
                        set: { appState.setOutputVolume($0) }
                    ),
                    in: 0.0...2.0,
                    step: 0.1
                ) {
                    Text("Volume")
                } minimumValueLabel: {
                    Image(systemName: "speaker.fill")
                        .foregroundColor(.secondary)
                } maximumValueLabel: {
                    Image(systemName: "speaker.wave.3.fill")
                        .foregroundColor(.secondary)
                }
                
                Text("Adjust the output volume (0-200%)")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            
            // Echo Cancellation Info
            VStack(alignment: .leading, spacing: 8) {
                Text("Echo Cancellation")
                    .font(.subheadline)
                    .foregroundColor(.secondary)
                
                HStack {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundColor(.green)
                    Text("Voice processing enabled (setVoiceProcessingEnabled)")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                
                Text("SPT Assistant uses setVoiceProcessingEnabled(true) on AVAudioEngine - the macOS equivalent of iOS setPreferredEchoCancellationInInput(_:) - to prevent the assistant's voice from triggering barge-in detection.")
                    .font(.caption2)
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.leading)
            }
        }
    }
}

struct PermissionsSection: View {
    @EnvironmentObject var appState: AppState
    
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Permissions")
                .font(.headline)
                .fontWeight(.semibold)
            
            // Microphone Permission
            HStack {
                Image(systemName: appState.microphonePermissionGranted ? "checkmark.circle.fill" : "xmark.circle.fill")
                    .foregroundColor(appState.microphonePermissionGranted ? .green : .red)
                
                VStack(alignment: .leading, spacing: 2) {
                    Text("Microphone Access")
                        .font(.subheadline)
                    
                    Text(appState.microphonePermissionGranted ? "Granted" : "Not granted")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                
                Spacer()
                
                if !appState.microphonePermissionGranted {
                    Button("Open Settings") {
                        openSystemPreferences()
                    }
                    .font(.caption)
                }
            }
            
            Text("Microphone access is required to capture your voice for AI conversation.")
                .font(.caption)
                .foregroundColor(.secondary)
        }
    }
    
    private func openSystemPreferences() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone") {
            NSWorkspace.shared.open(url)
        }
    }
}

#Preview {
    SettingsView()
        .environmentObject(AppState())
        .frame(width: 400, height: 500)
} 