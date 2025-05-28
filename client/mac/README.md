# SPT Assistant - macOS Menu Bar Application

A native macOS menu bar application for the SPT Assistant voice AI system, featuring native Apple echo cancellation and a beautiful, modern interface.

## Features

- **Menu Bar Integration**: Lives in your menu bar for quick access
- **Advanced Echo Cancellation**: Uses macOS AVAudioEngine voice processing (equivalent to iOS setPreferredEchoCancellationInInput)
- **Real-time Audio Processing**: 16kHz audio capture and playback with low latency
- **Modern UI**: Beautiful SwiftUI interface following Apple's design guidelines
- **Device Selection**: Choose input and output audio devices
- **Volume Control**: Adjustable output volume (0-200%)
- **Auto-reconnection**: Automatic WebSocket reconnection with retry logic
- **Permissions Management**: Proper microphone permission handling

## Requirements

- macOS 14.0 or later
- Xcode 15.0 or later
- SPT Assistant backend running (see main README)

## Building

1. Open `SPTAssistant.xcodeproj` in Xcode
2. Select your development team in the project settings
3. Build and run (⌘+R)

## Usage

1. **First Launch**: Grant microphone permissions when prompted
2. **Menu Bar**: Click the waveform icon in your menu bar to open the interface
3. **Connect**: The app will auto-connect to `ws://localhost:8000/api/v1/ws/audio`
4. **Configure**: Use the Settings tab to:
   - Change server URL
   - Select audio devices
   - Adjust output volume
5. **Start Conversation**: Click the blue microphone button to start recording
6. **Stop Recording**: Click the red stop button or wait for automatic detection

## Echo Cancellation

The application uses **`setVoiceProcessingEnabled(true)`** on the AVAudioEngine input node, which is the macOS equivalent of iOS's `setPreferredEchoCancellationInInput(_:)`. This provides professional-grade echo cancellation that prevents the assistant's voice from being picked up by the microphone.

**Implementation Details:**
- **Voice Processing**: Uses `inputNode.setVoiceProcessingEnabled(true)` 
- **Real-time Echo Cancellation**: Automatically filters assistant voice from microphone input
- **Barge-in Prevention**: Prevents false triggers during assistant speech
- **Standard Apple API**: Uses the official Apple-recommended approach for voice applications

This is the same technology used in professional VoIP applications and provides robust echo cancellation specifically designed for voice assistant use cases. The implementation follows Apple's WWDC 2019 guidance for voice processing in AVAudioEngine.

## Architecture

The application follows modern SwiftUI patterns:

- **AppState**: Centralized state management using `@ObservableObject`
- **AudioManager**: Handles audio capture/playback with AVAudioEngine voice processing
- **WebSocketManager**: Manages WebSocket communication with the backend
- **Views**: Modular SwiftUI views for different UI components

## Configuration

Default settings:
- Server URL: `ws://localhost:8000/api/v1/ws/audio`
- Sample Rate: 16kHz
- Channels: Mono
- Audio Format: 16-bit PCM
- Output Volume: 100%
- Echo Cancellation: Enabled (voice processing)

Settings are automatically saved to UserDefaults.

## Troubleshooting

### Microphone Not Working
1. Check System Preferences > Security & Privacy > Microphone
2. Ensure SPT Assistant is listed and enabled
3. Restart the application

### Connection Issues
1. Verify the SPT Assistant backend is running
2. Check the server URL in Settings
3. Ensure WebSocket endpoint is accessible

### Audio Issues / Echo Problems
1. Check that voice processing is enabled in console logs
2. Verify both input and output voice processing are active
3. Try refreshing audio devices in Settings
4. Restart the application to reinitialize audio engine

### Echo Cancellation Not Working
1. Look for "✅ Voice processing (echo cancellation) enabled" in console
2. Ensure both input and output nodes show voice processing enabled
3. If echo cancellation fails to initialize, the app falls back to system-level processing
4. Restart the app if echo cancellation seems ineffective

## Development

The project structure:
```
SPTAssistant/
├── AppDelegate.swift          # Application lifecycle
├── main.swift                 # Application entry point
├── AppState.swift             # Centralized state management
├── Views/
│   ├── ContentView.swift      # Main interface
│   ├── ChatView.swift         # Chat and recording interface
│   └── SettingsView.swift     # Configuration interface
└── Managers/
    ├── AudioManager.swift     # Audio processing with voice processing echo cancellation
    └── WebSocketManager.swift # WebSocket communication
```

## License

Same as the main SPT Assistant project. 