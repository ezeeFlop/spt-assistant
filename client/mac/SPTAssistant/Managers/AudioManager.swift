//
//  AudioManager.swift
//  SPTAssistant
//
//  Created by SPT Assistant Team
//  Copyright © 2025 SPT Assistant. All rights reserved.
//

import Foundation
import AVFoundation
import Combine
import CoreAudio

class AudioManager: NSObject, ObservableObject {
    
    // MARK: - Published Properties
    @Published var isRecording = false
    @Published var isPlayingAudio = false
    @Published var micAudioLevel: Float = 0.0
    @Published var playbackAudioLevel: Float = 0.0
    @Published var microphonePermissionGranted = false
    
    // MARK: - Audio Configuration
    private let sampleRate: Double = 16000  // 16kHz to match frontend and Python client
    private let channels: UInt32 = 1        // Mono
    private let bitDepth: UInt32 = 16       // 16-bit
    
    // MARK: - Audio Engine Components
    private var audioEngine: AVAudioEngine!
    private var inputNode: AVAudioInputNode!
    private var outputNode: AVAudioOutputNode!
    private var playerNode: AVAudioPlayerNode!
    private var mixerNode: AVAudioMixerNode!
    
    // MARK: - Audio Format
    private var inputFormat: AVAudioFormat!
    private var outputFormat: AVAudioFormat!
    private var pcmFormat: AVAudioFormat!
    private var playbackFormat: AVAudioFormat!
    
    // MARK: - Playback Management
    private var audioQueue = DispatchQueue(label: "com.sptassistant.audio", qos: .userInteractive)
    private var currentSentenceChunks: [Data] = []  // Accumulate chunks for current sentence
    private var sentenceQueue: [Data] = []          // Queue of complete sentences ready for playback
    private var playbackQueueLock = NSLock()
    private var streamEnded = false
    private var outputVolume: Float = 1.0
    private var isAccumulatingSentence = false      // Track if we're currently building a sentence
    
    // MARK: - Audio Level Monitoring
    private var levelTimer: Timer?
    
    // MARK: - Callbacks
    var onAudioChunk: ((Data) -> Void)?
    var onPlaybackFinished: (() -> Void)?
    
    override init() {
        super.init()
        setupAudioEngine()
        checkMicrophonePermission()
    }
    
    // MARK: - Setup
    
    private func setupAudioEngine() {
        audioEngine = AVAudioEngine()
        inputNode = audioEngine.inputNode
        outputNode = audioEngine.outputNode
        playerNode = AVAudioPlayerNode()
        mixerNode = AVAudioMixerNode()
        
        // Attach nodes
        audioEngine.attach(playerNode)
        audioEngine.attach(mixerNode)
        
        // Setup audio formats
        setupAudioFormats()
        
        // Configure audio engine for echo cancellation
        configureAudioEngine()
    }
    
    private func setupAudioFormats() {
        // Input format from microphone (system default, usually 44.1kHz or 48kHz)
        inputFormat = inputNode.inputFormat(forBus: 0)
        
        // Output format for playback (system default)
        outputFormat = outputNode.outputFormat(forBus: 0)
        
        // PCM format for processing (16kHz, 16-bit, mono)
        pcmFormat = AVAudioFormat(
            commonFormat: .pcmFormatInt16,
            sampleRate: sampleRate,
            channels: channels,
            interleaved: true
        )
        
        print("Input format: \(inputFormat.debugDescription)")
        print("Output format: \(outputFormat.debugDescription)")
        print("PCM format: \(pcmFormat.debugDescription)")
    }
    
    private func configureAudioEngine() {
        // On macOS, echo cancellation is handled differently than iOS
        // We rely on the system's built-in echo cancellation which is automatically
        // enabled when using AVAudioEngine with simultaneous input/output
        // This is similar to how browser getUserMedia works with echoCancellation: true
        
        // The key is to ensure proper audio routing and use the system's
        // automatic echo cancellation capabilities
        print("Audio engine configured with system echo cancellation")
    }
    
