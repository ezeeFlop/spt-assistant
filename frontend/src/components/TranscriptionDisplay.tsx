import React from 'react';

interface TranscriptionDisplayProps {
  partialTranscript?: string;
  finalTranscript?: string;
}

const TranscriptionDisplay: React.FC<TranscriptionDisplayProps> = ({ partialTranscript, finalTranscript }) => {
  return (
    <div>
      <p>Partial: {partialTranscript || "..."}</p>
      <p>Final: {finalTranscript || ""}</p>
    </div>
  );
};

export default TranscriptionDisplay; 