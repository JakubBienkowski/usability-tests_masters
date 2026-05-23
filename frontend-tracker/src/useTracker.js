import { useEffect, useRef } from 'react';
import * as rrweb from 'rrweb';

const API_URL = 'http://localhost:8000/api';
const SOURCE = 'frontend_tracker';
const EVENT_BATCH_SIZE = 20;
const EVENT_FLUSH_INTERVAL_MS = 2000;

const getSessionId = () => {
  let sid = sessionStorage.getItem('tracker_session_id');
  if (!sid) {
    sid = `sess_${Math.random().toString(36).slice(2, 11)}_${Date.now()}`;
    sessionStorage.setItem('tracker_session_id', sid);
  }
  return sid;
};

const getCssPath = (node) => {
  if (!(node instanceof Element)) return null;

  const path = [];
  let current = node;

  while (current && current.nodeType === Node.ELEMENT_NODE) {
    let selector = current.nodeName.toLowerCase();

    if (current.id) {
      selector += `#${current.id}`;
      path.unshift(selector);
      break;
    }

    let sibling = current;
    let nth = 1;
    while ((sibling = sibling.previousElementSibling)) {
      if (sibling.nodeName.toLowerCase() === selector) nth += 1;
    }
    if (nth !== 1) selector += `:nth-of-type(${nth})`;
    path.unshift(selector);
    current = current.parentElement;
  }

  return path.join(' > ');
};

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

  return response.json().catch(() => null);
};

