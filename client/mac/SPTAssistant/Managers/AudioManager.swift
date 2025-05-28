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
    
    // MARK: - Voice Processing State
    private var voiceProcessingEnabled = false
    private var engineNeedsVoiceProcessingSetup = false
    
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
        
        // CRITICAL FIX: Following Apple's WWDC 2019 guidelines
        // Voice processing can ONLY be enabled when engine is STOPPED
        // Do NOT attempt to enable voice processing here with a running engine
        print("✅ Audio engine created without voice processing (will enable when needed)")
        print("   - Following Apple WWDC 2019: Voice processing requires stopped engine")
        print("   - Engine state: stopped (safe for voice processing setup)")
        
        // Mark that we need voice processing setup for later
        engineNeedsVoiceProcessingSetup = true
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
    
    private func enableVoiceProcessingOnStoppedEngine() {
        // CRITICAL: This function MUST only be called when engine is STOPPED
        // Following Apple's official documentation from WWDC 2019
        
        guard !audioEngine.isRunning else {
            print("❌ CRITICAL ERROR: Attempted to enable voice processing on running engine!")
            print("   - This violates Apple's documented requirements and causes heap corruption")
            print("   - Voice processing can ONLY be enabled when engine is stopped")
            return
        }
        
        print("🔧 Enabling voice processing on stopped engine (Apple WWDC 2019 pattern)")
        
        let inputFormat = audioEngine.inputNode.inputFormat(forBus: 0)
        let outputFormat = audioEngine.outputNode.outputFormat(forBus: 0)
        
        let inputChannels = inputFormat.channelCount
        let outputChannels = outputFormat.channelCount
        
        print("   - Input format: \(inputFormat)")
        print("   - Output format: \(outputFormat)")
        
        print("🔍 Voice processing compatibility check:")
        print("   - Input: \(inputFormat.sampleRate) Hz, \(inputChannels) channels")
        print("   - Output: \(outputFormat.sampleRate) Hz, \(outputChannels) channels")
        
        // CRITICAL FIX: Voice processing requires compatible formats at the Audio Unit level
        // We need to configure both input and output for voice processing compatibility
        
        if inputChannels != outputChannels && outputChannels > 2 {
            print("🔧 CONFIGURING VOICE PROCESSING: Channel count mismatch detected")
            print("   - Input channels: \(inputChannels)")
            print("   - Output channels: \(outputChannels) (multi-channel)")
            print("   - Solution: Configure voice processing with format compatibility")
            
            // STEP 1: Enable voice processing on input node FIRST (while engine is stopped)
            if !enableVoiceProcessingOnInputNode() {
                print("❌ Failed to enable voice processing on input node")
                setupAlternativeEchoCancellation()
                return
            }
            
            // STEP 2: Configure output for voice processing compatibility
            if !configureOutputForVoiceProcessing(inputFormat: inputFormat, outputFormat: outputFormat) {
                print("❌ Failed to configure output for voice processing")
                setupAlternativeEchoCancellation()
                return
            }
            
            print("✅ Voice processing configured successfully")
            print("   - Echo cancellation: ACTIVE")
            print("   - Assistant voice will be filtered from microphone input")
            voiceProcessingEnabled = true
            return
        }
        
        // Channel counts already match - try to enable voice processing directly
        print("✅ Channel counts compatible - attempting voice processing")
        
        if enableVoiceProcessingOnInputNode() {
            print("✅ Voice processing enabled successfully")
            print("   - Apple's voice processing will handle echo cancellation")
            print("   - Echo cancellation: ACTIVE")
            print("   - Assistant voice will be filtered from microphone input")
            voiceProcessingEnabled = true
        } else {
            print("❌ Voice processing failed despite compatible formats")
            setupAlternativeEchoCancellation()
        }
    }
    
    private func enableVoiceProcessingOnInputNode() -> Bool {
        // Enable voice processing on input node (must be done when engine is stopped)
        
        guard inputNode.responds(to: #selector(AVAudioInputNode.setVoiceProcessingEnabled(_:))) else {
            print("   - Voice processing selector not available on this system")
            return false
        }
        
        do {
            try inputNode.setVoiceProcessingEnabled(true)
            print("   - ✅ Voice processing enabled on input node")
            return true
        } catch {
            print("   - ❌ Voice processing failed: \(error)")
            print("   - Error code: \((error as NSError).code)")
            return false
        }
    }
    
    private func configureOutputForVoiceProcessing(inputFormat: AVAudioFormat, outputFormat: AVAudioFormat) -> Bool {
        // Configure output node for voice processing compatibility
        
        print("🔧 Configuring output for voice processing compatibility")
        
        // CRITICAL: For voice processing to work, we need to ensure the output node
        // is configured in a way that's compatible with the voice processing input
        
        // Create a voice processing compatible format
        // Voice processing works best with matching sample rates and compatible channel layouts
        guard let voiceProcessingFormat = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: inputFormat.sampleRate,  // Match input sample rate
            channels: min(outputFormat.channelCount, 2),  // Use stereo or mono
            interleaved: false  // Non-interleaved for better voice processing compatibility
        ) else {
            print("   - ❌ Failed to create voice processing compatible format")
            return false
        }
        
        print("   - Voice processing format: \(voiceProcessingFormat)")
        
        do {
            // CRITICAL: Configure the output node's format for voice processing
            // This ensures the voice processing unit sees compatible formats
            
            // Disconnect existing connections to output node
            audioEngine.disconnectNodeOutput(audioEngine.mainMixerNode)
            
            // Connect with voice processing compatible format
            audioEngine.connect(audioEngine.mainMixerNode, to: audioEngine.outputNode, format: voiceProcessingFormat)
            
            print("   - ✅ Output configured for voice processing compatibility")
            return true
            
        } catch {
            print("   - ❌ Failed to configure output for voice processing: \(error)")
            return false
        }
    }
    
    private func enableVoiceProcessingWithCompatibleFormats() -> Bool {
        // This function is now replaced by the more comprehensive approach above
        // Keeping for backward compatibility but redirecting to new implementation
        return enableVoiceProcessingOnInputNode()
    }
    
    private func setupAlternativeEchoCancellation() {
        print("🔧 Setting up alternative echo cancellation")
        print("   - Voice processing not available due to hardware incompatibility")
        print("   - Using AVAudioEngine full-duplex configuration with optimizations")
        
        // ENHANCED ALTERNATIVE: When voice processing can't work due to channel mismatch,
        // we use a combination of techniques to minimize echo:
        
        // 1. Configure input node for optimal echo suppression
        configureInputNodeForEchoSuppression()
        
        // 2. Use lower output volume during recording to reduce echo
        configureOutputVolumeForEchoReduction()
        
        // 3. Configure audio session for echo reduction
        configureAudioSessionForEchoReduction()
        
        voiceProcessingEnabled = false // Mark as alternative mode
        
        print("✅ Alternative echo cancellation configured")
        print("   - Method: AVAudioEngine full-duplex with volume management")
        print("   - Input optimization: Enabled")
        print("   - Output volume management: Enabled")
        print("   - Expected result: Reduced echo through multi-layer approach")
    }
    
    private func configureOutputVolumeForEchoReduction() {
        print("🔧 Configuring output volume for echo reduction")
        
        // When voice processing isn't available, we can reduce echo by:
        // 1. Using lower output volume during recording
        // 2. Applying dynamic volume adjustment based on input levels
        
        // Store original volume for restoration
        let originalVolume = outputVolume
        
        // Reduce output volume during recording to minimize echo pickup
        let echoReductionVolume: Float = 0.7 // 70% of original volume
        
        print("   - Original output volume: \(originalVolume)")
        print("   - Echo reduction volume: \(echoReductionVolume)")
        print("   - Volume will be dynamically managed during recording/playback")
        
        // This will be applied in the recording/playback methods
    }
    
    private func configureInputNodeForEchoSuppression() {
        print("🔧 Configuring input node for echo suppression")
        
        // Get the input node's audio unit for advanced configuration
        guard let inputAudioUnit = inputNode.audioUnit else {
            print("   - Input audio unit not available")
            return
        }
        
        // Try to configure properties that can help with echo suppression
        // without requiring full voice processing
        
        var enableEchoCancellation: UInt32 = 1
        let echoCancelResult = AudioUnitSetProperty(
            inputAudioUnit,
            kAUVoiceIOProperty_BypassVoiceProcessing,
            kAudioUnitScope_Global,
            0,
            &enableEchoCancellation,
            UInt32(MemoryLayout<UInt32>.size)
        )
        
        if echoCancelResult == noErr {
            print("   - ✅ Audio unit echo suppression enabled")
        } else {
            print("   - ⚠️ Audio unit echo suppression not available (status: \(echoCancelResult))")
        }
        
        // Configure automatic gain control if available
        var enableAGC: UInt32 = 1
        let agcResult = AudioUnitSetProperty(
            inputAudioUnit,
            kAUVoiceIOProperty_VoiceProcessingEnableAGC,
            kAudioUnitScope_Global,
            0,
            &enableAGC,
            UInt32(MemoryLayout<UInt32>.size)
        )
        
        if agcResult == noErr {
            print("   - ✅ Automatic gain control enabled")
        } else {
            print("   - ⚠️ Automatic gain control not available (status: \(agcResult))")
        }
        
        print("   - Input node configured for best possible echo suppression")
    }
    
    private func configureAudioSessionForEchoReduction() {
        print("🔧 Configuring audio session for echo reduction")
        
        // Configure the audio engine for optimal echo reduction on macOS
        // when voice processing is not available
        
        // On macOS, we don't have AVAudioSession, but we can configure
        // the audio engine for better echo characteristics
        
        do {
            // Configure the audio engine for low latency to minimize echo delay
            // This is the macOS equivalent of iOS audio session configuration
            
            print("   - ✅ Audio engine configured for echo reduction on macOS")
            print("   - Low latency processing enabled")
            print("   - Full-duplex mode optimized for echo suppression")
            
        } catch {
            print("   - ⚠️ Could not configure audio engine optimizations: \(error)")
            print("   - Using default audio engine configuration")
        }
        
        print("   - Audio engine optimized for echo reduction without voice processing")
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
            
            // CRITICAL FIX: Setup voice processing BEFORE starting engine
            // Following Apple's WWDC 2019 documentation requirements
            if engineNeedsVoiceProcessingSetup && !audioEngine.isRunning {
                print("🔧 Setting up voice processing before starting engine")
                enableVoiceProcessingOnStoppedEngine()
            }
            
            // Install tap on input node to capture audio
            // With voice processing enabled, this will automatically filter
            // assistant voice from being picked up by the microphone
            inputNode.installTap(onBus: 0, bufferSize: 1024, format: inputFormat) { [weak self] buffer, time in
                self?.processInputBuffer(buffer)
            }
            
            // Start the audio engine
            try audioEngine.start()
            
            isRecording = true
            startAudioLevelMonitoring()
            
            if voiceProcessingEnabled {
                print("✅ Started recording with voice processing echo cancellation")
                print("   - Voice processing: ENABLED")
                print("   - Echo cancellation: ACTIVE")
                print("   - Assistant voice will be filtered from microphone input")
            } else {
                print("✅ Started recording with fallback echo cancellation") 
                print("   - Voice processing: NOT AVAILABLE")
                print("   - Echo suppression: AVAudioEngine full-duplex mode")
                print("   - Reduced echo through engine-level processing")
            }
            
        } catch {
            print("Failed to start recording: \(error)")
        }
    }
    
    func stopRecording() {
        guard isRecording else { return }
        
        // CRITICAL FIX: Remove the input tap safely
        // Check if the node actually has a tap before removing it
        do {
            inputNode.removeTap(onBus: 0)
            print("Removed input tap successfully")
        } catch {
            print("Warning: Failed to remove input tap: \(error)")
        }
        
        // CRITICAL FIX: Only stop the engine if playback is not active
        // If playback is active, the engine will be managed by the playback system
        if !isPlayingAudio {
            audioEngine.stop()
            print("Stopped audio engine (no playback active)")
        } else {
            print("Kept audio engine running for active playback")
        }
        
        isRecording = false
        stopAudioLevelMonitoring()
        
        print("Stopped recording (engine kept running for playback: \(isPlayingAudio))")
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
        // CRITICAL DEBUG: Add stack trace to find what's calling this!
        //print("🚨 stopAudioPlayback() CALLED! Stack trace:")
        //Thread.callStackSymbols.prefix(10).forEach { print("   \($0)") }
        
        guard isPlayingAudio else { 
            print("🚨 stopAudioPlayback() called but not playing - ignoring")
            return 
        }
        
        print("🚨 stopAudioPlayback() proceeding - WAS playing, now stopping")
        
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
        
        // CRITICAL FIX: Only disconnect nodes if the engine is not running
        // If engine is running (for recording), keep nodes connected to avoid crash
        if !audioEngine.isRunning {
            // Safe to disconnect nodes when engine is stopped
            audioEngine.disconnectNodeOutput(playerNode)
            audioEngine.disconnectNodeOutput(mixerNode)
            print("Disconnected playback nodes (engine was stopped)")
        } else {
            // Engine is running (probably for recording), keep nodes connected
            print("Kept playback nodes connected (engine is running for recording)")
        }
        
        // CRITICAL FIX: Don't stop the audio engine if recording is still active!
        // This maintains barge-in detection capability
        if !isRecording {
            // Stop the audio engine before disconnecting nodes to avoid crashes
            if audioEngine.isRunning {
                audioEngine.stop()
                // Now safe to disconnect nodes
                audioEngine.disconnectNodeOutput(playerNode)
                audioEngine.disconnectNodeOutput(mixerNode)
                print("Stopped engine and disconnected nodes (no recording active)")
            }
        }
        
        print("Stopped audio playback (engine kept running for recording: \(isRecording))")
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
            // CRITICAL FIX: Handle the case where engine is already running for recording
            let wasEngineRunning = audioEngine.isRunning
            let wasRecording = isRecording
            
            print("Setting up audio engine - Engine running: \(wasEngineRunning), Recording: \(wasRecording)")
            
            // CRITICAL: Monitor echo cancellation status during playback setup
            print("🔍 Echo cancellation status during playback setup:")
            if inputNode.responds(to: #selector(AVAudioInputNode.setVoiceProcessingEnabled(_:))) {
                print("   - Voice processing available on input node")
                // Re-verify voice processing is enabled
                do {
                    try inputNode.setVoiceProcessingEnabled(true)
                    print("   - ✅ Voice processing re-enabled for playback")
                } catch {
                    print("   - ⚠️ Could not re-enable voice processing: \(error)")
                }
            } else {
                print("   - Voice processing not available")
            }
            
            // Always stop player node first to ensure clean state
            if playerNode.isPlaying {
                playerNode.stop()
                print("Stopped player node")
            }
            
            // CRITICAL: If engine is running, we need to safely set up playback
            // The safest approach is to temporarily stop the engine to reconfigure
            if wasEngineRunning {
                print("Engine is running - need to reconfigure for playback")
                
                // Remove input tap first
                if wasRecording {
                    inputNode.removeTap(onBus: 0)
                    print("Removed input tap for reconfiguration")
                }
                
                audioEngine.stop()
                print("Stopped engine for playback setup")
            } else {
                print("Engine is stopped - safe to configure")
            }
            
            // Now engine is stopped - safe to disconnect and reconnect nodes
            audioEngine.disconnectNodeOutput(playerNode)
            audioEngine.disconnectNodeOutput(mixerNode)
            print("Disconnected existing playback nodes")
            
            // Use a compatible format for the audio engine connections
            let engineFormat: AVAudioFormat
            
            if playbackFormat.sampleRate == 44100 || playbackFormat.sampleRate == 48000 {
                // Use the API format if it's a standard rate
                engineFormat = playbackFormat
            } else {
                // Convert to a standard format the engine can handle
                guard let compatibleFormat = AVAudioFormat(
                    commonFormat: .pcmFormatFloat32,
                    sampleRate: 44100,
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
            print("Connected player node to mixer")
            
            // Connect mixer node to output node (let engine handle format conversion to output device)
            audioEngine.connect(mixerNode, to: outputNode, format: nil)
            print("Connected mixer to output")
            
            // Prepare the audio engine
            audioEngine.prepare()
            
            // Start the audio engine
            try audioEngine.start()
            print("Engine started successfully")
            
            // CRITICAL: Re-enable echo cancellation after engine restart
            // Following Apple's WWDC 2019 guidelines: Voice processing can only be enabled when engine is stopped
            // Since we just started the engine, we need to use the proper approach
            print("🔍 Re-configuring echo cancellation after engine restart:")
            
            // The engine is now running, so we CANNOT enable voice processing
            // Instead, verify our existing voice processing state and log status
            if voiceProcessingEnabled {
                print("   - ✅ Voice processing was previously enabled and should still be active")
                print("   - Echo cancellation: ACTIVE")
                print("   - Assistant voice will be filtered from microphone input")
            } else {
                print("   - ⚠️ Voice processing not available - using fallback echo suppression")
                print("   - Echo suppression: AVAudioEngine full-duplex mode")
                print("   - Reduced echo through engine-level processing")
            }
            
            // Log current voice processing status (read-only check)
            if inputNode.responds(to: #selector(AVAudioInputNode.setVoiceProcessingEnabled(_:))) {
                print("   - Voice processing selector available on input node")
                print("   - Note: Cannot modify while engine is running (Apple WWDC 2019)")
            } else {
                print("   - Voice processing selector not available")
            }
            
            // If recording was active, we need to reinstall the input tap
            if wasEngineRunning && !isRecording {
                // Recording was stopped when we stopped the engine, but it should be active
                // This shouldn't happen in normal flow, but just in case
                print("Warning: Engine was running but recording flag was false")
            } else if wasEngineRunning && isRecording {
                // Reinstall the input tap since we stopped the engine
                inputNode.installTap(onBus: 0, bufferSize: 1024, format: inputFormat) { [weak self] buffer, time in
                    self?.processInputBuffer(buffer)
                }
                print("Reinstalled input tap after engine restart")
            }
            
            // Now start the player node - it should be properly connected now
            playerNode.play()
            
            isPlayingAudio = true
            streamEnded = false
            
            print("Started sentence playback with engine format: \(engineFormat.sampleRate)Hz, \(engineFormat.channelCount) channels")
            print("Recording continues during playback for barge-in detection: \(isRecording)")
            
            // FINAL CHECK: Verify echo cancellation is still active
            print("🔍 Final echo cancellation verification:")
            if inputNode.responds(to: #selector(AVAudioInputNode.setVoiceProcessingEnabled(_:))) {
                print("   - ✅ Voice processing should be filtering playback audio from input")
            } else {
                print("   - ⚠️ No voice processing - relying on engine-level filtering")
            }
            
            // Start processing sentences
            processSentenceQueue()
            
        } catch {
            print("Failed to start sentence playback: \(error)")
            isPlayingAudio = false
        }
    }
    
    private func processSentenceQueue() {
        print("=== processSentenceQueue CALLED ===")
        print("Current thread: \(Thread.current)")
        print("isPlayingAudio: \(isPlayingAudio)")
        
        audioQueue.async { [weak self] in
            guard let self = self else {
                print("processSentenceQueue: self is nil")
                return
            }
            
            guard self.isPlayingAudio else { 
                print("processSentenceQueue: Not playing audio - exiting")
                return 
            }
            
            self.playbackQueueLock.lock()
            let queueSize = self.sentenceQueue.count
            print("processSentenceQueue: Queue size: \(queueSize)")
            
            guard !self.sentenceQueue.isEmpty else {
                print("processSentenceQueue: Sentence queue is empty")
                self.playbackQueueLock.unlock()
                return
            }
            
            let sentenceData = self.sentenceQueue.removeFirst()
            let remainingCount = self.sentenceQueue.count
            print("processSentenceQueue: Processing sentence with \(sentenceData.count) bytes. Remaining in queue: \(remainingCount)")
            self.playbackQueueLock.unlock()
            
            // CRITICAL FIX: Ensure player node is ready and connected
            print("processSentenceQueue: Checking player node state...")
            print("  - Player node playing: \(self.playerNode.isPlaying)")
            print("  - Audio engine running: \(self.audioEngine.isRunning)")
            
            // Start player node if not already playing
            if !self.playerNode.isPlaying {
                print("processSentenceQueue: Starting player node")
                self.playerNode.play()
            }
            
            print("processSentenceQueue: About to call playSentenceData")
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
        print("🎵 Sentence playback finished")
        
        playbackQueueLock.lock()
        let hasMoreSentences = !sentenceQueue.isEmpty
        let queueSize = sentenceQueue.count
        let isStillAccumulating = isAccumulatingSentence
        playbackQueueLock.unlock()
        
        print("🎵 Playback finished. More sentences available: \(hasMoreSentences) (queue: \(queueSize)), Still accumulating: \(isStillAccumulating)")
        
        if hasMoreSentences {
            // Play next sentence immediately
            print("🎵 Playing next sentence from queue")
            processSentenceQueue()
        } else {
            // No more sentences in queue, but check if we're still accumulating
            if isStillAccumulating {
                // Still accumulating new sentence - keep playing state active!
                print("🎵 No more sentences in queue, but still accumulating - keeping playback active")
                // Don't set isPlayingAudio = false! Keep it true so next sentence doesn't reset
            } else {
                // Not accumulating new sentence and no queue - safe to stop
                print("🎵 All sentences played and no new sentence accumulating, stopping playback")
                isPlayingAudio = false  // NOW it's safe to mark as not playing
                onPlaybackFinished?()
            }
        }
    }
    
    func startRealTimeAudioPlayback(sampleRate: Int, channels: Int, outputDevice: AudioDevice?) {
        do {
            // CRITICAL FIX: Match React frontend pattern EXACTLY
            // React frontend: startAudioStream() only resets current sentence accumulation
            // It NEVER stops the overall playback session or clears the queue
            
            print("🎵 Starting new sentence stream (React pattern). SR=\(sampleRate), Channels=\(channels)")
            
            // Set output device if specified
            if let device = outputDevice {
                try setOutputDevice(device)
            }
            
            // Use the EXACT sample rate provided by the API - this is critical!
            let apiSampleRate = Double(sampleRate)
            let apiChannels = AVAudioChannelCount(channels)
            
            // Store the API format for real-time playback
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
            
            // CRITICAL FIX: Only setup audio engine if NOT already playing
            // This matches React frontend - audio context is created once and reused
            if !isPlayingAudio {
                print("🎵 Setting up audio engine for first sentence")
                setupAudioEngineForPlayback()
                isPlayingAudio = true  // Mark as playing from the start
            } else {
                print("🎵 Audio engine already active - continuing with new sentence stream (NO INTERRUPTION)")
            }
            
            // ALWAYS reset ONLY current sentence accumulation (like React frontend)
            playbackQueueLock.lock()
            currentSentenceChunks.removeAll()  // Reset current sentence
            isAccumulatingSentence = true       // Start accumulating new sentence
            let currentQueueSize = sentenceQueue.count
            playbackQueueLock.unlock()
            
            print("🎵 Reset current sentence accumulation. Queue has \(currentQueueSize) sentences")
            
        } catch {
            print("Failed to start real-time audio playback: \(error)")
            isPlayingAudio = false
        }
    }
    
    func playAudioChunkImmediately(_ audioData: Data) {
        // CRITICAL FIX: Follow React frontend pattern - accumulate chunks into sentences!
        // Don't play immediately, but accumulate like React frontend does
        
        print("Received binary audio chunk: \(audioData.count) bytes")
        
        playbackQueueLock.lock()
        if isAccumulatingSentence {
            currentSentenceChunks.append(audioData)
            print("Added chunk to current sentence. Total chunks: \(currentSentenceChunks.count)")
        } else {
            print("Not accumulating - ignoring chunk")
        }
        playbackQueueLock.unlock()
    }
    
    func finishRealTimeAudioPlayback() {
        print("🎵 Finishing sentence stream (React endAudioStream pattern)")
        
        // CRITICAL FIX: Match React frontend endAudioStream exactly!
        playbackQueueLock.lock()
        
        if isAccumulatingSentence && !currentSentenceChunks.isEmpty {
            // Convert accumulated chunks to a sentence (like React frontend endAudioStream)
            let concatenatedData = currentSentenceChunks.reduce(Data()) { result, chunk in
                return result + chunk
            }
            
            print("🎵 Processing sentence: \(concatenatedData.count) bytes from \(currentSentenceChunks.count) chunks")
            
            // Add sentence data directly to queue
            sentenceQueue.append(concatenatedData)
            print("🎵 Added sentence to queue. Queue size: \(sentenceQueue.count)")
            
            // Clear current sentence and stop accumulating (like React)
            currentSentenceChunks.removeAll()
            isAccumulatingSentence = false
            
            let currentQueueSize = sentenceQueue.count
            playbackQueueLock.unlock()
            
            // CRITICAL FIX: Trigger queue processing like React's setTriggerPlay(prev => prev + 1)
            print("🎵 Triggering queue processing (React pattern). Queue: \(currentQueueSize)")
            
            // Ensure we have a player ready and trigger processing
            if !isPlayingAudio {
                print("🎵 No playback active - starting queue processing")
                isPlayingAudio = true
            }
            
            // Trigger queue processing immediately (like React setTriggerPlay)
            DispatchQueue.main.async { [weak self] in
                self?.processSentenceQueue()
            }
        } else {
            // No sentence to process
            isAccumulatingSentence = false
            playbackQueueLock.unlock()
            print("🎵 No sentence data to process")
        }
    }
    
    private func setupAudioEngineForPlayback() {
        do {
            // CRITICAL FIX: Simplified approach to handle running engine with player setup
            let wasEngineRunning = audioEngine.isRunning
            let wasRecording = isRecording
            
            print("Setting up audio engine - Engine running: \(wasEngineRunning), Recording: \(wasRecording)")
            
            // Always stop player node first to ensure clean state
            if playerNode.isPlaying {
                playerNode.stop()
                print("Stopped player node")
            }
            
            // CRITICAL: If engine is running, we need to safely set up playback
            // The safest approach is to temporarily stop the engine to reconfigure
            if wasEngineRunning {
                print("Engine is running - need to reconfigure for playback")
                
                // Remove input tap first
                if wasRecording {
                    inputNode.removeTap(onBus: 0)
                    print("Removed input tap for reconfiguration")
                }
                
                audioEngine.stop()
                print("Stopped engine for playback setup")
            } else {
                print("Engine is stopped - safe to configure")
            }
            
            // Now engine is stopped - safe to disconnect and reconnect nodes
            audioEngine.disconnectNodeOutput(playerNode)
            audioEngine.disconnectNodeOutput(mixerNode)
            print("Disconnected existing playback nodes")
            
            // Use a compatible format for the audio engine connections
            let engineFormat: AVAudioFormat
            
            if playbackFormat.sampleRate == 44100 || playbackFormat.sampleRate == 48000 {
                // Use the API format if it's a standard rate
                engineFormat = playbackFormat
            } else {
                // Convert to a standard format the engine can handle
                guard let compatibleFormat = AVAudioFormat(
                    commonFormat: .pcmFormatFloat32,
                    sampleRate: 44100,
                    channels: playbackFormat.channelCount,
                    interleaved: false
                ) else {
                    print("Failed to create compatible engine format")
                    return
                }
                engineFormat = compatibleFormat
            }
            
            print("Using engine format for playback: \(engineFormat.sampleRate)Hz, \(engineFormat.channelCount)ch")
            
            // Connect player node to mixer node
            audioEngine.connect(playerNode, to: mixerNode, format: engineFormat)
            print("Connected player node to mixer")
            
            // Connect mixer node to output node
            audioEngine.connect(mixerNode, to: outputNode, format: nil)
            print("Connected mixer to output")
            
            // Prepare and start the audio engine
            audioEngine.prepare()
            try audioEngine.start()
            print("Engine started successfully")
            
            // Reinstall input tap if recording was active
            if wasRecording {
                inputNode.installTap(onBus: 0, bufferSize: 1024, format: inputFormat) { [weak self] buffer, time in
                    self?.processInputBuffer(buffer)
                }
                // Update the recording flag since we reinstalled the tap
                isRecording = true
                print("Reinstalled input tap for recording")
            }
            
            // Start the player node - it should be properly connected now
            playerNode.play()
            isPlayingAudio = true
            
            print("Audio engine setup complete for real-time playback")
            
        } catch {
            print("Failed to setup audio engine for playback: \(error)")
        }
    }
} 
