#!/bin/bash

# Find the latest build of SPT Assistant
APP_PATH=$(find ~/Library/Developer/Xcode/DerivedData/SPTAssistant*/Build/Products/Debug/SPTAssistant.app -type d 2>/dev/null | head -1)

if [ -z "$APP_PATH" ]; then
    echo "SPT Assistant app not found. Please build the project first."
    echo "Run: xcodebuild -project SPTAssistant.xcodeproj -scheme SPTAssistant -configuration Debug build"
    exit 1
fi

echo "Launching SPT Assistant from: $APP_PATH"
open "$APP_PATH" 