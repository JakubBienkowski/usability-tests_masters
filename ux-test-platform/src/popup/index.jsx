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
    captureScreen: true,
    status: 'loading',
    sessionId: null,
    activeTask: null,
    lastError: null,
    lastDiagnostic: null,
  });
  const [taskLabel, setTaskLabel] = useState('Task');
  const [completionType, setCompletionType] = useState('manual');
  const [completionValue, setCompletionValue] = useState('');

  const refresh = () => {
    chrome.runtime.sendMessage({ type: 'GET_STATUS' }, (response) => {
      if (!response) return;
      setState({
        trackingEnabled: Boolean(response.trackingEnabled),
        captureGaze: response.captureGaze !== false,
        captureScreen: response.captureScreen !== false,
        status: response.status || 'idle',
        sessionId: response.sessionId || null,
        activeTask: response.activeTask || null,
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
        changes.captureScreen ||
        changes.status ||
        changes.sessionId ||
        changes.activeTask ||
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

  const handleScreenToggle = (event) => {
    chrome.runtime.sendMessage({ type: 'SET_SCREEN_CAPTURE', enabled: event.target.checked }, () => refresh());
  };

  const sendTaskMarker = (type, payload = {}) => {
    chrome.runtime.sendMessage({ type, ...payload }, () => refresh());
  };

  const handleNote = () => {
    const note = window.prompt('Session note');
    if (!note) return;
    sendTaskMarker('NOTE_ADDED', { note });
  };

  const handleTaskStart = () => {
    const label = taskLabel.trim() || 'Task';
    sendTaskMarker('TASK_STARTED', {
      label,
      completionRule: {
        type: completionType,
        value: completionValue,
      },
    });
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

      <label style={toggleRowStyle}>
        <input type="checkbox" checked={state.captureScreen} onChange={handleScreenToggle} />
        <span>Record real screen video during tests</span>
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

      <div style={markerCardStyle}>
        <strong>Task markers</strong>
        {state.activeTask && (
          <div style={activeTaskStyle}>
            Active: {state.activeTask.label || 'Task'}
          </div>
        )}
        <input
          type="text"
          value={taskLabel}
          onChange={(event) => setTaskLabel(event.target.value)}
          placeholder="Task label"
          style={inputStyle}
        />
        <select
          value={completionType}
          onChange={(event) => setCompletionType(event.target.value)}
          style={selectStyle}
        >
          <option value="manual">Manual completion</option>
          <option value="url_contains">Auto: URL contains</option>
          <option value="selector_exists">Auto: selector exists</option>
          <option value="text_contains">Auto: page text contains</option>
        </select>
        {completionType !== 'manual' && (
          <input
            type="text"
            value={completionValue}
            onChange={(event) => setCompletionValue(event.target.value)}
            placeholder={completionType === 'selector_exists' ? '.success, #done' : 'match value'}
            style={inputStyle}
          />
        )}
        <div style={markerRowStyle}>
          <button
            disabled={!state.trackingEnabled}
            onClick={handleTaskStart}
            style={{ ...buttonBaseStyle, background: state.trackingEnabled ? '#475569' : '#94a3b8' }}
          >
            Task start
          </button>
          <button
            disabled={!state.trackingEnabled}
            onClick={() => sendTaskMarker('TASK_COMPLETED')}
            style={{ ...buttonBaseStyle, background: state.trackingEnabled ? '#334155' : '#94a3b8' }}
          >
            Task done
          </button>
          <button
            disabled={!state.trackingEnabled}
            onClick={handleNote}
            style={{ ...buttonBaseStyle, background: state.trackingEnabled ? '#7c2d12' : '#94a3b8' }}
          >
            Note
          </button>
        </div>
      </div>

      <div style={noteStyle}>
        Gaze prefers the local desktop agent bridge when available. Screen recording uses Chrome's screen/window picker and stores WebM chunks with the session.
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

const markerCardStyle = {
  border: '1px solid #e5e7eb',
  borderRadius: '12px',
  padding: '10px',
  background: '#fff7ed',
  marginBottom: '16px',
  fontSize: '13px',
};

const activeTaskStyle = {
  marginTop: '8px',
  marginBottom: '8px',
  padding: '8px',
  borderRadius: '8px',
  background: '#ffedd5',
  color: '#7c2d12',
  fontWeight: 600,
};

const inputStyle = {
  width: '100%',
  boxSizing: 'border-box',
  marginTop: '8px',
  padding: '9px 10px',
  borderRadius: '9px',
  border: '1px solid #fed7aa',
  fontSize: '13px',
};

const selectStyle = {
  ...inputStyle,
  background: '#ffffff',
};

const markerRowStyle = {
  display: 'flex',
  gap: '8px',
  marginTop: '8px',
  flexWrap: 'wrap',
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
