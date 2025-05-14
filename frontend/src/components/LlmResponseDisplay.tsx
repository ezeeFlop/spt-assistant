import React from 'react';

interface LlmResponseDisplayProps {
  llmResponse?: string; // Could be tokens or full response
  toolStatus?: string;
}

const LlmResponseDisplay: React.FC<LlmResponseDisplayProps> = ({ llmResponse, toolStatus }) => {
  return (
    <div>
      <p>LLM: {llmResponse || "..."}</p>
      {toolStatus && <p>Tool Status: {toolStatus}</p>}
    </div>
  );
};

export default LlmResponseDisplay; 