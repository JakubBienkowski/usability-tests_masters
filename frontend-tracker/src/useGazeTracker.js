import { useEffect, useRef, useState } from 'react';
import webgazer from 'webgazer';

const API_URL = 'http://localhost:8000/api';
const SOURCE = 'frontend_webcam';

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
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const sessionId = sessionStorage.getItem('tracker_session_id');

    const sendEvent = async (eventType, payload) => {
      if (!sessionId) return;

      await postJson('/events', {
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
    };

    const init = async () => {
      try {
        if (window.webgazer) {
          window.webgazer.clearData();
        }

        await webgazer
          .setGazeListener((data) => {
            if (!data) return;

            const x = data.x;
            const y = data.y;
            const now = Date.now();
            const element = document.elementFromPoint(x, y);
            const meaningfulElement = element?.closest('button, input, a, h1, h2, h3, p, img, form, textarea, label');

            if (now - lastGazeEventTime.current >= 200) {
              lastGazeEventTime.current = now;
              sendEvent('gaze_point', {
                screen_x: Math.round(x),
                screen_y: Math.round(y),
                confidence: typeof data.confidence === 'number' ? data.confidence : null,
              }).catch(() => {});
            }

            if (!meaningfulElement) return;

            if (meaningfulElement !== lastLookedElement.current) {
              const duration = now - gazeTimeStart.current;
              if (lastLookedElement.current && duration > 500) {
                sendEvent('gaze_fixation', {
                  element: lastLookedElement.current.tagName.toLowerCase() +
                    (lastLookedElement.current.id ? `#${lastLookedElement.current.id}` : ''),
                  duration_ms: duration,
                }).catch(() => {});
              }
              lastLookedElement.current = meaningfulElement;
              gazeTimeStart.current = now;
            }
          })
          .begin();

        webgazer.showVideoPreview(false);
        webgazer.showPredictionPoints(true);
        webgazer.pause();
        setReady(true);
      } catch (error) {
        console.error('WebGazer init failed:', error);
      }
    };

    init();

    return () => {
      const duration = Date.now() - gazeTimeStart.current;
      if (lastLookedElement.current && duration > 500 && sessionId) {
        sendEvent('gaze_fixation', {
          element:
            lastLookedElement.current.tagName.toLowerCase() +
            (lastLookedElement.current.id ? `#${lastLookedElement.current.id}` : ''),
          duration_ms: duration,
        }).catch(() => {});
      }

      if (window.webgazer) {
        window.webgazer.pause();
      }
    };
  }, []);

  useEffect(() => {
    const sessionId = sessionStorage.getItem('tracker_session_id');

    if (isCalibrated && window.webgazer) {
      window.webgazer.resume();
      window.webgazer.showPredictionPoints(true);

      if (sessionId) {
        postJson('/events', {
          session_id: sessionId,
          source: SOURCE,
          event_type: 'calibration_completed',
          timestamp: new Date().toISOString(),
          context: {
            url: window.location.href,
            title: document.title,
          },
          payload: {},
        }).catch(() => {});
      }
    }
  }, [isCalibrated]);

  return { ready };
};
