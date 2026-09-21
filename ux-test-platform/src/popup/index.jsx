import React, { useEffect, useRef, useState } from 'react';
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
    pendingTaskAssessment: null,
    targetTabId: null,
    targetTabUrl: null,
    targetTabTitle: null,
    lastError: null,
    lastDiagnostic: null,
    studyId: '',
    participantId: '',
    desktopBridge: null,
  });
  const [taskLabel, setTaskLabel] = useState('Task');
  const [completionType, setCompletionType] = useState('manual');
  const [completionValue, setCompletionValue] = useState('');
  const [studyId, setStudyId] = useState('');
  const [participantId, setParticipantId] = useState('');
  const contextDraftInitialized = useRef(false);
  const [manualAssessmentOpen, setManualAssessmentOpen] = useState(false);
  const [taskOutcome, setTaskOutcome] = useState('success');
  const [seqRating, setSeqRating] = useState(5);
  const [assessmentNote, setAssessmentNote] = useState('');
  const [susOpen, setSusOpen] = useState(false);
  const [susAnswers, setSusAnswers] = useState(Array(10).fill(3));
  const [startPending, setStartPending] = useState(false);

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
        pendingTaskAssessment: response.pendingTaskAssessment || null,
        targetTabId: response.targetTabId || null,
        targetTabUrl: response.targetTabUrl || null,
        targetTabTitle: response.targetTabTitle || null,
        lastError: response.lastError || null,
        lastDiagnostic: response.lastDiagnostic || null,
        studyId: response.studyId || '',
        participantId: response.participantId || '',
        desktopBridge: response.desktopBridge || null,
      });
      if (!contextDraftInitialized.current) {
        setStudyId(response.studyId || '');
        setParticipantId(response.participantId || '');
        contextDraftInitialized.current = true;
      }
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
        changes.pendingTaskAssessment ||
        changes.targetTabId ||
        changes.targetTabUrl ||
        changes.targetTabTitle ||
        changes.lastError ||
        changes.lastDiagnostic
        || changes.studyId
        || changes.participantId
        || changes.desktopBridge
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
    if (startPending || state.trackingEnabled) return;
    setStartPending(true);
    chrome.runtime.sendMessage(
      { type: 'SET_STUDY_CONTEXT', studyId, participantId },
      () => {
        if (chrome.runtime.lastError) {
          setState((current) => ({
            ...current,
            status: 'error',
            lastError: chrome.runtime.lastError.message,
          }));
          setStartPending(false);
          return;
        }
        chrome.runtime.sendMessage({ type: 'START_TRACKING' }, (response) => {
          if (chrome.runtime.lastError || response?.ok === false) {
            setState((current) => ({
              ...current,
              status: 'error',
              lastError: chrome.runtime.lastError?.message
                || response?.error
                || 'start_tracking_failed',
            }));
            setStartPending(false);
            return;
          }
          setStartPending(false);
          refresh();
        });
      }
    );
  };

  const handleStop = () => {
    if (!state.trackingEnabled) return;
    setSusOpen(true);
  };

  const handleSusSubmit = () => {
    chrome.runtime.sendMessage(
      { type: 'SESSION_QUESTIONNAIRE_RESPONSE', susAnswers },
      () => chrome.runtime.sendMessage({ type: 'STOP_TRACKING' }, () => {
        setSusOpen(false);
        setSusAnswers(Array(10).fill(3));
        refresh();
      }),
    );
  };

  const handleFlush = () => {
    chrome.runtime.sendMessage({ type: 'FLUSH_NOW' }, () => refresh());
  };

  const handleGazeToggle = (event) => {
    chrome.runtime.sendMessage({ type: 'SET_GAZE', enabled: event.target.checked }, () => refresh());
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

  const handleAttentionProbe = (rating) => {
    sendTaskMarker('ATTENTION_PROBE_RESPONSE', { rating });
  };

  const handleAssessmentSubmit = () => {
    const isPendingAutoAssessment = Boolean(state.pendingTaskAssessment);
    sendTaskMarker(isPendingAutoAssessment ? 'TASK_ASSESSED' : 'TASK_COMPLETED', {
      outcome: taskOutcome,
      seqRating,
      assessmentNote,
    });
    setManualAssessmentOpen(false);
    setTaskOutcome('success');
    setSeqRating(5);
    setAssessmentNote('');
  };

  const assessmentTask = state.pendingTaskAssessment
    || (manualAssessmentOpen ? state.activeTask : null);

  return (
    <div style={containerStyle}>
      <h2 style={{ marginTop: 0, marginBottom: '8px' }}>UX Capture</h2>
      <p style={mutedStyle}>Works on all websites while tracking is enabled.</p>

      <div style={statusCardStyle}>
        <div><strong>Status:</strong> {state.status}</div>
        <div><strong>Session:</strong> {state.sessionId || 'not started'}</div>
        <div>
          <strong>Desktop gaze:</strong>{' '}
          {state.desktopBridge?.connected ? 'joined to this session' : 'disconnected'}
        </div>
        <div>
          <strong>Tracked tab:</strong>{' '}
          {state.targetTabTitle || (state.trackingEnabled ? 'loading…' : 'active tab selected on Start')}
        </div>
        {state.targetTabUrl && (
          <div style={urlStyle} title={state.targetTabUrl}>{state.targetTabUrl}</div>
        )}
        {state.desktopBridge?.calibration && (
          <div>
            <strong>Calibration:</strong>{' '}
            {state.desktopBridge.calibration.required
              ? 'required'
              : `ready${state.desktopBridge.calibration.rmse_normalized != null
                ? ` (RMSE ${state.desktopBridge.calibration.rmse_normalized})`
                : ''}`}
          </div>
        )}
      </div>

      <input
        type="text"
        value={studyId}
        disabled={state.trackingEnabled}
        onChange={(event) => setStudyId(event.target.value)}
        placeholder="Study ID, e.g. masters_checkout"
        style={inputStyle}
      />
      <input
        type="text"
        value={participantId}
        disabled={state.trackingEnabled}
        onChange={(event) => setParticipantId(event.target.value)}
        placeholder="Pseudonymous participant ID"
        style={{ ...inputStyle, marginBottom: '16px' }}
      />

      <label style={toggleRowStyle}>
        <input type="checkbox" checked={state.captureGaze} onChange={handleGazeToggle} />
        <span>Enable eye tracker on websites</span>
      </label>

      <label style={toggleRowStyle}>
        <input type="checkbox" checked disabled />
        <span>Screen recording required for every test</span>
      </label>

      <div style={actionRowStyle}>
        <button
          onClick={handleStart}
          disabled={startPending || state.trackingEnabled}
          style={{
            ...buttonBaseStyle,
            background: startPending || state.trackingEnabled ? '#94a3b8' : '#0f766e',
          }}
        >
          {startPending ? 'Starting…' : 'Start unified test'}
        </button>
        <button onClick={handleStop} style={{ ...buttonBaseStyle, background: '#b91c1c' }}>
          Stop test
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
            disabled={!state.trackingEnabled || Boolean(state.activeTask) || Boolean(state.pendingTaskAssessment)}
            onClick={handleTaskStart}
            style={{
              ...buttonBaseStyle,
              background: state.trackingEnabled && !state.activeTask && !state.pendingTaskAssessment
                ? '#475569'
                : '#94a3b8',
            }}
          >
            Task start
          </button>
          <button
            disabled={!state.trackingEnabled || !state.activeTask || Boolean(state.pendingTaskAssessment)}
            onClick={() => setManualAssessmentOpen(true)}
            style={{
              ...buttonBaseStyle,
              background: state.trackingEnabled && state.activeTask && !state.pendingTaskAssessment
                ? '#334155'
                : '#94a3b8',
            }}
          >
            Finish & assess
          </button>
          <button
            disabled={!state.trackingEnabled}
            onClick={handleNote}
            style={{ ...buttonBaseStyle, background: state.trackingEnabled ? '#7c2d12' : '#94a3b8' }}
          >
            Note
          </button>
        </div>
        {assessmentTask && (
          <div style={assessmentCardStyle}>
            <strong>Assess: {assessmentTask.label || 'Task'}</strong>
            <label style={assessmentLabelStyle}>
              Outcome
              <select
                value={taskOutcome}
                onChange={(event) => setTaskOutcome(event.target.value)}
                style={selectStyle}
              >
                <option value="success">Success</option>
                <option value="partial_success">Partial success</option>
                <option value="failure">Failure</option>
                <option value="abandoned">Abandoned</option>
              </select>
            </label>
            <label style={assessmentLabelStyle}>
              SEQ — how easy was the task? <strong>{seqRating}/7</strong>
              <input
                type="range"
                min="1"
                max="7"
                step="1"
                value={seqRating}
                onChange={(event) => setSeqRating(Number(event.target.value))}
                style={{ width: '100%' }}
              />
              <span style={rangeLabelsStyle}>
                <span>1 — very difficult</span>
                <span>7 — very easy</span>
              </span>
            </label>
            <textarea
              value={assessmentNote}
              onChange={(event) => setAssessmentNote(event.target.value)}
              placeholder="Optional short observation"
              maxLength={1000}
              style={{ ...inputStyle, minHeight: '56px', resize: 'vertical' }}
            />
            <button
              onClick={handleAssessmentSubmit}
              style={{ ...buttonBaseStyle, marginTop: '8px', background: '#0f766e' }}
            >
              Save task result
            </button>
          </div>
        )}
      </div>

      {susOpen && (
        <div style={assessmentCardStyle}>
          <strong>SUS — odpowiedz przed zakończeniem sesji</strong>
          <p style={smallMutedStyle}>1 — zdecydowanie nie, 5 — zdecydowanie tak</p>
          {[
            'Chciał(a)bym często korzystać z tego systemu.',
            'System był niepotrzebnie złożony.',
            'System był łatwy w użyciu.',
            'Potrzebował(a)bym pomocy technicznej, aby używać systemu.',
            'Funkcje systemu były dobrze zintegrowane.',
            'W systemie było zbyt wiele niespójności.',
            'Większość osób szybko nauczyłaby się używać systemu.',
            'System był bardzo uciążliwy w użyciu.',
            'Czułem(-am) się pewnie, używając systemu.',
            'Musiał(a)bym nauczyć się wielu rzeczy przed użyciem systemu.',
          ].map((question, index) => (
            <label key={question} style={assessmentLabelStyle}>
              {index + 1}. {question} <strong>{susAnswers[index]}/5</strong>
              <input
                type="range"
                min="1"
                max="5"
                value={susAnswers[index]}
                onChange={(event) => {
                  const next = [...susAnswers];
                  next[index] = Number(event.target.value);
                  setSusAnswers(next);
                }}
              />
            </label>
          ))}
          <button
            onClick={handleSusSubmit}
            style={{ ...buttonBaseStyle, background: '#b91c1c' }}
          >
            Zapisz SUS i zakończ test
          </button>
        </div>
      )}

      {state.trackingEnabled && (
        <div style={statusCardStyle}>
          <strong>Focused right now?</strong>
          <div style={{ ...actionRowStyle, marginTop: '8px' }}>
            {[1, 2, 3, 4, 5].map((rating) => (
              <button
                key={rating}
                onClick={() => handleAttentionProbe(rating)}
                style={{ ...buttonBaseStyle, background: rating <= 2 ? '#b91c1c' : rating >= 4 ? '#0f766e' : '#64748b' }}
              >
                {rating}
              </button>
            ))}
          </div>
        </div>
      )}

      <div style={noteStyle}>
        Only the active HTTP/HTTPS tab is instrumented when Start is pressed. Desktop gaze,
        browser events and screen recording share one session ID.
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

const smallMutedStyle = {
  color: '#6b7280',
  fontSize: '12px',
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

const assessmentCardStyle = {
  marginTop: '10px',
  padding: '10px',
  border: '1px solid #fdba74',
  borderRadius: '10px',
  background: '#ffffff',
};

const assessmentLabelStyle = {
  display: 'block',
  marginTop: '10px',
  lineHeight: 1.4,
};

const rangeLabelsStyle = {
  display: 'flex',
  justifyContent: 'space-between',
  gap: '8px',
  color: '#6b7280',
  fontSize: '11px',
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

const urlStyle = {
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
  color: '#475569',
  fontSize: '11px',
};

createRoot(document.getElementById('root')).render(<Popup />);
