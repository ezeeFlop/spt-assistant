import React, { useEffect, useRef } from 'react';
import './ChatDisplay.css';

export interface ChatMessage {
  id: string; // For React keys, can be timestamp + random number
  type: 'user' | 'assistant' | 'tool_status' | 'partial_transcript';
  content: string;
  timestamp?: number; // Optional, Unix timestamp
}

interface ChatDisplayProps {
  messages: ChatMessage[];
  partialTranscript?: string; // Separate prop for live partial transcript
}

const ChatDisplay: React.FC<ChatDisplayProps> = ({ messages, partialTranscript }) => {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, partialTranscript]);

  return (
    <div className="chat-display-container" ref={scrollRef}>
      {messages.map((msg) => (
        <div key={msg.id} className={`chat-message-wrapper ${msg.type}-wrapper`}>
          <div className={`chat-message ${msg.type}`}>
            <p>{msg.content}</p>
            {/* Optionally display timestamp here */}
          </div>
        </div>
      ))}
      {partialTranscript && (
        <div className="chat-message-wrapper partial_transcript-wrapper">
          <div className="chat-message partial_transcript">
            <p>{partialTranscript}</p>
          </div>
        </div>
      )}
    </div>
  );
};

export default ChatDisplay; 