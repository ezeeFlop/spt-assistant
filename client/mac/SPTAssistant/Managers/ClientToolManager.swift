//
//  ClientToolManager.swift
//  SPTAssistant
//
//  Created by SPT Assistant Team
//  Copyright © 2025 SPT Assistant. All rights reserved.
//

import Foundation
import Combine
import AppKit
import ScreenCaptureKit
import UniformTypeIdentifiers

// MARK: - Tool Parameter Definition
struct ToolParameter {
    let type: String
    let description: String
    let required: Bool
    let defaultValue: Any?
    
    init(type: String, description: String, required: Bool = false, defaultValue: Any? = nil) {
        self.type = type
        self.description = description
        self.required = required
        self.defaultValue = defaultValue
    }
}

// MARK: - Tool Definition
struct ToolDefinition {
    let name: String
    let description: String
    let parameters: [String: ToolParameter]
    
    init(name: String, description: String, parameters: [String: ToolParameter] = [:]) {
        self.name = name
        self.description = description
        self.parameters = parameters
    }
}

public class ClientToolManager: ObservableObject {
    
    // MARK: - Published Properties
    @Published var isToolExecuting = false
    @Published var lastToolResult: String?
    @Published var lastToolError: String?
    
    // MARK: - Private Properties
    private let clientId = "macos_client_\(UUID().uuidString.prefix(8))"
    private let platform = "macos"
    weak var webSocketManager: WebSocketManager?
    private var cancellables = Set<AnyCancellable>()
    
    // MARK: - Tool Registry
    private let availableTools: [String: ToolDefinition] = [
        "take_screenshot": ToolDefinition(
            name: "take_screenshot",
            description: "Captures a screenshot of the current screen and saves it to the Desktop",
            parameters: [
                "filename": ToolParameter(
                    type: "string",
                    description: "Optional filename for the screenshot (without extension)",
                    required: false,
                    defaultValue: "screenshot"
                ),
                "format": ToolParameter(
                    type: "string",
                    description: "Image format: png or jpg",
                    required: false,
                    defaultValue: "png"
                ),
                "include_cursor": ToolParameter(
                    type: "boolean",
                    description: "Whether to include the mouse cursor in the screenshot",
                    required: false,
                    defaultValue: false
                )
            ]
        ),
        
        "open_application": ToolDefinition(
            name: "open_application",
            description: "Opens a macOS application by name or bundle identifier",
            parameters: [
                "application": ToolParameter(
                    type: "string",
                    description: "Application name (e.g., 'Safari', 'TextEdit') or bundle identifier (e.g., 'com.apple.Safari')",
                    required: true
                ),
                "activate": ToolParameter(
                    type: "boolean",
                    description: "Whether to bring the application to the foreground",
                    required: false,
                    defaultValue: true
                )
            ]
        ),
        
        "search_files": ToolDefinition(
            name: "search_files",
            description: "Searches for files and folders on the system using Spotlight",
            parameters: [
                "query": ToolParameter(
                    type: "string",
                    description: "Search query (filename, content, or metadata)",
                    required: true
                ),
                "file_types": ToolParameter(
                    type: "array",
                    description: "Optional array of file extensions to filter by (e.g., ['txt', 'pdf', 'doc'])",
                    required: false,
                    defaultValue: []
                ),
                "max_results": ToolParameter(
                    type: "integer",
                    description: "Maximum number of results to return",
                    required: false,
                    defaultValue: 10
                ),
                "search_path": ToolParameter(
                    type: "string",
                    description: "Optional path to limit search scope (e.g., '~/Documents')",
                    required: false,
                    defaultValue: ""
                )
            ]
        )
    ]
    
    // MARK: - Initialization
    init() {
        print("ClientToolManager initialized with \(availableTools.count) available tools")
    }
    
    // MARK: - Public Methods
    
