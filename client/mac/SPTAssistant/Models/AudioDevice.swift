//
//  AudioDevice.swift
//  SPTAssistant
//
//  Created by SPT Assistant Team
//  Copyright © 2025 SPT Assistant. All rights reserved.
//

import Foundation

// MARK: - Audio Device Model
class AudioDevice: ObservableObject, Identifiable, Hashable {
    let id: String
    let name: String
    let isInput: Bool
    let isOutput: Bool
    var isDefault: Bool
    
    init(id: String, name: String, isInput: Bool, isOutput: Bool, isDefault: Bool) {
        self.id = id
        self.name = name
        self.isInput = isInput
        self.isOutput = isOutput
        self.isDefault = isDefault
    }
    
    // MARK: - Hashable
    func hash(into hasher: inout Hasher) {
        hasher.combine(id)
    }
    
    // MARK: - Equatable
    static func == (lhs: AudioDevice, rhs: AudioDevice) -> Bool {
        return lhs.id == rhs.id
    }
} 