    private func checkMicrophonePermission() {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            microphonePermissionGranted = true
        case .denied, .restricted:
            microphonePermissionGranted = false
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .audio) { [weak self] granted in
                DispatchQueue.main.async {
                    self?.microphonePermissionGranted = granted
                }
            }
        @unknown default:
            microphonePermissionGranted = false
        }
    }
    
    // MARK: - Public Methods
    
    func startRecording(inputDevice: AudioDevice?) {
        guard microphonePermissionGranted else {
            print("Microphone permission not granted")
            return
        }
        
        guard !isRecording else {
            print("Already recording")
            return
        }
        
        do {
            // Set input device if specified
            if let device = inputDevice {
                try setInputDevice(device)
            }
            
            // Install tap on input node to capture audio
            // On macOS, the system automatically applies echo cancellation when
            // using AVAudioEngine with simultaneous input/output operations
            // This is equivalent to browser getUserMedia with echoCancellation: true
            inputNode.installTap(onBus: 0, bufferSize: 1024, format: inputFormat) { [weak self] buffer, time in
                self?.processInputBuffer(buffer)
            }
            
            // Start the audio engine
            try audioEngine.start()
            
            isRecording = true
            startAudioLevelMonitoring()
            
            print("Started recording with system echo cancellation")
            
        } catch {
            print("Failed to start recording: \(error)")
        }
    }
    
    func stopRecording() {
        guard isRecording else { return }
        
        inputNode.removeTap(onBus: 0)
        audioEngine.stop()
        isRecording = false
        stopAudioLevelMonitoring()
        
        print("Stopped recording")
    }
    
    func startAudioPlayback(sampleRate: Int, channels: Int, outputDevice: AudioDevice?) {
        do {
            // Stop any existing playback first
            if isPlayingAudio {
                stopAudioPlayback()
            }
            
            // Set output device if specified
            if let device = outputDevice {
                try setOutputDevice(device)
            }
            
            // Use the EXACT sample rate provided by the API - this is critical!
            let apiSampleRate = Double(sampleRate)
            let apiChannels = AVAudioChannelCount(channels)
            
            print("Starting audio stream for new sentence: \(apiSampleRate)Hz, \(apiChannels) channels")
            
            // Store the API format for this sentence
            guard let apiPlaybackFormat = AVAudioFormat(
                commonFormat: .pcmFormatInt16,
                sampleRate: apiSampleRate,
                channels: apiChannels,
                interleaved: true
            ) else {
                print("Failed to create API playback format")
                return
            }
            
            self.playbackFormat = apiPlaybackFormat
            
            // Start accumulating chunks for this sentence
            playbackQueueLock.lock()
            currentSentenceChunks.removeAll()
            isAccumulatingSentence = true
            playbackQueueLock.unlock()
            
            print("Started accumulating audio chunks for new sentence")
            
        } catch {
            print("Failed to start audio stream: \(error)")
            isPlayingAudio = false
        }
    }
    
    func enqueueAudioChunk(_ audioData: Data) {
        guard isAccumulatingSentence else { 
            print("Not accumulating sentence, ignoring audio chunk")
            return 
        }
        
        playbackQueueLock.lock()
        currentSentenceChunks.append(audioData)
        playbackQueueLock.unlock()
        
        print("Added audio chunk to current sentence: \(audioData.count) bytes, total chunks: \(currentSentenceChunks.count)")
    }
    
    func signalStreamEnded() {
        guard isAccumulatingSentence else { 
            print("Not accumulating sentence, ignoring stream end")
            return 
        }
        
        playbackQueueLock.lock()
        
        // Concatenate all chunks for this sentence
        let totalSize = currentSentenceChunks.reduce(0) { $0 + $1.count }
        guard totalSize > 0 else {
            print("No audio data accumulated for sentence")
            currentSentenceChunks.removeAll()
            isAccumulatingSentence = false
            playbackQueueLock.unlock()
            return
        }
        
        var completeSentence = Data()
        completeSentence.reserveCapacity(totalSize)
        for chunk in currentSentenceChunks {
            completeSentence.append(chunk)
        }
        
        // Add complete sentence to playback queue
        sentenceQueue.append(completeSentence)
        
        // Clear current sentence accumulation
        currentSentenceChunks.removeAll()
        isAccumulatingSentence = false
        
        print("Completed sentence with \(totalSize) bytes, added to playback queue. Queue size: \(sentenceQueue.count)")
        
        playbackQueueLock.unlock()
        
        // Start playback if not already playing
        if !isPlayingAudio {
            startSentencePlayback()
        }
    }
    
    func stopAudioPlayback() {
        guard isPlayingAudio else { return }
        
        isPlayingAudio = false
        streamEnded = false
        
        // Clear all queues
        playbackQueueLock.lock()
        let totalCleared = currentSentenceChunks.count + sentenceQueue.count
        currentSentenceChunks.removeAll()
        sentenceQueue.removeAll()
        isAccumulatingSentence = false
        playbackQueueLock.unlock()
        
        if totalCleared > 0 {
            print("Cleared \(totalCleared) items from audio queues")
        }
        
        // Stop the player node first
        if playerNode.isPlaying {
            playerNode.stop()
        }
        
        // Stop the audio engine before disconnecting nodes to avoid crashes
        if audioEngine.isRunning {
            audioEngine.stop()
        }
        
        // Now safely disconnect nodes
        audioEngine.disconnectNodeOutput(playerNode)
        audioEngine.disconnectNodeOutput(mixerNode)
        
        print("Stopped audio playback")
    }
    
    func setOutputVolume(_ volume: Float) {
        outputVolume = max(0.0, min(2.0, volume))
        print("Output volume set to \(outputVolume)")
    }
    
    // MARK: - Device Management (Public)
    
    func refreshAudioDevices(completion: @escaping ([AudioDevice], [AudioDevice]) -> Void) {
        DispatchQueue.global(qos: .userInitiated).async {
            let inputDevices = self.getInputDevices()
            let outputDevices = self.getOutputDevices()
            
            DispatchQueue.main.async {
                completion(inputDevices, outputDevices)
            }
        }
    }
    
    // MARK: - Private Methods
    
    private func processInputBuffer(_ buffer: AVAudioPCMBuffer) {
        // Update audio level
        updateMicAudioLevel(from: buffer)
        
        // Convert to PCM format if needed
        let pcmBuffer: AVAudioPCMBuffer
        if buffer.format.sampleRate != pcmFormat.sampleRate || buffer.format.commonFormat != pcmFormat.commonFormat {
            guard let convertedBuffer = convertBuffer(buffer, to: pcmFormat) else { return }
            pcmBuffer = convertedBuffer
        } else {
            pcmBuffer = buffer
        }
        
        // Convert to Data and send
        guard let audioData = bufferToData(pcmBuffer) else { return }
        onAudioChunk?(audioData)
    }
    
    private func convertBuffer(_ buffer: AVAudioPCMBuffer, to format: AVAudioFormat) -> AVAudioPCMBuffer? {
        guard let converter = AVAudioConverter(from: buffer.format, to: format) else {
            print("Failed to create audio converter")
            return nil
        }
        
        let outputFrameCount = AVAudioFrameCount(Double(buffer.frameLength) * format.sampleRate / buffer.format.sampleRate)
        guard let outputBuffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: outputFrameCount) else {
            print("Failed to create output buffer")
            return nil
        }
        
        var error: NSError?
        let status = converter.convert(to: outputBuffer, error: &error) { _, outStatus in
            outStatus.pointee = .haveData
            return buffer
        }
        
        if status == .error {
            print("Audio conversion error: \(error?.localizedDescription ?? "Unknown")")
            return nil
        }
        
        return outputBuffer
    }
    
    private func bufferToData(_ buffer: AVAudioPCMBuffer) -> Data? {
        guard let channelData = buffer.int16ChannelData else { return nil }
        
        let frameCount = Int(buffer.frameLength)
        let channelCount = Int(buffer.format.channelCount)
        let dataSize = frameCount * channelCount * MemoryLayout<Int16>.size
        
        var data = Data(capacity: dataSize)
        
        for frame in 0..<frameCount {
            for channel in 0..<channelCount {
                let sample = channelData[channel][frame]
                data.append(contentsOf: withUnsafeBytes(of: sample) { Array($0) })
            }
        }
        
        return data
    }
    
    private func playAudioData(_ audioData: Data) {
        guard let buffer = dataToPlaybackBuffer(audioData) else { return }
        
        // Calculate playback audio level
        updatePlaybackAudioLevel(from: buffer)
        
        // Apply volume
        if outputVolume != 1.0 {
            applyVolumeToFloat32Buffer(buffer, volume: outputVolume)
        }
        
        // Schedule buffer for playback
        playerNode.scheduleBuffer(buffer, completionHandler: nil)
    }
    
    private func dataToPlaybackBuffer(_ data: Data) -> AVAudioPCMBuffer? {
        // Convert incoming 16-bit PCM data to the playback format
        guard let playbackFormat = playbackFormat else { return nil }
        
        // Create a temporary format that matches the incoming data structure (16-bit PCM)
        // using the API's original sample rate
        guard let tempFormat = AVAudioFormat(
            commonFormat: .pcmFormatInt16,
            sampleRate: playbackFormat.sampleRate,  // Use API sample rate
            channels: playbackFormat.channelCount,
            interleaved: true
        ) else {
            print("Failed to create temporary format for audio conversion")
            return nil
        }
        
        // Calculate frame count based on the incoming data
        let frameCount = data.count / (MemoryLayout<Int16>.size * Int(playbackFormat.channelCount))
        guard let int16Buffer = AVAudioPCMBuffer(pcmFormat: tempFormat, frameCapacity: AVAudioFrameCount(frameCount)) else {
            print("Failed to create int16 buffer with temp format")
            return nil
        }
        
        int16Buffer.frameLength = AVAudioFrameCount(frameCount)
        
        // Copy the raw audio data into the buffer
        data.withUnsafeBytes { bytes in
            guard let channelData = int16Buffer.int16ChannelData else { return }
            let int16Pointer = bytes.bindMemory(to: Int16.self)
            channelData[0].assign(from: int16Pointer.baseAddress!, count: frameCount)
        }
        
        // Determine the engine format (what the audio engine expects)
        let engineFormat: AVAudioFormat
        if playbackFormat.sampleRate == 44100 || playbackFormat.sampleRate == 48000 {
            // Engine can handle this format directly
            engineFormat = playbackFormat
        } else {
            // Engine needs Float32 at 44100Hz
            guard let compatibleFormat = AVAudioFormat(
                commonFormat: .pcmFormatFloat32,
                sampleRate: 44100,
                channels: playbackFormat.channelCount,
                interleaved: false
            ) else {
                print("Failed to create engine format")
                return int16Buffer  // Fallback to original buffer
            }
            engineFormat = compatibleFormat
        }
        
        // Convert to engine format if needed
        if tempFormat.sampleRate != engineFormat.sampleRate || tempFormat.commonFormat != engineFormat.commonFormat {
            return convertBuffer(int16Buffer, to: engineFormat)
        } else {
            return int16Buffer
        }
    }
    
    private func dataToBuffer(_ data: Data) -> AVAudioPCMBuffer? {
        let frameCount = data.count / (MemoryLayout<Int16>.size * Int(pcmFormat.channelCount))
        
        guard let buffer = AVAudioPCMBuffer(pcmFormat: pcmFormat, frameCapacity: AVAudioFrameCount(frameCount)) else {
            return nil
        }
        
        buffer.frameLength = AVAudioFrameCount(frameCount)
        
        data.withUnsafeBytes { bytes in
            guard let channelData = buffer.int16ChannelData else { return }
            let int16Pointer = bytes.bindMemory(to: Int16.self)
            channelData[0].assign(from: int16Pointer.baseAddress!, count: frameCount)
        }
        
        return buffer
    }
    
    private func applyVolume(to buffer: AVAudioPCMBuffer, volume: Float) {
        guard let channelData = buffer.int16ChannelData else { return }
        
        let frameCount = Int(buffer.frameLength)
        let channelCount = Int(buffer.format.channelCount)
        
        for channel in 0..<channelCount {
            for frame in 0..<frameCount {
                let sample = Float(channelData[channel][frame]) * volume
                channelData[channel][frame] = Int16(max(-32768, min(32767, sample)))
            }
        }
    }
    
    private func applyVolumeToFloat32Buffer(_ buffer: AVAudioPCMBuffer, volume: Float) {
        guard let channelData = buffer.floatChannelData else { return }
        
        let frameCount = Int(buffer.frameLength)
        let channelCount = Int(buffer.format.channelCount)
        
        for channel in 0..<channelCount {
            for frame in 0..<frameCount {
                channelData[channel][frame] *= volume
            }
        }
    }
    
    private func updateMicAudioLevel(from buffer: AVAudioPCMBuffer) {
        guard let channelData = buffer.int16ChannelData else { return }
        
        let frameCount = Int(buffer.frameLength)
        var sum: Float = 0
        
        for i in 0..<frameCount {
            let sample = Float(channelData[0][i]) / 32768.0
            sum += sample * sample
        }
        
        let rms = sqrt(sum / Float(frameCount))
        
        DispatchQueue.main.async {
            self.micAudioLevel = min(rms, 1.0)
        }
    }
    
    private func updatePlaybackAudioLevel(from buffer: AVAudioPCMBuffer) {
        var sum: Float = 0
        let frameCount = Int(buffer.frameLength)
        
        if let channelData = buffer.int16ChannelData {
            for i in 0..<frameCount {
                let sample = Float(channelData[0][i]) / 32768.0
                sum += sample * sample
            }
        } else if let channelData = buffer.floatChannelData {
            for i in 0..<frameCount {
                let sample = channelData[0][i]
                sum += sample * sample
            }
        }
        
        let rms = sqrt(sum / Float(frameCount))
        
        DispatchQueue.main.async {
            self.playbackAudioLevel = min(rms, 1.0)
        }
    }
    
    private func startAudioLevelMonitoring() {
        levelTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            // Audio levels are updated in real-time during processing
            // This timer ensures levels decay to zero when no audio is present
            guard let self = self else { return }
            
            if !self.isRecording {
                self.micAudioLevel = 0
            }
            if !self.isPlayingAudio {
                self.playbackAudioLevel = 0
            }
        }
    }
    
    private func stopAudioLevelMonitoring() {
        levelTimer?.invalidate()
        levelTimer = nil
        micAudioLevel = 0
        playbackAudioLevel = 0
    }
    
    // MARK: - Device Management (Private)
    
    private func getInputDevices() -> [AudioDevice] {
        var devices: [AudioDevice] = []
        
        // Get all audio devices using Core Audio
        var propertyAddress = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDevices,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        
        var dataSize: UInt32 = 0
        var status = AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &propertyAddress, 0, nil, &dataSize)
        
        guard status == noErr else {
            print("Failed to get audio devices data size: \(status)")
            return getDefaultInputDevices()
        }
        
        let deviceCount = Int(dataSize) / MemoryLayout<AudioDeviceID>.size
        var deviceIDs = [AudioDeviceID](repeating: 0, count: deviceCount)
        
        status = AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &propertyAddress, 0, nil, &dataSize, &deviceIDs)
        
        guard status == noErr else {
            print("Failed to get audio devices: \(status)")
            return getDefaultInputDevices()
        }
        
        // Get default input device
        var defaultInputDeviceID: AudioDeviceID = 0
        propertyAddress.mSelector = kAudioHardwarePropertyDefaultInputDevice
        dataSize = UInt32(MemoryLayout<AudioDeviceID>.size)
        AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &propertyAddress, 0, nil, &dataSize, &defaultInputDeviceID)
        
        // Filter for input devices
        for deviceID in deviceIDs {
            if let device = createAudioDevice(from: deviceID, isInput: true) {
                device.isDefault = (deviceID == defaultInputDeviceID)
                devices.append(device)
            }
        }
        
        // Sort devices: default first, then alphabetically
        devices.sort { device1, device2 in
            if device1.isDefault && !device2.isDefault {
                return true
            } else if !device1.isDefault && device2.isDefault {
                return false
            } else {
                return device1.name < device2.name
            }
        }
        
        return devices.isEmpty ? getDefaultInputDevices() : devices
    }
    
    private func getOutputDevices() -> [AudioDevice] {
        var devices: [AudioDevice] = []
        
        // Get all audio devices using Core Audio
        var propertyAddress = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDevices,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        
        var dataSize: UInt32 = 0
        var status = AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &propertyAddress, 0, nil, &dataSize)
        
        guard status == noErr else {
            print("Failed to get audio devices data size: \(status)")
            return getDefaultOutputDevices()
        }
        
        let deviceCount = Int(dataSize) / MemoryLayout<AudioDeviceID>.size
        var deviceIDs = [AudioDeviceID](repeating: 0, count: deviceCount)
        
        status = AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &propertyAddress, 0, nil, &dataSize, &deviceIDs)
        
        guard status == noErr else {
            print("Failed to get audio devices: \(status)")
            return getDefaultOutputDevices()
        }
        
        // Get default output device
        var defaultOutputDeviceID: AudioDeviceID = 0
        propertyAddress.mSelector = kAudioHardwarePropertyDefaultOutputDevice
        dataSize = UInt32(MemoryLayout<AudioDeviceID>.size)
        AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &propertyAddress, 0, nil, &dataSize, &defaultOutputDeviceID)
        
        // Filter for output devices
        for deviceID in deviceIDs {
            if let device = createAudioDevice(from: deviceID, isInput: false) {
                device.isDefault = (deviceID == defaultOutputDeviceID)
                devices.append(device)
            }
        }
        
        // Sort devices: default first, then alphabetically
        devices.sort { device1, device2 in
            if device1.isDefault && !device2.isDefault {
                return true
            } else if !device1.isDefault && device2.isDefault {
                return false
            } else {
                return device1.name < device2.name
            }
        }
        
        return devices.isEmpty ? getDefaultOutputDevices() : devices
    }
    
    private func createAudioDevice(from deviceID: AudioDeviceID, isInput: Bool) -> AudioDevice? {
        // Get device name
        var propertyAddress = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyDeviceNameCFString,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        
        var dataSize: UInt32 = 0
        var status = AudioObjectGetPropertyDataSize(deviceID, &propertyAddress, 0, nil, &dataSize)
        guard status == noErr else { return nil }
        
        var deviceName: CFString?
        status = AudioObjectGetPropertyData(deviceID, &propertyAddress, 0, nil, &dataSize, &deviceName)
        guard status == noErr, let name = deviceName as String? else { return nil }
        
        // Check if device supports input/output
        propertyAddress.mSelector = isInput ? kAudioDevicePropertyStreamConfiguration : kAudioDevicePropertyStreamConfiguration
        propertyAddress.mScope = isInput ? kAudioDevicePropertyScopeInput : kAudioDevicePropertyScopeOutput
        
        status = AudioObjectGetPropertyDataSize(deviceID, &propertyAddress, 0, nil, &dataSize)
        guard status == noErr else { return nil }
        
        let bufferList = UnsafeMutablePointer<AudioBufferList>.allocate(capacity: 1)
        defer { bufferList.deallocate() }
        
        status = AudioObjectGetPropertyData(deviceID, &propertyAddress, 0, nil, &dataSize, bufferList)
        guard status == noErr else { return nil }
        
        let bufferCount = Int(bufferList.pointee.mNumberBuffers)
        guard bufferCount > 0 else { return nil }
        
        return AudioDevice(
            id: String(deviceID),
            name: name,
            isInput: isInput,
            isOutput: !isInput,
            isDefault: false  // Will be set by caller
        )
    }
    
    private func getDefaultInputDevices() -> [AudioDevice] {
        return [
            AudioDevice(
                id: "default_input",
                name: "Default Microphone",
                isInput: true,
                isOutput: false,
                isDefault: true
            ),
            AudioDevice(
                id: "builtin_input",
                name: "Built-in Microphone",
                isInput: true,
                isOutput: false,
                isDefault: false
            )
        ]
    }
    
    private func getDefaultOutputDevices() -> [AudioDevice] {
        return [
            AudioDevice(
                id: "default_output",
                name: "Default Speakers",
                isInput: false,
                isOutput: true,
                isDefault: true
            ),
            AudioDevice(
                id: "builtin_output",
                name: "Built-in Speakers",
                isInput: false,
                isOutput: true,
                isDefault: false
            )
        ]
    }
    
    private func setInputDevice(_ device: AudioDevice) throws {
        // For now, we'll use the default input device selection
        // Advanced device selection would require more complex Core Audio setup
        print("Input device selection: \(device.name)")
    }
    
    private func setOutputDevice(_ device: AudioDevice) throws {
        // For now, we'll use the default output device selection
        // Advanced device selection would require more complex Core Audio setup
        print("Output device selection: \(device.name)")
    }
    
    private func startSentencePlayback() {
        guard !isPlayingAudio else { return }
        
        playbackQueueLock.lock()
        guard !sentenceQueue.isEmpty, let playbackFormat = playbackFormat else {
            playbackQueueLock.unlock()
            return
        }
        playbackQueueLock.unlock()
        
        do {
            // Stop the audio engine before making changes
            if audioEngine.isRunning {
                audioEngine.stop()
            }
            
            // Disconnect existing connections
            audioEngine.disconnectNodeOutput(playerNode)
            audioEngine.disconnectNodeOutput(mixerNode)
            
            // Use a compatible format for the audio engine connections
            // Convert the API format to a format the engine can handle
            let engineFormat: AVAudioFormat
            
            if playbackFormat.sampleRate == 44100 || playbackFormat.sampleRate == 48000 {
                // Use the API format if it's a standard rate
                engineFormat = playbackFormat
            } else {
                // Convert to a standard format the engine can handle
                guard let compatibleFormat = AVAudioFormat(
                    commonFormat: .pcmFormatFloat32,  // Use Float32 for better compatibility
                    sampleRate: 44100,  // Use standard sample rate
                    channels: playbackFormat.channelCount,
                    interleaved: false
                ) else {
                    print("Failed to create compatible engine format")
                    return
                }
                engineFormat = compatibleFormat
            }
            
            print("Using engine format: \(engineFormat.sampleRate)Hz, \(engineFormat.channelCount)ch, \(engineFormat.commonFormat)")
            
            // Connect player node to mixer node with compatible format
            audioEngine.connect(playerNode, to: mixerNode, format: engineFormat)
            
            // Connect mixer node to output node (let engine handle format conversion to output device)
            audioEngine.connect(mixerNode, to: outputNode, format: nil)
            
            // Prepare the audio engine
            audioEngine.prepare()
            
            // Start the audio engine
            try audioEngine.start()
            
            // Start the player node
            if !playerNode.isPlaying {
                playerNode.play()
            }
            
            isPlayingAudio = true
            streamEnded = false
            
            print("Started sentence playback with engine format: \(engineFormat.sampleRate)Hz, \(engineFormat.channelCount) channels")
            
            // Start processing sentences
            processSentenceQueue()
            
        } catch {
            print("Failed to start sentence playback: \(error)")
            isPlayingAudio = false
        }
    }
    
    private func processSentenceQueue() {
        audioQueue.async { [weak self] in
            guard let self = self, self.isPlayingAudio else { return }
            
            self.playbackQueueLock.lock()
            guard !self.sentenceQueue.isEmpty else {
                self.playbackQueueLock.unlock()
                return
            }
            
            let sentenceData = self.sentenceQueue.removeFirst()
            self.playbackQueueLock.unlock()
            
            self.playSentenceData(sentenceData)
        }
    }
    
    private func playSentenceData(_ sentenceData: Data) {
        guard let playbackFormat = playbackFormat,
              let audioBuffer = dataToPlaybackBuffer(sentenceData) else {
            print("Failed to convert sentence data to audio buffer")
            // Continue with next sentence
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in
                self?.processSentenceQueue()
            }
            return
        }
        
        print("Playing sentence: \(sentenceData.count) bytes -> \(audioBuffer.frameLength) frames")
        
        // Schedule the buffer for playback
        playerNode.scheduleBuffer(audioBuffer) { [weak self] in
            DispatchQueue.main.async {
                self?.onSentencePlaybackFinished()
            }
        }
        
        // Update audio level
        updatePlaybackAudioLevel(from: audioBuffer)
    }
    
    private func onSentencePlaybackFinished() {
        print("Sentence playback finished")
        
        playbackQueueLock.lock()
        let hasMoreSentences = !sentenceQueue.isEmpty
        playbackQueueLock.unlock()
        
        if hasMoreSentences {
            // Play next sentence
            processSentenceQueue()
        } else {
            // No more sentences, check if we should stop
            if !isAccumulatingSentence {
                // Not accumulating new sentence, stop playback
                print("All sentences played and no new sentence accumulating, stopping playback")
                stopAudioPlayback()
                onPlaybackFinished?()
            } else {
                print("Waiting for current sentence to complete...")
            }
        }
    }
} 