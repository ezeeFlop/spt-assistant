import React, { useEffect, useRef, useState } from 'react';
import WaveSurfer from 'wavesurfer.js';
import RecordPlugin from 'wavesurfer.js/dist/plugins/record.esm.js';

// FR-08: Web UI shows live waveform

const WaveformDisplay: React.FC = () => {
  const waveformRef = useRef<HTMLDivElement | null>(null);
  const wavesurferInstanceRef = useRef<WaveSurfer | null>(null);
  const recordPluginRef = useRef<RecordPlugin | null>(null);
  const [isVisualizing, setIsVisualizing] = useState(false);
  const [deviceError, setDeviceError] = useState<string | null>(null);

  useEffect(() => {
    if (!waveformRef.current) return;

    let ws: WaveSurfer | null = null;
    let rec: RecordPlugin | null = null;

    try {
      ws = WaveSurfer.create({
        container: waveformRef.current,
        waveColor: 'rgb(200, 0, 200)',
        progressColor: 'rgb(100, 0, 100)',
        height: 100,
        barWidth: 2,
        barGap: 1,
      });
      wavesurferInstanceRef.current = ws;

      rec = ws.registerPlugin(RecordPlugin.create({
        // scrollingWaveform: true, // Enable this for a scrolling live waveform effect
        // renderRecordedAudio: false, // Important: keep false for live visualization only
      }));
      recordPluginRef.current = rec;

      // This event is fired when stopRecording() is called or recording naturally ends.
      rec.on('record-end', () => {
        console.log('Record plugin stopped visualization.');
        setIsVisualizing(false);
        // wavesurferInstanceRef.current?.empty(); // Optionally clear waveform
      });

      // The 'record-progress' event could be used if we need to know the current recording time
      // rec.on('record-progress', (time) => { console.log('Record progress:', time); });

    } catch (error: any) {
        console.error("Error initializing WaveSurfer or Record plugin:", error);
        setDeviceError(`Initialization Error: ${error.message || 'Could not initialize audio visualizer.'}`);
    }

    return () => {
      // Ensure plugin and wavesurfer are destroyed in the correct order or safely
      if (recordPluginRef.current) {
        // Check if recording and stop before destroying if necessary
        if (recordPluginRef.current.isRecording()) {
            recordPluginRef.current.stopRecording();
        }
        // recordPluginRef.current.destroy(); // Plugin might be destroyed with wavesurfer
      }
      if (wavesurferInstanceRef.current) {
        wavesurferInstanceRef.current.destroy();
      }
      recordPluginRef.current = null;
      wavesurferInstanceRef.current = null;
    };
  }, []);

  const handleToggleVisualization = async () => {
    if (!recordPluginRef.current) {
        setDeviceError('Visualizer not ready.');
        return;
    }
    setDeviceError(null);

    try {
      if (recordPluginRef.current.isRecording()) {
        recordPluginRef.current.stopRecording();
        // setIsVisualizing(false); // State will be updated by 'record-end' event
      } else {
        // wavesurferInstanceRef.current?.empty(); // Clear previous waveform before starting new one
        await recordPluginRef.current.startRecording();
        setIsVisualizing(true);
      }
    } catch (error: any) {
      console.error('Error toggling microphone visualization:', error);
      setDeviceError(`Mic Error: ${error.message || 'Could not start microphone.'}`);
      setIsVisualizing(false); // Ensure state is correct on error
    }
  };

  // Note: The `RecordPlugin` handles its own microphone access.
  // This is separate from the `useAudioStreamer` hook which sends audio to the backend.
  // This is a simpler approach for visualization if direct stream sharing is problematic.

  return (
    <div className="waveform-container" style={{ marginBottom: 'var(--spacing-md)' }}>
      <div ref={waveformRef} style={{ minHeight: '100px', marginBottom: 'var(--spacing-sm)' }} />
      <button onClick={handleToggleVisualization} disabled={!recordPluginRef.current} style={{width: '100%'}}>
        {isVisualizing ? 'Stop Visualization' : 'Start Mic Visualization'}
      </button>
      {deviceError && <p className="text-error mt-1">{deviceError}</p>}
    </div>
  );
};

export default WaveformDisplay; 