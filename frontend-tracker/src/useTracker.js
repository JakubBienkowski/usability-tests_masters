import { useEffect, useRef } from 'react';
import * as rrweb from 'rrweb';

const API_URL = 'http://localhost:8000/api';

const getSessionId = () => {
  let sid = sessionStorage.getItem('tracker_session_id');
  if (!sid) {
    sid = 'sess_' + Math.random().toString(36).substr(2, 9) + '_' + Date.now();
    sessionStorage.setItem('tracker_session_id', sid);
  }
  return sid;
};

const getCssPath = (el) => {
    if (!(el instanceof Element)) return;
    const path = [];
    while (el.nodeType === Node.ELEMENT_NODE) {
        let selector = el.nodeName.toLowerCase();
        if (el.id) {
            selector += '#' + el.id;
            path.unshift(selector);
            break;
        } else {
            let sib = el, nth = 1;
            while (sib = sib.previousElementSibling) {
                if (sib.nodeName.toLowerCase() == selector) nth++;
            }
            if (nth != 1) selector += ":nth-of-type("+nth+")";
        }
        path.unshift(selector);
        el = el.parentNode;
    }
    return path.join(" > ");
};

export const useTracker = () => {
  const sessionId = useRef(getSessionId());
  const eventsBuffer = useRef([]);

  useEffect(() => {
    if (window._tracking_initialized) return;
    window._tracking_initialized = true;

    console.log(`Tracker active. Session ID: ${sessionId.current}`);

    const sendEvent = (type, details) => {
      fetch(`${API_URL}/track`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: sessionId.current,
            timestamp: new Date().toISOString(),
            type: type,
            url: window.location.href,
            details: details || {}
          })
      }).catch(err => console.warn("Track err:", err));
    };


    const stopRecording = rrweb.record({
      emit(event) {
        eventsBuffer.current.push(event);
      },

      maskAllInputs: false,
      checkoutEveryNth: 100, 
    });

    // Pętla wysyłająca nagranie do backendu
    const saveInterval = setInterval(() => {
        if (eventsBuffer.current.length > 0) {
            const chunk = [...eventsBuffer.current];
            eventsBuffer.current = []; // Czyść bufor

            fetch(`${API_URL}/record`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: sessionId.current,
                    events: chunk
                })
            }).catch(e => console.error("Rec upload failed", e));
        }
    }, 5000); // Wysyłaj co 5 sekund(narazie pomyślimy czy zrobić na websocketach czy nie do PoC wystarczt)


    // w folderze tracking_scripts są skrypty pokazujące reszte implementacji rzeczy co można zbierać nie dawałem wszystkiego bo to troche dużo roboty
    // Click tracking
    document.addEventListener('click', (e) => {
        sendEvent('click', {
            tagName: target.tagName.toLowerCase(),
            id: e.target.id,
            className: e.target.className,
            text: e.target.innerText?.substring(0, 50),
            path: getCssPath(e.target)
        });
    }, true);

    // Navigation tracking(do podstron)
    let lastUrl = window.location.href;
    new MutationObserver(() => {
        if (window.location.href !== lastUrl) {
            lastUrl = window.location.href;
            sendEvent('navigation', { to: lastUrl });
            

            rrweb.record.takeFullSnapshot(true);
        }
    }).observe(document, { subtree: true, childList: true });

    return () => {
        // Cleanup
        clearInterval(saveInterval);
        if(stopRecording) stopRecording();
    }
  }, []);
};