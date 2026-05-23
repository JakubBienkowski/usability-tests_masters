import { useEffect, useRef, useState } from 'react';
import webgazer from 'webgazer';
import {
  GAZE_FIXATION_MIN_DURATION_MS,
  GAZE_LOST_TIMEOUT_MS,
  buildGazeFixationPayload,
  buildGazeLostPayload,
  buildGazePointPayload,
  buildGazeStatusPayload,
} from './gazeRuntime';

const API_URL = 'http://localhost:8000/api';
const SOURCE = 'frontend_webcam';
const GAZE_BATCH_SIZE = 25;
const GAZE_FLUSH_INTERVAL_MS = 1000;
const LOCAL_GAZE_BRIDGE_HTTP = 'http://127.0.0.1:8790';
const LOCAL_GAZE_BRIDGE_WS = 'ws://127.0.0.1:8790/ws/gaze';

const postJson = async (path, payload) => {
  const response = await fetch(`${API_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
    keepalive: true,
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
};

export const useGazeTracker = (isCalibrated) => {
  const lastLookedElement = useRef(null);
  const gazeTimeStart = useRef(Date.now());
  const lastGazeEventTime = useRef(0);
  const lastGazeDataAt = useRef(0);
  const gazeLostReported = useRef(false);
  const eventBuffer = useRef([]);
  const flushTimerRef = useRef(null);
  const flushPromiseRef = useRef(null);
  const bridgeSocketRef = useRef(null);
  const sourceModeRef = useRef('unknown');
  const [ready, setReady] = useState(false);
  const [providerMode, setProviderMode] = useState('unknown');
  const [requiresCalibration, setRequiresCalibration] = useState(false);
  const [calibrationTargets, setCalibrationTargets] = useState([]);

  useEffect(() => {
    const sessionId = sessionStorage.getItem('tracker_session_id');

    const flushEvents = async () => {
      if (flushPromiseRef.current) {
        await flushPromiseRef.current;
        return;
      }
      if (!sessionId || !eventBuffer.current.length) return;

      flushPromiseRef.current = (async () => {
        const chunk = [...eventBuffer.current];
        eventBuffer.current = [];

        try {
          await postJson('/events', {
            events: chunk,
          });
        } catch (error) {
          eventBuffer.current = [...chunk, ...eventBuffer.current];
          throw error;
        } finally {
          flushPromiseRef.current = null;
        }
      })();
      await flushPromiseRef.current;
    };

    const flushEventsSafe = () => {
      flushEvents().catch(() => {});
    };

    const sendEvent = (eventType, payload) => {
      if (!sessionId) return;

      eventBuffer.current.push({
        session_id: sessionId,
        source: SOURCE,
        event_type: eventType,
        timestamp: new Date().toISOString(),
        context: {
          url: window.location.href,
          title: document.title,
          viewport: {
            width: window.innerWidth,
            height: window.innerHeight,
          },
        },
        payload,
      });
      if (eventBuffer.current.length >= GAZE_BATCH_SIZE) {
        flushEventsSafe();
      }
    };

    const reportGazeLost = (reason, extra = {}) => {
      if (gazeLostReported.current) return;
      gazeLostReported.current = true;
      sendEvent('gaze_lost', buildGazeLostPayload(reason, extra));
    };

    const checkForStaleGaze = () => {
      if (!lastGazeDataAt.current) return;
      if (Date.now() - lastGazeDataAt.current < GAZE_LOST_TIMEOUT_MS) return;
      reportGazeLost('stale_gaze_stream');
    };

    const syncCalibrationStatus = async () => {
      try {
        const response = await fetch(`${LOCAL_GAZE_BRIDGE_HTTP}/calibration/status`);
        if (!response.ok) return;
        const status = await response.json();
        setRequiresCalibration(Boolean(status.required));
        setCalibrationTargets(status.targets || []);
      } catch {}
    };

    const recordFixationTransition = (x, y, now, extra = {}) => {
      lastGazeDataAt.current = now;
      gazeLostReported.current = false;

      const element = document.elementFromPoint(x, y);
      const meaningfulElement = element?.closest(
        'button, input, a, h1, h2, h3, p, img, form, textarea, label',
      );

      if (!meaningfulElement) return;

      if (meaningfulElement !== lastLookedElement.current) {
        const duration = now - gazeTimeStart.current;
        if (lastLookedElement.current && duration >= GAZE_FIXATION_MIN_DURATION_MS) {
          sendEvent(
            'gaze_fixation',
            buildGazeFixationPayload(lastLookedElement.current, duration, extra),
          );
        }
        lastLookedElement.current = meaningfulElement;
        gazeTimeStart.current = now;
      }
    };

    const handleGazePoint = (x, y, confidence, extra = {}) => {
      const now = Date.now();
      recordFixationTransition(x, y, now, extra);

      if (now - lastGazeEventTime.current < 200) return;
      lastGazeEventTime.current = now;
      sendEvent('gaze_point', buildGazePointPayload(x, y, confidence, extra));
    };

    const projectBridgePoint = (payload = {}) => {
      if (typeof payload.normalized_x === 'number' && typeof payload.normalized_y === 'number') {
        return {
          x: Math.max(0, Math.min(window.innerWidth - 1, payload.normalized_x * window.innerWidth)),
          y: Math.max(0, Math.min(window.innerHeight - 1, payload.normalized_y * window.innerHeight)),
        };
      }
      if (typeof payload.screen_x === 'number' && typeof payload.screen_y === 'number') {
        return {
          x: Math.max(0, Math.min(window.innerWidth - 1, payload.screen_x)),
          y: Math.max(0, Math.min(window.innerHeight - 1, payload.screen_y)),
        };
      }
      return null;
    };

    const startWebgazerTracking = async () => {
      try {
        sourceModeRef.current = 'webgazer';
        setProviderMode('webgazer');
        setRequiresCalibration(true);
        sendEvent('gaze_provider_status', buildGazeStatusPayload('starting'));
        if (window.webgazer) {
          window.webgazer.clearData();
        }

        await webgazer
          .setGazeListener((data) => {
            if (!data) {
              if (
                lastGazeDataAt.current &&
                Date.now() - lastGazeDataAt.current >= GAZE_LOST_TIMEOUT_MS
              ) {
                reportGazeLost('provider_returned_null');
              }
              return;
            }

            handleGazePoint(data.x, data.y, data.confidence);
          })
          .begin();

        webgazer.showVideoPreview(false);
        webgazer.showPredictionPoints(true);
        webgazer.pause();
        sendEvent('gaze_provider_status', buildGazeStatusPayload('ready'));
        setReady(true);
      } catch (error) {
        console.error('WebGazer init failed:', error);
        sendEvent(
          'gaze_provider_status',
          buildGazeStatusPayload('unavailable', {
            message: error?.message || String(error),
          }),
        );
        reportGazeLost('provider_init_failed', {
          message: error?.message || String(error),
        });
      }
    };

    const startLocalBridgeTracking = async () => {
      try {
        const healthResponse = await fetch(`${LOCAL_GAZE_BRIDGE_HTTP}/health`);
        if (!healthResponse.ok) {
          throw new Error(`Bridge health failed: ${healthResponse.status}`);
        }
        const socket = new WebSocket(LOCAL_GAZE_BRIDGE_WS);
        bridgeSocketRef.current = socket;

        await new Promise((resolve, reject) => {
          const onOpen = () => {
            sourceModeRef.current = 'local_bridge';
            setProviderMode('local_bridge');
            sendEvent(
              'gaze_provider_status',
              buildGazeStatusPayload('connected', {
                provider: 'desktop_agent_bridge',
                provider_type: 'local_bridge',
                bridge_url: LOCAL_GAZE_BRIDGE_WS,
              }),
            );
            syncCalibrationStatus().catch(() => {});
            setReady(true);
            resolve();
          };
          const onError = () => {
            reject(new Error('Bridge websocket failed'));
          };
          socket.addEventListener('open', onOpen, { once: true });
          socket.addEventListener('error', onError, { once: true });
        });

        socket.addEventListener('message', (message) => {
          const snapshot = JSON.parse(message.data);
          const event = snapshot?.last_event;
          if (!event) return;

          if (event.event_type === 'gaze_provider_status') {
            if (typeof event.payload?.calibration_required === 'boolean') {
              setRequiresCalibration(event.payload.calibration_required);
            }
            sendEvent('gaze_provider_status', {
              ...event.payload,
              bridge_mode: 'local_agent',
            });
            return;
          }

          if (event.event_type === 'gaze_lost') {
            reportGazeLost(event.payload?.reason || 'local_bridge_lost', {
              ...event.payload,
              provider: 'desktop_agent_bridge',
              provider_type: 'local_bridge',
              bridge_mode: 'local_agent',
            });
            return;
          }

          if (event.event_type !== 'gaze_point') return;

          const projectedPoint = projectBridgePoint(event.payload);
          if (!projectedPoint) return;

          handleGazePoint(projectedPoint.x, projectedPoint.y, event.payload?.confidence, {
            provider: 'desktop_agent_bridge',
            provider_type: 'local_bridge',
            bridge_mode: 'local_agent',
            upstream_source: 'desktop_agent_local_bridge',
            upstream_provider: event.payload?.provider || 'unknown',
          });
        });

        socket.addEventListener('close', () => {
          if (sourceModeRef.current === 'local_bridge') {
            reportGazeLost('local_bridge_closed', {
              bridge_mode: 'local_agent',
            });
          }
        });
      } catch (error) {
        await startWebgazerTracking();
      }
    };

    startLocalBridgeTracking();
    flushTimerRef.current = window.setInterval(() => {
      checkForStaleGaze();
      flushEventsSafe();
    }, GAZE_FLUSH_INTERVAL_MS);

    return () => {
      const duration = Date.now() - gazeTimeStart.current;
      if (lastLookedElement.current && duration >= GAZE_FIXATION_MIN_DURATION_MS && sessionId) {
        sendEvent(
          'gaze_fixation',
          buildGazeFixationPayload(lastLookedElement.current, duration, {
            bridge_mode: sourceModeRef.current === 'local_bridge' ? 'local_agent' : undefined,
          }),
        );
      }
      sendEvent('gaze_provider_status', buildGazeStatusPayload('stopped'));
      if (flushTimerRef.current) {
        window.clearInterval(flushTimerRef.current);
      }
      flushEventsSafe();

      if (bridgeSocketRef.current) {
        bridgeSocketRef.current.close();
        bridgeSocketRef.current = null;
      }

      if (window.webgazer) {
        window.webgazer.pause();
      }
    };
  }, []);

  useEffect(() => {
    const sessionId = sessionStorage.getItem('tracker_session_id');

    if (sourceModeRef.current === 'local_bridge') {
      return;
    }

    if (isCalibrated && window.webgazer) {
      window.webgazer.resume();
      window.webgazer.showPredictionPoints(true);

      if (sessionId) {
        postJson('/events', {
          events: [
            {
              session_id: sessionId,
              source: SOURCE,
              event_type: 'calibration_completed',
              timestamp: new Date().toISOString(),
              context: {
                url: window.location.href,
                title: document.title,
              },
              payload: buildGazeStatusPayload('calibrated'),
            },
          ],
        }).catch(() => {});
      }
    }
  }, [isCalibrated]);

  return {
    ready,
    providerMode,
    requiresCalibration,
    calibrationTargets,
    startLocalCalibration: async () => {
      const response = await fetch(`${LOCAL_GAZE_BRIDGE_HTTP}/calibration/start`, {
        method: 'POST',
      });
      if (!response.ok) {
        throw new Error(`Calibration start failed: ${response.status}`);
      }
      const status = await response.json();
      setRequiresCalibration(Boolean(status.required || status.active));
      setCalibrationTargets(status.targets || []);
      return status;
    },
    submitLocalCalibrationSample: async (sample) => {
      const response = await fetch(`${LOCAL_GAZE_BRIDGE_HTTP}/calibration/sample`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(sample),
      });
      if (!response.ok) {
        const errorBody = await response.json().catch(() => ({}));
        throw new Error(errorBody.detail || `Calibration sample failed: ${response.status}`);
      }
      const status = await response.json();
      setRequiresCalibration(Boolean(status.required || status.active));
      setCalibrationTargets(status.targets || []);
      return status;
    },
  };
};
