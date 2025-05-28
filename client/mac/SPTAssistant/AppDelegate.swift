//
//  AppDelegate.swift
//  SPTAssistant
//
//  Created by SPT Assistant Team
//  Copyright © 2025 SPT Assistant. All rights reserved.
//

import Cocoa
import SwiftUI
import AVFoundation

class AppDelegate: NSObject, NSApplicationDelegate {
    
    private var statusBarItem: NSStatusItem!
    private var popover: NSPopover!
    private var appState: AppState!
    
    func applicationDidFinishLaunching(_ aNotification: Notification) {
        // Initialize app state
        appState = AppState()
        
        // Create the status bar item
        statusBarItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        
        if let button = statusBarItem.button {
            // Set the menu bar icon
            button.image = NSImage(systemSymbolName: "waveform.circle", accessibilityDescription: "SPT Assistant")
            button.image?.isTemplate = true
            button.action = #selector(togglePopover(_:))
            button.target = self
            
            // Add right-click menu
            let menu = NSMenu()
            menu.addItem(NSMenuItem(title: "Show SPT Assistant", action: #selector(showApp), keyEquivalent: ""))
            menu.addItem(NSMenuItem.separator())
            menu.addItem(NSMenuItem(title: "Quit SPT Assistant", action: #selector(quitApp), keyEquivalent: "q"))
            button.menu = menu
        }
        
        // Create the popover
        popover = NSPopover()
        popover.contentSize = NSSize(width: 400, height: 600)
        popover.behavior = .transient
        popover.contentViewController = NSHostingController(rootView: ContentView().environmentObject(appState))
        
        // Hide dock icon and make this a menu bar only app
        NSApp.setActivationPolicy(.accessory)
        
        // Request microphone permissions early
        requestMicrophonePermissions()
    }
    
    @objc func togglePopover(_ sender: AnyObject?) {
        if let button = statusBarItem.button {
            if popover.isShown {
                popover.performClose(sender)
            } else {
                popover.show(relativeTo: button.bounds, of: button, preferredEdge: NSRectEdge.minY)
                // Activate the app to ensure the popover gets focus
                NSApp.activate(ignoringOtherApps: true)
            }
        }
    }
    
    @objc func showApp() {
        if !popover.isShown {
            togglePopover(nil)
        }
    }
    
    @MainActor @objc func quitApp() {
        appState.cleanup()
        NSApplication.shared.terminate(nil)
    }
    
    @MainActor private func requestMicrophonePermissions() {
        // Request microphone permissions using AVCaptureDevice for macOS
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            print("Microphone permission already granted")
            appState.microphonePermissionGranted = true
        case .denied, .restricted:
            print("Microphone permission denied")
            appState.microphonePermissionGranted = false
            showMicrophonePermissionAlert()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .audio) { granted in
                DispatchQueue.main.async {
                    if granted {
                        print("Microphone permission granted")
                        self.appState.microphonePermissionGranted = true
                    } else {
                        print("Microphone permission denied")
                        self.appState.microphonePermissionGranted = false
                        self.showMicrophonePermissionAlert()
                    }
                }
            }
        @unknown default:
            appState.microphonePermissionGranted = false
        }
    }
    
    private func showMicrophonePermissionAlert() {
        let alert = NSAlert()
        alert.messageText = "Microphone Access Required"
        alert.informativeText = "SPT Assistant needs microphone access to capture your voice for AI conversation. Please grant permission in System Preferences > Security & Privacy > Microphone."
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Open System Preferences")
        alert.addButton(withTitle: "Cancel")
        
        let response = alert.runModal()
        if response == .alertFirstButtonReturn {
            // Open System Preferences
            if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone") {
                NSWorkspace.shared.open(url)
            }
        }
    }
    
    func applicationWillTerminate(_ aNotification: Notification) {
        // Clean up resources
        appState.cleanup()
    }
    
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        // Show popover when app is reopened
        if !flag {
            togglePopover(nil)
        }
        return true
    }
} 