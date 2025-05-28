//
//  WebSocketManager.swift
//  SPTAssistant
//
//  Created by SPT Assistant Team
//  Copyright © 2025 SPT Assistant. All rights reserved.
//

import Foundation
import Combine

class WebSocketManager: NSObject, ObservableObject {
    
    // MARK: - Published Properties
    @Published var isConnected = false
    @Published var connectionStatus = "Disconnected"
    
    // MARK: - Properties
    private var webSocketTask: URLSessionWebSocketTask?
    private var urlSession: URLSession
    private var reconnectTimer: Timer?
    private var reconnectAttempts = 0
    private let maxReconnectAttempts = 5
    private let reconnectDelay: TimeInterval = 3.0
    
    // Track active conversation ID for binary audio chunks
    var activeConversationId: String?
    
    // MARK: - Callbacks
    var onMessageReceived: (([String: Any]) -> Void)?
    var onAudioChunkReceived: ((Data) -> Void)?
    
    override init() {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 60
        
        urlSession = URLSession(configuration: config, delegate: nil, delegateQueue: nil)
        super.init()
        
        // Set up the delegate after initialization
        urlSession = URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }
    
    // MARK: - Setup
    
    private func setupURLSession() {
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 30
        configuration.timeoutIntervalForResource = 60
        urlSession = URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
    }
    
    // MARK: - Public Methods
    
    func connect(to urlString: String) {
        guard let url = URL(string: urlString) else {
            connectionStatus = "Invalid URL"
            return
        }
        
        disconnect() // Disconnect any existing connection
        
        connectionStatus = "Connecting..."
        
        webSocketTask = urlSession.webSocketTask(with: url)
        webSocketTask?.resume()
        
        // Start listening for messages
        receiveMessage()
        
        print("Attempting to connect to: \(urlString)")
    }
    
    func disconnect() {
        webSocketTask?.cancel(with: .goingAway, reason: nil)
        webSocketTask = nil
        isConnected = false
        connectionStatus = "Disconnected"
        reconnectTimer?.invalidate()
        reconnectTimer = nil
        reconnectAttempts = 0
    }
    
    func sendAudioChunk(_ audioData: Data) {
        guard isConnected, let webSocketTask = webSocketTask else {
            print("Cannot send audio chunk: WebSocket not connected")
            return
        }
        
        let message = URLSessionWebSocketTask.Message.data(audioData)
        webSocketTask.send(message) { error in
            if let error = error {
                print("Failed to send audio chunk: \(error)")
            }
        }
    }
    
    func sendJSONMessage(_ message: [String: Any]) {
        guard isConnected, let webSocketTask = webSocketTask else {
            print("Cannot send JSON message: WebSocket not connected")
            return
        }
        
        do {
            let jsonData = try JSONSerialization.data(withJSONObject: message)
            let jsonString = String(data: jsonData, encoding: .utf8) ?? ""
            let wsMessage = URLSessionWebSocketTask.Message.string(jsonString)
            
            webSocketTask.send(wsMessage) { error in
                if let error = error {
                    print("Failed to send JSON message: \(error)")
                }
            }
        } catch {
            print("Failed to serialize JSON message: \(error)")
        }
    }
    
    // MARK: - Private Methods
    
    private func receiveMessage() {
        webSocketTask?.receive { [weak self] result in
            switch result {
            case .success(let message):
                self?.handleMessage(message)
                // Continue listening for more messages
                self?.receiveMessage()
                
            case .failure(let error):
                print("WebSocket receive error: \(error)")
                self?.handleDisconnection()
            }
        }
    }
    
    private func handleMessage(_ message: URLSessionWebSocketTask.Message) {
        switch message {
        case .string(let text):
            handleJSONMessage(text)
        case .data(let data):
            handleBinaryMessage(data)
        @unknown default:
            print("Unknown WebSocket message type")
        }
    }
    
    private func handleJSONMessage(_ text: String) {
        guard let data = text.data(using: .utf8) else {
            print("Failed to convert string to data")
            return
        }
        
        do {
            if let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] {
                DispatchQueue.main.async {
                    self.onMessageReceived?(json)
                }
            }
        } catch {
            print("Failed to parse JSON message: \(error)")
        }
    }
    
    private func handleBinaryMessage(_ data: Data) {
        // Binary messages are audio chunks - pass them directly to the app state
        // The app state will handle them as raw audio chunks with the proper conversation ID
        print("Received binary audio chunk: \(data.count) bytes")
        
        // Create a raw_audio_chunk message format that matches the React frontend
        let message: [String: Any] = [
            "type": "raw_audio_chunk",
            "data": data,
            "conversation_id": self.activeConversationId ?? "current"
        ]
        
        DispatchQueue.main.async {
            self.onMessageReceived?(message)
        }
    }
    
    private func handleConnection() {
        DispatchQueue.main.async {
            self.isConnected = true
            self.connectionStatus = "Connected"
            self.reconnectAttempts = 0
            self.reconnectTimer?.invalidate()
            self.reconnectTimer = nil
        }
        print("WebSocket connected successfully")
    }
    
    private func handleDisconnection() {
        DispatchQueue.main.async {
            self.isConnected = false
            self.connectionStatus = "Disconnected"
        }
        
        // Attempt to reconnect if we haven't exceeded max attempts
        if reconnectAttempts < maxReconnectAttempts {
            scheduleReconnect()
        } else {
            DispatchQueue.main.async {
                self.connectionStatus = "Connection failed"
            }
            print("Max reconnection attempts reached")
        }
    }
    
    private func scheduleReconnect() {
        reconnectAttempts += 1
        
        DispatchQueue.main.async {
            self.connectionStatus = "Reconnecting... (\(self.reconnectAttempts)/\(self.maxReconnectAttempts))"
        }
        
        reconnectTimer = Timer.scheduledTimer(withTimeInterval: reconnectDelay, repeats: false) { [weak self] _ in
            guard let self = self else { return }
            
            // Get the last URL from the webSocketTask
            if let url = self.webSocketTask?.originalRequest?.url {
                self.connect(to: url.absoluteString)
            }
        }
        
        print("Scheduled reconnection attempt \(reconnectAttempts) in \(reconnectDelay) seconds")
    }
}

// MARK: - URLSessionWebSocketDelegate

extension WebSocketManager: URLSessionWebSocketDelegate {
    
    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didOpenWithProtocol protocol: String?) {
        handleConnection()
    }
    
    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
        let reasonString = reason.flatMap { String(data: $0, encoding: .utf8) } ?? "Unknown"
        print("WebSocket closed with code: \(closeCode.rawValue), reason: \(reasonString)")
        handleDisconnection()
    }
}

// MARK: - URLSessionDelegate

extension WebSocketManager: URLSessionDelegate {
    
    func urlSession(_ session: URLSession, didBecomeInvalidWithError error: Error?) {
        if let error = error {
            print("URLSession became invalid: \(error)")
        }
        handleDisconnection()
    }
} 