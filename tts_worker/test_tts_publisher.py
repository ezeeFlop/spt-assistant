import redis
import json
import uuid

# --- Configuration ---
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0
REDIS_PASSWORD = None  # Set if you have a password
TTS_REQUEST_CHANNEL = "tts_request_channel"

# --- Test Data ---
conversation_id = f"test_conv_{uuid.uuid4()}"
text_to_speak = "Bonjour le monde, ceci est un test du service de synthèse vocale."
# Using a common French voice model for Piper, adjust if needed or omit for default
voice_id = "fr_FR-siwis-medium.onnx" 
# For ElevenLabs, an example voice_id might be "pNInz6obpgDQGcFmaJgB" (Rachel)
# If testing ElevenLabs, ensure your .env for tts_service has TTS_PROVIDER="elevenlabs" and the API key.

payload = {
    "conversation_id": conversation_id,
    "text_to_speak": text_to_speak,
    "voice_id": voice_id,
    "options": {} # e.g., {"speaker_idx": 0} for Piper if model has multiple speakers
}

if __name__ == "__main__":
    print(f"Attempting to connect to Redis at {REDIS_HOST}:{REDIS_PORT}, DB {REDIS_DB}...")
    try:
        r = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD,
            decode_responses=True # Easier to work with strings for this publisher
        )
        r.ping()
        print("Successfully connected to Redis.")
    except redis.exceptions.ConnectionError as e:
        print(f"Error connecting to Redis: {e}")
        print("Please ensure Redis is running and accessible.")
        exit(1)

    try:
        message_json = json.dumps(payload)
        print(f"Publishing to channel '{TTS_REQUEST_CHANNEL}':")
        print(message_json)
        
        result = r.publish(TTS_REQUEST_CHANNEL, message_json)
        print(f"Publish command sent. Result (number of clients that received the message): {result}")
        if result == 0:
            print(f"Warning: Message published, but no clients seem to be subscribed to '{TTS_REQUEST_CHANNEL}'.")
            print("Ensure the tts_service is running and subscribed.")
        else:
            print(f"Message successfully published to {result} client(s).")
        print(f"Check the tts_service logs for processing details and for audio output on 'audio_output_stream:{conversation_id}'.")

    except Exception as e:
        print(f"An error occurred during publishing: {e}") 