export const useTracker = () => {
  const sessionId = useRef(getSessionId());
  const eventBuffer = useRef([]);
  const eventsBuffer = useRef([]);
  const flushTimerRef = useRef(null);
  const eventFlushTimerRef = useRef(null);
  const sessionCreatedRef = useRef(false);
  const sessionCreatePromiseRef = useRef(null);
  const eventFlushPromiseRef = useRef(null);
  const rrwebFlushPromiseRef = useRef(null);
  const sequenceRef = useRef(1);

  useEffect(() => {
    if (window._tracking_initialized) return undefined;
    window._tracking_initialized = true;

    const currentSessionId = sessionId.current;
    let lastUrl = window.location.href;

    const createSession = async () => {
      if (sessionCreatedRef.current) return;
      if (sessionCreatePromiseRef.current) {
        await sessionCreatePromiseRef.current;
        return;
      }

      sessionCreatePromiseRef.current = (async () => {
        try {
          await postJson('/sessions', {
            session_id: currentSessionId,
            source: SOURCE,
            metadata: {
              initial_url: window.location.href,
              user_agent: navigator.userAgent,
              viewport: {
                width: window.innerWidth,
                height: window.innerHeight,
              },
            },
          });
          sessionCreatedRef.current = true;
        } finally {
          sessionCreatePromiseRef.current = null;
        }
      })();
      await sessionCreatePromiseRef.current;
    };

    const flushEvents = async () => {
      if (eventFlushPromiseRef.current) {
        await eventFlushPromiseRef.current;
        return;
      }
      if (!eventBuffer.current.length) return;

      eventFlushPromiseRef.current = (async () => {
        await createSession();
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
          eventFlushPromiseRef.current = null;
        }
      })();
      await eventFlushPromiseRef.current;
    };

    const flushRrweb = async () => {
      if (rrwebFlushPromiseRef.current) {
        await rrwebFlushPromiseRef.current;
        return;
      }
      if (!eventsBuffer.current.length) return;

      rrwebFlushPromiseRef.current = (async () => {
        await createSession();
        const chunk = [...eventsBuffer.current];
        eventsBuffer.current = [];

        try {
          await postJson('/rrweb', {
            session_id: currentSessionId,
            source: SOURCE,
            timestamp: new Date().toISOString(),
            context: {
              url: window.location.href,
              title: document.title,
            },
            events: chunk,
          });
        } catch (error) {
          eventsBuffer.current = [...chunk, ...eventsBuffer.current];
          throw error;
        } finally {
          rrwebFlushPromiseRef.current = null;
        }
      })();
      await rrwebFlushPromiseRef.current;
    };

    const buildEvent = (eventType, payload = {}, context = {}) => ({
      session_id: currentSessionId,
      source: SOURCE,
      event_type: eventType,
      sequence: sequenceRef.current++,
      timestamp: new Date().toISOString(),
      context: {
        url: window.location.href,
        title: document.title,
        viewport: {
          width: window.innerWidth,
          height: window.innerHeight,
        },
        ...context,
      },
      payload,
    });

    const flushEventsSafe = () => {
      flushEvents().catch((error) => {
        console.warn('Event upload failed', error);
      });
    };

    const sendEvent = (eventType, payload = {}, context = {}) => {
      eventBuffer.current.push(buildEvent(eventType, payload, context));
      if (eventBuffer.current.length >= EVENT_BATCH_SIZE) {
        flushEventsSafe();
      }
    };

    const sendSessionEventImmediately = async (eventType, payload = {}, context = {}) => {
      await createSession();
      await postJson('/events', {
        session_id: currentSessionId,
        source: SOURCE,
        event_type: eventType,
        sequence: sequenceRef.current++,
        timestamp: new Date().toISOString(),
        context: {
          url: window.location.href,
          title: document.title,
          viewport: {
            width: window.innerWidth,
            height: window.innerHeight,
          },
          ...context,
        },
        payload,
      });
    };

    const flushRrwebSafe = () => {
      flushRrweb().catch((error) => {
        console.warn('RRWeb upload failed', error);
      });
    };

    const stopRecording = rrweb.record({
      emit(event) {
        eventsBuffer.current.push(event);
      },
      maskAllInputs: false,
      checkoutEveryNth: 100,
    });

    const onClick = (event) => {
      const target = event.target;
      sendEvent(
        'mouse_click',
        {
          x: event.clientX,
          y: event.clientY,
          button: event.button,
          tag_name: target?.tagName?.toLowerCase() || null,
          id: target?.id || null,
          class_name: target?.className || null,
          text: target?.innerText?.substring(0, 50) || null,
          path: getCssPath(target),
        },
      );
    };

    const onScroll = () => {
      sendEvent(
        'scroll',
        {
          scroll_x: window.scrollX,
          scroll_y: window.scrollY,
        },
      );
    };

    const onResize = () => {
      sendEvent(
        'viewport_changed',
        {
          width: window.innerWidth,
          height: window.innerHeight,
        },
      );
    };

    const navigationObserver = new MutationObserver(() => {
      if (window.location.href === lastUrl) return;

      const previousUrl = lastUrl;
      lastUrl = window.location.href;
      sendEvent(
        'route_changed',
        {
          from: previousUrl,
          to: lastUrl,
        },
      );

      if (typeof rrweb.record.takeFullSnapshot === 'function') {
        rrweb.record.takeFullSnapshot();
      }
    });

    const onBeforeUnload = () => {
      if (eventBuffer.current.length) {
        navigator.sendBeacon(
          `${API_URL}/events`,
          new Blob([JSON.stringify({ events: eventBuffer.current })], {
            type: 'application/json',
          }),
        );
      }
      if (eventsBuffer.current.length) {
        navigator.sendBeacon(
          `${API_URL}/rrweb`,
          new Blob(
            [
              JSON.stringify({
                session_id: currentSessionId,
                source: SOURCE,
                timestamp: new Date().toISOString(),
                context: {
                  url: window.location.href,
                  title: document.title,
                },
                events: eventsBuffer.current,
              }),
            ],
            { type: 'application/json' },
          ),
        );
      }
    };

    createSession().catch((error) => console.warn('Session creation failed', error));
    sendSessionEventImmediately('viewport_changed', {
      width: window.innerWidth,
      height: window.innerHeight,
    }).catch((error) => console.warn('Initial viewport event failed', error));

    document.addEventListener('click', onClick, true);
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onResize);
    window.addEventListener('beforeunload', onBeforeUnload);
    navigationObserver.observe(document, { subtree: true, childList: true });

    flushTimerRef.current = window.setInterval(() => {
      flushRrwebSafe();
    }, 5000);
    eventFlushTimerRef.current = window.setInterval(() => {
      flushEventsSafe();
    }, EVENT_FLUSH_INTERVAL_MS);

    return () => {
      window._tracking_initialized = false;
      if (flushTimerRef.current) {
        window.clearInterval(flushTimerRef.current);
      }
      if (eventFlushTimerRef.current) {
        window.clearInterval(eventFlushTimerRef.current);
      }
      flushEventsSafe();
      flushRrwebSafe();
      navigationObserver.disconnect();
      document.removeEventListener('click', onClick, true);
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onResize);
      window.removeEventListener('beforeunload', onBeforeUnload);
      if (typeof stopRecording === 'function') {
        stopRecording();
      }
    };
  }, []);
};