    func setWebSocketManager(_ manager: WebSocketManager) {
        self.webSocketManager = manager
        setupToolRequestListener()
        registerCapabilities()
    }
    
    func getAvailableTools() -> [String: Any] {
        var capabilities: [String: Any] = [:]
        
        for (toolName, toolDef) in availableTools {
            capabilities[toolName] = [
                "description": toolDef.description,
                "parameters": [
                    "type": "object",
                    "properties": toolDef.parameters.mapValues { param in
                        var paramDict: [String: Any] = [
                            "type": param.type,
                            "description": param.description
                        ]
                        if let defaultValue = param.defaultValue {
                            paramDict["default"] = defaultValue
                        }
                        return paramDict
                    },
                    "required": toolDef.parameters.compactMap { key, param in
                        param.required ? key : nil
                    }
                ]
            ]
        }
        
        return capabilities
    }
    
    func registerCapabilities(conversationId: String) {
        // Register capabilities for a specific conversation
        guard let webSocketManager = webSocketManager else { return }
        
        let capabilities = getAvailableTools()
        let registrationMessage: [String: Any] = [
            "type": "client_capabilities",
            "client_id": clientId,
            "platform": platform,
            "conversation_id": conversationId,
            "capabilities": capabilities,
            "timestamp": Date().timeIntervalSince1970
        ]
        
        webSocketManager.sendJSONMessage(registrationMessage)
        print("Registered client capabilities for conversation \(conversationId): \(Array(capabilities.keys))")
    }
    
    func handleToolRequest(_ message: [String: Any]) {
        // Handle tool request from WebSocket message
        guard let toolCallId = message["tool_call_id"] as? String,
              let toolName = message["tool_name"] as? String,
              let conversationId = message["conversation_id"] as? String else {
            print("Invalid tool request format")
            return
        }
        
        let argumentsString = message["arguments"] as? String ?? "{}"
        
        print("Received tool request: \(toolName) for conversation \(conversationId)")
        
        Task {
            await executeToolRequest(
                toolCallId: toolCallId,
                toolName: toolName,
                arguments: argumentsString,
                conversationId: conversationId
            )
        }
    }
    
    // Method expected by AppState
    func executeToolCall(
        toolCallId: String,
        toolName: String,
        arguments: [String: Any],
        conversationId: String
    ) async -> [String: Any]? {
        var result: [String: Any]
        var success = false
        
        do {
            // Execute the appropriate tool
            switch toolName {
            case "take_screenshot":
                result = await executeTakeScreenshot(args: arguments)
                success = true
                
            case "open_application":
                result = await executeOpenApplication(args: arguments)
                success = true
                
            case "search_files":
                result = await executeSearchFiles(args: arguments)
                success = true
                
            default:
                result = ["error": "Unknown tool: \(toolName)"]
                success = false
            }
            
        } catch {
            result = ["error": "Failed to execute tool: \(error.localizedDescription)"]
            success = false
        }
        
        // Send response back to server
        await sendToolResponse(
            toolCallId: toolCallId,
            conversationId: conversationId,
            success: success,
            result: result
        )
        
        return result
    }
    
    // MARK: - Private Methods
    
    private func setupToolRequestListener() {
        // The WebSocketManager will call handleToolRequest directly when tool requests are received
        // This is handled in ContentView.swift setupIntegration()
        print("Tool request listener setup - will be handled via ContentView integration")
    }
    
    private func registerCapabilities() {
        guard let webSocketManager = webSocketManager else { return }
        
        let capabilities = getAvailableTools()
        let registrationMessage: [String: Any] = [
            "type": "client_capabilities",
            "client_id": clientId,
            "platform": platform,
            "capabilities": capabilities,
            "timestamp": Date().timeIntervalSince1970
        ]
        
        if let jsonData = try? JSONSerialization.data(withJSONObject: registrationMessage),
           let jsonString = String(data: jsonData, encoding: .utf8) {
            webSocketManager.sendJSONMessage(registrationMessage)
            print("Registered client capabilities: \(Array(capabilities.keys))")
        }
    }
    
