import { useEffect, useMemo, useRef, useState } from 'react';
import { Replayer } from 'rrweb';
import 'rrweb/dist/rrweb.css';

const API_URL = 'http://localhost:8000/api';

const formatTime = (value) => {
  if (!value) return 'n/a';
  return new Date(value).toLocaleString();
};

const getViewportFromEvent = (event, fallbackViewport) => {
  return (
    event?.context?.viewport ||
    fallbackViewport || {
      width: 1,
      height: 1,
    }
  );
};

function SessionReplay() {
  const params = new URLSearchParams(window.location.search);
  const initialSessionId = params.get('replay') || '';

  const [sessionId, setSessionId] = useState(initialSessionId);
  const [inputValue, setInputValue] = useState(initialSessionId);
  const [availableSessions, setAvailableSessions] = useState([]);
  const [replayData, setReplayData] = useState(null);
  const [timelineData, setTimelineData] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [overlayStyle, setOverlayStyle] = useState(null);
  const [error, setError] = useState('');
  const [status, setStatus] = useState(initialSessionId ? 'loading' : 'idle');
  const [currentReplayTime, setCurrentReplayTime] = useState(0);

  const playerHostRef = useRef(null);
  const playerStageRef = useRef(null);
  const videoRef = useRef(null);
  const replayerRef = useRef(null);
  const rafRef = useRef(0);

  useEffect(() => {
    fetch(`${API_URL}/sessions`)
      .then((response) => response.json())
      .then((data) => setAvailableSessions(data.sessions || []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!sessionId) return undefined;

    // Fetch lifecycle is intentionally mirrored in UI state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStatus('loading');
    setError('');

    fetch(`${API_URL}/sessions/${sessionId}/replay`)
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Replay request failed: ${response.status}`);
        }
        return response.json();
      })
      .then((data) => {
        setReplayData(data);
        setStatus('ready');
      })
      .catch((fetchError) => {
        setReplayData(null);
        setStatus('error');
        setError(fetchError.message);
      });

    return undefined;
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    Promise.all([
      fetch(`${API_URL}/sessions/${sessionId}/timeline`).then((response) => response.json()),
      fetch(`${API_URL}/sessions/${sessionId}/metrics`).then((response) => response.json()),
    ])
      .then(([timeline, sessionMetrics]) => {
        setTimelineData(timeline);
        setMetrics(sessionMetrics);
      })
      .catch(() => {
        setTimelineData(null);
        setMetrics(null);
      });
  }, [sessionId]);

  useEffect(() => {
    if (!replayData?.rrweb_events?.length || !playerHostRef.current) return undefined;

    if (replayerRef.current) {
      replayerRef.current.destroy();
      replayerRef.current = null;
    }

    playerHostRef.current.innerHTML = '';
    const replayer = new Replayer(replayData.rrweb_events, {
      root: playerHostRef.current,
      mouseTail: false,
    });
    replayer.play();
    replayerRef.current = replayer;

    const tick = () => {
      if (replayerRef.current) {
        setCurrentReplayTime(replayerRef.current.getCurrentTime());
        rafRef.current = window.requestAnimationFrame(tick);
      }
    };
    rafRef.current = window.requestAnimationFrame(tick);

    return () => {
      window.cancelAnimationFrame(rafRef.current);
      if (replayerRef.current) {
        replayerRef.current.destroy();
        replayerRef.current = null;
      }
    };
  }, [replayData]);

  const replayBaseTimestamp = useMemo(() => {
    const firstRrweb = replayData?.rrweb_events?.[0]?.timestamp;
    if (typeof firstRrweb === 'number') return firstRrweb;

    const firstEvent = replayData?.events?.[0]?.timestamp;
    return firstEvent ? new Date(firstEvent).getTime() : 0;
  }, [replayData]);

  const fallbackViewport = useMemo(() => {
    return replayData?.session?.metadata?.viewport || { width: 1, height: 1 };
  }, [replayData]);

  const currentGaze = useMemo(() => {
    if (!replayData?.events?.length || !replayBaseTimestamp) return null;

    const cutoff = replayBaseTimestamp + currentReplayTime;
    let latestPoint = null;
    let latestFixation = null;

    for (const event of replayData.events) {
      const eventTime = event.timestamp ? new Date(event.timestamp).getTime() : 0;
      if (!eventTime || eventTime > cutoff) break;

      if (event.event_type === 'gaze_point') {
        latestPoint = event;
      }
      if (event.event_type === 'gaze_fixation') {
        latestFixation = event;
      }
    }

    return { latestPoint, latestFixation };
  }, [currentReplayTime, replayBaseTimestamp, replayData]);

  useEffect(() => {
    const iframe = playerHostRef.current?.querySelector('iframe');
    const stage = playerStageRef.current;
    const latestPoint = currentGaze?.latestPoint;
    if (!iframe || !stage || !latestPoint) {
      // DOM geometry is external state and must be reflected after replay renders.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setOverlayStyle(null);
      return;
    }

    const iframeRect = iframe.getBoundingClientRect();
    const stageRect = stage.getBoundingClientRect();
    const viewport = getViewportFromEvent(latestPoint, fallbackViewport);
    const width = viewport.width || 1;
    const height = viewport.height || 1;
    const x = latestPoint.payload?.screen_x ?? latestPoint.payload?.x;
    const y = latestPoint.payload?.screen_y ?? latestPoint.payload?.y;

    if (typeof x !== 'number' || typeof y !== 'number') {
      setOverlayStyle(null);
      return;
    }

    setOverlayStyle({
      left: `${iframeRect.left - stageRect.left + (x / width) * iframeRect.width}px`,
      top: `${iframeRect.top - stageRect.top + (y / height) * iframeRect.height}px`,
    });
  }, [currentGaze, fallbackViewport]);

  const fixationLabel = currentGaze?.latestFixation?.payload?.element || null;
  const fixationDuration = currentGaze?.latestFixation?.payload?.duration_ms || null;

  const handleLoad = (nextSessionId) => {
    if (!nextSessionId) return;
    const url = new URL(window.location.href);
    url.searchParams.set('replay', nextSessionId);
    window.history.replaceState({}, '', url);
    setSessionId(nextSessionId);
    setInputValue(nextSessionId);
  };

  const markers = useMemo(
    () =>
      (timelineData?.timeline || []).filter(
        (item) => item.kind === 'friction' || item.kind === 'marker',
      ),
    [timelineData],
  );

  const seekToMarker = (offsetMs) => {
    const offset = Math.max(Number(offsetMs) || 0, 0);
    if (replayerRef.current) {
      replayerRef.current.pause();
      replayerRef.current.play(offset);
    }
    if (videoRef.current) {
      videoRef.current.currentTime = offset / 1000;
      videoRef.current.play().catch(() => {});
    }
    setCurrentReplayTime(offset);
  };

  return (
    <div style={pageStyle}>
      <div style={sidebarStyle}>
        <h1 style={{ marginTop: 0 }}>Session Replay</h1>
        <p style={mutedStyle}>
          Load a recorded session and view the eye-tracker overlay on top of the replay.
        </p>

        <div style={fieldBlockStyle}>
          <label htmlFor="session-id">Session ID</label>
          <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
            <input
              id="session-id"
              value={inputValue}
              onChange={(event) => setInputValue(event.target.value)}
              placeholder="sess_..."
              style={inputStyle}
            />
            <button onClick={() => handleLoad(inputValue.trim())} style={buttonStyle}>
              Load
            </button>
          </div>
        </div>

        <div style={fieldBlockStyle}>
          <div style={{ marginBottom: '8px', fontWeight: 600 }}>Recent sessions</div>
          <div style={sessionListStyle}>
            {availableSessions.map((item) => (
              <div key={item.session_id} style={sessionCardStyle}>
                <button
                  onClick={() => handleLoad(item.session_id)}
                  style={{
                    ...sessionButtonStyle,
                    border: 0,
                    borderBottom: item.report_available ? '1px solid #e5e7eb' : 0,
                  }}
                >
                  <div style={{ fontWeight: 600 }}>{item.session_id}</div>
                  <div style={smallMutedStyle}>
                    {formatTime(item.started_at)} · {item.lifecycle?.mode || 'unknown mode'}
                  </div>
                  <div style={item.lifecycle?.completed ? completedStyle : recordingStyle}>
                    {item.lifecycle?.completed ? 'Completed' : 'Recording / incomplete'}
                  </div>
                </button>
                {item.report_available && (
                  <a
                    href={`${API_URL}/sessions/${item.session_id}/report`}
                    target="_blank"
                    rel="noreferrer"
                    style={reportLinkStyle}
                  >
                    Open final report
                  </a>
                )}
              </div>
            ))}
          </div>
        </div>

        {replayData?.session && (
          <div style={detailsStyle}>
            <div><strong>Started:</strong> {formatTime(replayData.session.started_at)}</div>
            <div><strong>Source:</strong> {replayData.session.source}</div>
            <div><strong>URL:</strong> {replayData.session.metadata?.initial_url || 'n/a'}</div>
            <div>
              <strong>Status:</strong>{' '}
              {availableSessions.find((item) => item.session_id === sessionId)?.lifecycle?.status ||
                'unknown'}
            </div>
          </div>
        )}

        {fixationLabel && (
          <div style={detailsStyle}>
            <div><strong>Current fixation:</strong> {fixationLabel}</div>
            <div><strong>Duration:</strong> {fixationDuration || 0} ms</div>
          </div>
        )}

        {metrics?.gaze_quality && (
          <div style={detailsStyle}>
            <div><strong>Gaze quality:</strong> {metrics.gaze_quality.status}</div>
            <div><strong>Score:</strong> {metrics.gaze_quality.score}</div>
            <div><strong>Sample rate:</strong> {metrics.gaze_samples_per_second}/s</div>
          </div>
        )}

        {sessionId && (
          <div style={fieldBlockStyle}>
            <a href={`${API_URL}/sessions/${sessionId}/report`} target="_blank" rel="noreferrer">
              {availableSessions.find((item) => item.session_id === sessionId)?.report_available
                ? 'Final session report'
                : 'Draft session report'}
            </a>
            {' · '}
            <a href={`${API_URL}/sessions/${sessionId}/mfem.csv`}>MFEM CSV</a>
            {' · '}
            <a href={`${API_URL}/sessions/${sessionId}/report.json`}>Report JSON</a>
          </div>
        )}

        <div style={fieldBlockStyle}>
          <div style={{ marginBottom: '8px', fontWeight: 600 }}>Timeline markers</div>
          <div style={sessionListStyle}>
            {markers.map((marker, index) => (
              <button
                key={`${marker.timestamp}-${marker.event_type}-${index}`}
                onClick={() => seekToMarker(marker.offset_ms)}
                style={sessionButtonStyle}
              >
                <div style={{ fontWeight: 600 }}>
                  {marker.payload?.marker_type || marker.event_type}
                </div>
                <div style={smallMutedStyle}>
                  {((marker.offset_ms || 0) / 1000).toFixed(1)}s · {marker.payload?.severity || marker.kind}
                </div>
              </button>
            ))}
          </div>
        </div>

        {error && <div style={{ color: '#b91c1c' }}>{error}</div>}
      </div>

      <div style={contentStyle}>
        {sessionId && (
          <video
            ref={videoRef}
            controls
            src={`${API_URL}/sessions/${sessionId}/screen-recording`}
            style={{ width: '100%', maxHeight: '45vh', marginBottom: '16px', background: '#111827' }}
          />
        )}
        <div style={playerShellStyle}>
          {status === 'idle' && <div style={emptyStyle}>Pick a session to load replay.</div>}
          {status === 'loading' && <div style={emptyStyle}>Loading replay...</div>}
          {status === 'error' && <div style={emptyStyle}>Replay could not be loaded.</div>}
          {status === 'ready' && !replayData?.rrweb_events?.length && (
            <div style={emptyStyle}>This session has no rrweb recording yet.</div>
          )}

          <div ref={playerStageRef} style={playerStageStyle}>
            <div ref={playerHostRef} style={playerHostStyle} />
            {status === 'ready' && overlayStyle && (
              <>
                <div style={{ ...gazeRingStyle, ...overlayStyle }} />
                <div style={{ ...gazeDotStyle, ...overlayStyle }} />
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

const pageStyle = {
  display: 'grid',
  gridTemplateColumns: '320px 1fr',
  minHeight: '100vh',
  background: '#f3f4f6',
  color: '#111827',
  fontFamily: 'Arial, sans-serif',
};

const sidebarStyle = {
  padding: '24px',
  borderRight: '1px solid #e5e7eb',
  background: '#ffffff',
};

const contentStyle = {
  padding: '24px',
};

const playerShellStyle = {
  minHeight: 'calc(100vh - 48px)',
  borderRadius: '16px',
  border: '1px solid #d1d5db',
  background: '#ffffff',
  overflow: 'hidden',
};

const playerStageStyle = {
  position: 'relative',
  minHeight: '800px',
  background: '#111827',
};

const playerHostStyle = {
  minHeight: '800px',
};

const gazeDotStyle = {
  position: 'absolute',
  width: '16px',
  height: '16px',
  marginLeft: '-8px',
  marginTop: '-8px',
  borderRadius: '999px',
  background: '#ef4444',
  pointerEvents: 'none',
  boxShadow: '0 0 0 4px rgba(239, 68, 68, 0.24)',
};

const gazeRingStyle = {
  position: 'absolute',
  width: '44px',
  height: '44px',
  marginLeft: '-22px',
  marginTop: '-22px',
  borderRadius: '999px',
  border: '2px solid rgba(248, 113, 113, 0.8)',
  background: 'rgba(248, 113, 113, 0.12)',
  pointerEvents: 'none',
};

const fieldBlockStyle = {
  marginBottom: '24px',
};

const detailsStyle = {
  marginBottom: '24px',
  padding: '16px',
  borderRadius: '12px',
  background: '#f9fafb',
  border: '1px solid #e5e7eb',
  lineHeight: 1.6,
};

const buttonStyle = {
  border: 'none',
  background: '#111827',
  color: '#ffffff',
  padding: '10px 14px',
  borderRadius: '10px',
  cursor: 'pointer',
};

const inputStyle = {
  flex: 1,
  padding: '10px 12px',
  borderRadius: '10px',
  border: '1px solid #d1d5db',
};

const sessionListStyle = {
  display: 'flex',
  flexDirection: 'column',
  gap: '8px',
  maxHeight: '280px',
  overflow: 'auto',
};

const sessionButtonStyle = {
  width: '100%',
  textAlign: 'left',
  background: '#ffffff',
  border: '1px solid #d1d5db',
  borderRadius: '10px',
  padding: '10px 12px',
  cursor: 'pointer',
};

const sessionCardStyle = {
  overflow: 'hidden',
  border: '1px solid #d1d5db',
  borderRadius: '10px',
  background: '#ffffff',
};

const reportLinkStyle = {
  display: 'block',
  padding: '8px 12px',
  color: '#1d4ed8',
  fontSize: '13px',
  fontWeight: 600,
  textDecoration: 'none',
};

const completedStyle = {
  marginTop: '5px',
  color: '#047857',
  fontSize: '12px',
  fontWeight: 600,
};

const recordingStyle = {
  marginTop: '5px',
  color: '#b45309',
  fontSize: '12px',
  fontWeight: 600,
};

const mutedStyle = {
  color: '#6b7280',
  lineHeight: 1.5,
};

const smallMutedStyle = {
  color: '#6b7280',
  fontSize: '12px',
};

const emptyStyle = {
  position: 'absolute',
  inset: 0,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  color: '#d1d5db',
  zIndex: 1,
};

export default SessionReplay;
