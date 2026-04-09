import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';

const buttonBaseStyle = {
  border: 'none',
  borderRadius: '10px',
  padding: '10px 14px',
  color: '#ffffff',
  cursor: 'pointer',
  fontWeight: 600,
};

function Popup() {
  const [state, setState] = useState({
    trackingEnabled: false,
    captureGaze: true,
    status: 'loading',
    sessionId: null,
    lastError: null,
    lastDiagnostic: null,
  });

  const refresh = () => {
    chrome.runtime.sendMessage({ type: 'GET_STATUS' }, (response) => {
      if (!response) return;
      setState({
        trackingEnabled: Boolean(response.trackingEnabled),
        captureGaze: response.captureGaze !== false,
        status: response.status || 'idle',
        sessionId: response.sessionId || null,
        lastError: response.lastError || null,
        lastDiagnostic: response.lastDiagnostic || null,
      });
    });
  };

  useEffect(() => {
    refresh();

    const handleStorageChange = (changes, areaName) => {
      if (areaName !== 'local') return;
      if (
        changes.trackingEnabled ||
        changes.captureGaze ||
        changes.status ||
        changes.sessionId ||
        changes.lastError ||
        changes.lastDiagnostic
      ) {
        refresh();
      }
    };

    chrome.storage.onChanged.addListener(handleStorageChange);
    const intervalId = window.setInterval(refresh, 1500);

    return () => {
      chrome.storage.onChanged.removeListener(handleStorageChange);
      window.clearInterval(intervalId);
    };
  }, []);

  const handleStart = () => {
    chrome.runtime.sendMessage({ type: 'START_TRACKING' }, () => refresh());
  };

  const handleStop = () => {
    chrome.runtime.sendMessage({ type: 'STOP_TRACKING' }, () => refresh());
  };

  const handleFlush = () => {
    chrome.runtime.sendMessage({ type: 'FLUSH_NOW' }, () => refresh());
  };

  const handleGazeToggle = (event) => {
    chrome.runtime.sendMessage({ type: 'SET_GAZE', enabled: event.target.checked }, () => refresh());
  };

  return (
    <div style={containerStyle}>
      <h2 style={{ marginTop: 0, marginBottom: '8px' }}>UX Capture</h2>
      <p style={mutedStyle}>Works on all websites while tracking is enabled.</p>

      <div style={statusCardStyle}>
        <div><strong>Status:</strong> {state.status}</div>
        <div><strong>Session:</strong> {state.sessionId || 'not started'}</div>
      </div>

      <label style={toggleRowStyle}>
        <input type="checkbox" checked={state.captureGaze} onChange={handleGazeToggle} />
        <span>Enable eye tracker on websites</span>
      </label>

      <div style={actionRowStyle}>
        <button onClick={handleStart} style={{ ...buttonBaseStyle, background: '#0f766e' }}>
          Start
        </button>
        <button onClick={handleStop} style={{ ...buttonBaseStyle, background: '#b91c1c' }}>
          Stop
        </button>
        <button onClick={handleFlush} style={{ ...buttonBaseStyle, background: '#1d4ed8' }}>
          Flush
        </button>
      </div>

      <div style={noteStyle}>
        Outside the browser still requires the local desktop agent. This popup controls website capture only.
      </div>

      {state.lastError && (
        <div style={errorStyle}>{state.lastError}</div>
      )}

      {state.lastDiagnostic && (
        <div style={diagnosticStyle}>
          <strong>Diagnostic:</strong> {state.lastDiagnostic.message}
        </div>
      )}
    </div>
  );
}

const containerStyle = {
  width: '320px',
  padding: '16px',
  fontFamily: 'Arial, sans-serif',
  color: '#111827',
};

const mutedStyle = {
  color: '#6b7280',
  marginTop: 0,
  marginBottom: '16px',
};

const statusCardStyle = {
  border: '1px solid #d1d5db',
  borderRadius: '12px',
  padding: '12px',
  background: '#f9fafb',
  lineHeight: 1.6,
  marginBottom: '16px',
};

const toggleRowStyle = {
  display: 'flex',
  gap: '8px',
  alignItems: 'center',
  marginBottom: '16px',
};

const actionRowStyle = {
  display: 'flex',
  gap: '8px',
  marginBottom: '16px',
};

const noteStyle = {
  color: '#374151',
  fontSize: '13px',
  lineHeight: 1.5,
};

const errorStyle = {
  marginTop: '12px',
  color: '#b91c1c',
  fontSize: '13px',
};

const diagnosticStyle = {
  marginTop: '12px',
  color: '#1f2937',
  fontSize: '13px',
  lineHeight: 1.4,
};

createRoot(document.getElementById('root')).render(<Popup />);