    private func executeToolRequest(
        toolCallId: String,
        toolName: String,
        arguments: String,
        conversationId: String
    ) async {
        var result: [String: Any]
        var success = false
        
        do {
            // Parse arguments
            let argumentsData = arguments.data(using: .utf8) ?? Data()
            let args = try JSONSerialization.jsonObject(with: argumentsData) as? [String: Any] ?? [:]
            
            // Execute the appropriate tool
            switch toolName {
            case "take_screenshot":
                result = await executeTakeScreenshot(args: args)
                success = true
                
            case "open_application":
                result = await executeOpenApplication(args: args)
                success = true
                
            case "search_files":
                result = await executeSearchFiles(args: args)
                success = true
                
            default:
                result = ["error": "Unknown tool: \(toolName)"]
                success = false
            }
            
        } catch {
            result = ["error": "Failed to parse tool arguments: \(error.localizedDescription)"]
            success = false
        }
        
        // Send response back to server
        await sendToolResponse(
            toolCallId: toolCallId,
            conversationId: conversationId,
            success: success,
            result: result
        )
    }
    
    private func sendToolResponse(
        toolCallId: String,
        conversationId: String,
        success: Bool,
        result: [String: Any]
    ) async {
        let response: [String: Any] = [
            "type": "tool_response",
            "tool_call_id": toolCallId,
            "conversation_id": conversationId,
            "success": success,
            "result": result,
            "timestamp": Date().timeIntervalSince1970
        ]
        
        webSocketManager?.sendJSONMessage(response)
        print("Sent tool response for \(toolCallId): success=\(success)")
    }
    
    // MARK: - Tool Implementations
    
