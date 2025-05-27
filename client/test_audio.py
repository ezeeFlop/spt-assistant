#!/usr/bin/env python3
"""Test script for audio functionality."""

import asyncio
import time
import sys
import os

# Add the client to the path
sys.path.insert(0, os.path.dirname(__file__))

from spt_assistant_client.spt_client import SPTClient

async def test_audio():
    """Test audio functionality."""
    print("🧪 Testing SPT Client Audio...")
    
    client = SPTClient()
    client.main_loop = asyncio.get_event_loop()
    
    try:
        await client.start()
        print("✅ Client started successfully")
        
        # Wait a moment for connection
        await asyncio.sleep(2)
        
        if client.websocket_client and client.websocket_client.is_connected:
            print("✅ WebSocket connected")
        else:
            print("❌ WebSocket not connected")
            return
        
        # Test audio output
        if client.audio_processor:
            print("🔊 Testing audio output...")
            client.audio_processor.test_audio_output()
            print("✅ Audio test completed")
        else:
            print("❌ Audio processor not available")
        
        # Wait a bit more
        await asyncio.sleep(2)
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await client.stop()
        print("🛑 Client stopped")

if __name__ == "__main__":
    asyncio.run(test_audio()) 