import React from 'react';
import './FuturisticAnimation.css'; // Import the new CSS

interface FuturisticAnimationProps {
  audioLevel: number; // Normalized 0-1
  isLoading?: boolean; // To show loading bars and hide main text
  statusText?: string; // Text for the #status-indicator
  mainText?: string; // Text for #mainCircleText
}

const FuturisticAnimation: React.FC<FuturisticAnimationProps> = ({
  audioLevel,
  isLoading = false,
  statusText = 'SYSTEM STATUS: ONLINE',
  mainText = 'TARA',
}) => {
  // Calculate dynamic glow based on audioLevel
  // Max additional blur: 100px, Max additional spread: 20px
  const baseBlur = 35;
  const baseSpread = 0; // The original template used only blur for the main shadow

  const dynamicOuterBlur = baseBlur + audioLevel * 65; // Max 35+65 = 100
  const dynamicOuterSpread = baseSpread + audioLevel * 10; // Max 0+10 = 10
  const dynamicInnerBlur = 50 + audioLevel * 50; // Max 50+50 = 100
  const dynamicInnerSpread = audioLevel * 10; // Max 0+10 = 10

  const accentColor = 'var(--accent-color, #2187e7)'; // Use CSS variable, fallback to original blue

  const outerCircleStyle = {
    boxShadow: `0 0 ${dynamicOuterBlur}px ${dynamicOuterSpread}px ${accentColor}`,
  };

  const innerCircleStyle = {
    boxShadow: `0 0 ${dynamicInnerBlur}px ${dynamicInnerSpread}px ${accentColor}`,
    // The border color is set in CSS, if it needs to be dynamic, it can be added here too.
  };
  
  // Use the app's primary background for the component's container if needed,
  // but the template implies its own background via body styles.
  // For now, the component itself won't set a background, relying on parent or global styles.

  return (
    <div id="main-animation-container" className={isLoading ? 'loading' : ''}>
      <div id="circle-container">
        <div id="mainCircle">
          <div className="animated-circle" style={outerCircleStyle}></div>
          <div className="animated-circle-inner" style={innerCircleStyle}></div>
          
          <div id="mainCircleContent">
            {isLoading ? (
              <ul className="loading-bars-container">
                <li></li>
                <li></li>
                <li></li>
              </ul>
            ) : (
              <div id="mainCircleText">
                {mainText}
              </div>
            )}
          </div>
        </div>
      </div>

      {statusText && (
        <div id="status-indicator">
          {statusText}
        </div>
      )}
    </div>
  );
};

export default FuturisticAnimation; 