    private func executeTakeScreenshot(args: [String: Any]) async -> [String: Any] {
        let filename = args["filename"] as? String ?? "screenshot"
        let format = args["format"] as? String ?? "png"
        let includeCursor = args["include_cursor"] as? Bool ?? false
        
        do {
            // Get available displays using ScreenCaptureKit
            let availableContent = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
            guard let display = availableContent.displays.first else {
                return ["error": "No displays available for screenshot"]
            }
            
            // Create screenshot configuration
            let filter = SCContentFilter(display: display, excludingWindows: [])
            let configuration = SCStreamConfiguration()
            configuration.width = Int(display.width)
            configuration.height = Int(display.height)
            configuration.pixelFormat = kCVPixelFormatType_32BGRA
            configuration.showsCursor = includeCursor
            
            // Capture screenshot using SCScreenshotManager
            let cgImage = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: configuration)
            
            // Convert to NSImage for easier handling
            let nsImage = NSImage(cgImage: cgImage, size: NSSize(width: CGFloat(cgImage.width), height: CGFloat(cgImage.height)))
            
            // Prepare file path
            let desktopPath = FileManager.default.urls(for: .desktopDirectory, in: .userDomainMask).first!
            let timestamp = DateFormatter().apply {
                $0.dateFormat = "yyyy-MM-dd_HH-mm-ss"
            }.string(from: Date())
            let finalFilename = "\(filename)_\(timestamp).\(format)"
            let fileURL = desktopPath.appendingPathComponent(finalFilename)
            
            // Save image
            guard let tiffData = nsImage.tiffRepresentation else {
                return ["error": "Failed to convert image to TIFF"]
            }
            
            let bitmapRep = NSBitmapImageRep(data: tiffData)
            let imageData: Data?
            
            if format.lowercased() == "jpg" || format.lowercased() == "jpeg" {
                imageData = bitmapRep?.representation(using: .jpeg, properties: [.compressionFactor: 0.9])
            } else {
                imageData = bitmapRep?.representation(using: .png, properties: [:])
            }
            
            guard let data = imageData else {
                return ["error": "Failed to convert image to \(format) format"]
            }
            
            try data.write(to: fileURL)
            
            return [
                "success": true,
                "message": "Screenshot saved successfully",
                "file_path": fileURL.path,
                "filename": finalFilename,
                "format": format,
                "size": [
                    "width": cgImage.width,
                    "height": cgImage.height
                ]
            ]
            
        } catch {
            return ["error": "Failed to save screenshot: \(error.localizedDescription)"]
        }
    }
    
    private func executeOpenApplication(args: [String: Any]) async -> [String: Any] {
        guard let applicationName = args["application"] as? String else {
            return ["error": "Missing required parameter: application"]
        }
        
        let activate = args["activate"] as? Bool ?? true
        
        do {
            let workspace = NSWorkspace.shared
            var appURL: URL?
            
            // Try to find app by bundle identifier first
            if applicationName.contains(".") {
                appURL = workspace.urlForApplication(withBundleIdentifier: applicationName)
            }
            
            // If not found, try by name
            if appURL == nil {
                // Try exact name match
                appURL = workspace.urlForApplication(withBundleIdentifier: "com.apple.\(applicationName)")
                
                // If still not found, search for app by name
                if appURL == nil {
                    let apps = workspace.runningApplications
                    for app in apps {
                        if app.localizedName?.lowercased() == applicationName.lowercased() {
                            if let bundleId = app.bundleIdentifier {
                                appURL = workspace.urlForApplication(withBundleIdentifier: bundleId)
                                break
                            }
                        }
                    }
                }
                
                // Last resort: try to find in Applications folder
                if appURL == nil {
                    let applicationsURL = URL(fileURLWithPath: "/Applications")
                    let appName = applicationName.hasSuffix(".app") ? applicationName : "\(applicationName).app"
                    let potentialURL = applicationsURL.appendingPathComponent(appName)
                    
                    if FileManager.default.fileExists(atPath: potentialURL.path) {
                        appURL = potentialURL
                    }
                }
            }
            
            guard let url = appURL else {
                return ["error": "Application '\(applicationName)' not found"]
            }
            
            // Launch the application
            let configuration = NSWorkspace.OpenConfiguration()
            configuration.activates = activate
            
            try await workspace.openApplication(at: url, configuration: configuration)
            
            // Get app info
            let bundle = Bundle(url: url)
            let appName = bundle?.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String ??
                         bundle?.object(forInfoDictionaryKey: "CFBundleName") as? String ??
                         url.deletingPathExtension().lastPathComponent
            
            return [
                "success": true,
                "message": "Application opened successfully",
                "application_name": appName ?? applicationName,
                "application_path": url.path,
                "bundle_identifier": bundle?.bundleIdentifier ?? "unknown",
                "activated": activate
            ]
            
        } catch {
            return ["error": "Failed to open application '\(applicationName)': \(error.localizedDescription)"]
        }
    }
    
    private func executeSearchFiles(args: [String: Any]) async -> [String: Any] {
        guard let query = args["query"] as? String, !query.isEmpty else {
            return ["error": "Missing required parameter: query"]
        }
        
        let fileTypes = args["file_types"] as? [String] ?? []
        let maxResults = args["max_results"] as? Int ?? 10
        let searchPath = args["search_path"] as? String ?? ""
        
        return await withCheckedContinuation { continuation in
            // Create metadata query
            let metadataQuery = NSMetadataQuery()
            
            // Build predicate
            var predicates: [NSPredicate] = []
            
            // Main search predicate
            let mainPredicate = NSPredicate(format: "kMDItemDisplayName LIKE[cd] '*\(query)*' OR kMDItemTextContent LIKE[cd] '*\(query)*'")
            predicates.append(mainPredicate)
            
            // File type filter
            if !fileTypes.isEmpty {
                let typePredicates = fileTypes.map { type in
                    NSPredicate(format: "kMDItemFSName LIKE[cd] '*.\(type)'")
                }
                let typePredicate = NSCompoundPredicate(orPredicateWithSubpredicates: typePredicates)
                predicates.append(typePredicate)
            }
            
            // Search path filter
            if !searchPath.isEmpty {
                let expandedPath = NSString(string: searchPath).expandingTildeInPath
                let pathPredicate = NSPredicate(format: "kMDItemPath LIKE '\(expandedPath)*'")
                predicates.append(pathPredicate)
            }
            
            // Combine all predicates
            let compoundPredicate = NSCompoundPredicate(andPredicateWithSubpredicates: predicates)
            metadataQuery.predicate = compoundPredicate
            
            // Set search scopes
            if !searchPath.isEmpty {
                let expandedPath = NSString(string: searchPath).expandingTildeInPath
                metadataQuery.searchScopes = [URL(fileURLWithPath: expandedPath)]
            } else {
                metadataQuery.searchScopes = [NSMetadataQueryLocalComputerScope]
            }
            
            // Set up completion handler
            var observer: NSObjectProtocol?
            observer = NotificationCenter.default.addObserver(
                forName: .NSMetadataQueryDidFinishGathering,
                object: metadataQuery,
                queue: .main
            ) { _ in
                metadataQuery.stop()
                
                if let observer = observer {
                    NotificationCenter.default.removeObserver(observer)
                }
                
                var results: [[String: Any]] = []
                let resultCount = min(metadataQuery.resultCount, maxResults)
                
                for i in 0..<resultCount {
                    if let item = metadataQuery.result(at: i) as? NSMetadataItem {
                        var fileInfo: [String: Any] = [:]
                        
                        if let path = item.value(forAttribute: NSMetadataItemPathKey) as? String {
                            fileInfo["path"] = path
                            fileInfo["name"] = URL(fileURLWithPath: path).lastPathComponent
                            
                            // Get file attributes
                            do {
                                let attributes = try FileManager.default.attributesOfItem(atPath: path)
                                if let size = attributes[.size] as? Int64 {
                                    fileInfo["size"] = size
                                }
                                if let modificationDate = attributes[.modificationDate] as? Date {
                                    fileInfo["modified"] = ISO8601DateFormatter().string(from: modificationDate)
                                }
                                if let fileType = attributes[.type] as? FileAttributeType {
                                    fileInfo["type"] = fileType == .typeDirectory ? "directory" : "file"
                                }
                            } catch {
                                // Ignore file attribute errors
                            }
                        }
                        
                        if let displayName = item.value(forAttribute: NSMetadataItemDisplayNameKey) as? String {
                            fileInfo["display_name"] = displayName
                        }
                        
                        if let contentType = item.value(forAttribute: NSMetadataItemContentTypeKey) as? String {
                            fileInfo["content_type"] = contentType
                        }
                        
                        results.append(fileInfo)
                    }
                }
                
                let response: [String: Any] = [
                    "success": true,
                    "message": "File search completed",
                    "query": query,
                    "results_count": results.count,
                    "max_results": maxResults,
                    "search_path": searchPath.isEmpty ? "entire system" : searchPath,
                    "file_types": fileTypes,
                    "results": results
                ]
                
                continuation.resume(returning: response)
            }
            
            // Start the search
            metadataQuery.start()
            
            // Set a timeout
            DispatchQueue.main.asyncAfter(deadline: .now() + 10) {
                if metadataQuery.isGathering {
                    metadataQuery.stop()
                    if let observer = observer {
                        NotificationCenter.default.removeObserver(observer)
                    }
                    continuation.resume(returning: [
                        "error": "Search timed out after 10 seconds"
                    ])
                }
            }
        }
    }
}

// MARK: - Extensions

extension DateFormatter {
    func apply(_ closure: (DateFormatter) -> Void) -> DateFormatter {
        closure(self)
        return self
    }
} 