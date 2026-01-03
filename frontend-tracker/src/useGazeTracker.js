import { useEffect, useRef, useState } from 'react';
import webgazer from 'webgazer'; 

const API_URL = 'http://localhost:8000/api/track';

export const useGazeTracker = (isCalibrated) => {
  const lastLookedElement = useRef(null);
  const gazeTimeStart = useRef(Date.now());
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const init = async () => {
        try {
            // Czyścimy stare instancje
            if (window.webgazer) {
                window.webgazer.clearData();
            }

            // Ustawiamy listenera
            await webgazer.setGazeListener((data, clock) => {
                if (data == null) return;
                
                // --- Logika śledzenia elementów ---
                const x = data.x;
                const y = data.y;
                const element = document.elementFromPoint(x, y);

                if (element) {
                    const meaningfulElement = element.closest('button, input, a, h1, h2, p, img, form');
                    if (meaningfulElement && meaningfulElement !== lastLookedElement.current) {
                        const duration = Date.now() - gazeTimeStart.current;
                        if (lastLookedElement.current && duration > 500) {
                            sendGazeData(lastLookedElement.current, duration);
                        }
                        lastLookedElement.current = meaningfulElement;
                        gazeTimeStart.current = Date.now();
                    }
                }
            }).begin();

            // Ukrywamy wideo, pokazujemy kropkę
            webgazer.showVideoPreview(false);
            webgazer.showPredictionPoints(true); 
            
            console.log("WebGazer started");
            setReady(true);
        } catch (e) {
            console.error("WebGazer init failed:", e);
        }
    };

    init();


    return () => {
        if (window.webgazer) {
            // webgazer.end(); /
            webgazer.pause();
        }
    }
  }, []); 

  // Jeśli kalibracja zakończona, check czy kropka jest widoczna
  useEffect(() => {
    if (isCalibrated && window.webgazer) {
        webgazer.resume();
        webgazer.showPredictionPoints(true); // Wymuś pokazanie kropki
    }
  }, [isCalibrated]);

  const sendGazeData = (element, duration) => {
    fetch(API_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            session_id: sessionStorage.getItem('tracker_session_id'),
            type: 'gaze_fixation',
            timestamp: new Date().toISOString(),
            url: window.location.href,
            details: {
                element: element.tagName.toLowerCase() + (element.id ? `#${element.id}` : ''),
                duration_ms: duration
            }
        })
    }).catch(e => {});
  };

  return { ready };
};