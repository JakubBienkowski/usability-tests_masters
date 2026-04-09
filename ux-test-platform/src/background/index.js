const API_URL = 'http://localhost:8000/api';
const DEFAULT_STATE = {
  trackingEnabled: false,
  captureGaze: true,
  status: 'idle',
  sessionId: null,
  lastError: null,
  lastDiagnostic: null,
};
const SOURCE = 'browser_extension';

let eventQueue = [];
let rrwebQueue = [];
let stateCache = { ...DEFAULT_STATE };

const getStorageState = async () => {
  const stored = await chrome.storage.local.get(Object.keys(DEFAULT_STATE));
  stateCache = {
    ...DEFAULT_STATE,
    ...stored,
  };
  return stateCache;
};

const setStorageState = async (nextState) => {
  stateCache = {
    ...stateCache,
    ...nextState,
  };
  await chrome.storage.local.set(nextState);
  return stateCache;
};

const createSessionId = () => `sess_${Math.random().toString(36).slice(2, 11)}_${Date.now()}`;

const postJson = async (path, payload) => {
  const response = await fetch(`${API_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }

  return response.json().catch(() => null);
};

const ensureSession = async () => {
  const currentState = await getStorageState();
  const sessionId = currentState.sessionId || createSessionId();

  if (!currentState.sessionId) {
    await setStorageState({ sessionId });
  }

  await postJson('/sessions', {
    session_id: sessionId,
    source: SOURCE,
    metadata: {
      extension: 'ux-test-platform',
      started_from: 'browser_extension',
    },
  });

  return sessionId;
};

const sendEventBatch = async (queue) => {
  for (const item of queue) {
    await postJson('/events', item);
  }
};

const sendRrwebChunk = async (chunk) => {
  await postJson('/rrweb', chunk);
};

const isInjectableUrl = (url) => {
  if (!url || typeof url !== 'string') return false;
  return url.startsWith('http://') || url.startsWith('https://');
};

const injectIntoOpenTabs = async () => {
  const tabs = await chrome.tabs.query({});
  await Promise.all(
    tabs
      .filter((tab) => tab.id && isInjectableUrl(tab.url))
      .map(async (tab) => {
        try {
          await chrome.scripting.executeScript({
            target: { tabId: tab.id },
            files: ['content.js'],
          });
        } catch (error) {
          await setStorageState({
            lastDiagnostic: {
              message: 'inject_failed',
              details: {
                tabId: tab.id,
                url: tab.url || null,
                error: error?.message || String(error),
              },
              url: tab.url || null,
              timestamp: new Date().toISOString(),
            },
          });
        }
      })
  );
};

const flushQueues = async () => {
  if (!eventQueue.length && !rrwebQueue.length) return;

  const pendingEvents = [...eventQueue];
  const pendingRrweb = [...rrwebQueue];
  eventQueue = [];
  rrwebQueue = [];

  try {
    if (pendingEvents.length) {
      await sendEventBatch(pendingEvents);
    }
    for (const chunk of pendingRrweb) {
      await sendRrwebChunk(chunk);
    }
    await setStorageState({
      status: 'tracking',
      lastError: null,
    });
  } catch (error) {
    eventQueue = [...pendingEvents, ...eventQueue];
    rrwebQueue = [...pendingRrweb, ...rrwebQueue];
    await setStorageState({
      status: 'error',
      lastError: error.message,
    });
    throw error;
  }
};

const broadcastState = async () => {
  const state = await getStorageState();
  const tabs = await chrome.tabs.query({});
  for (const tab of tabs) {
    if (!tab.id) continue;
    chrome.tabs.sendMessage(tab.id, { type: 'TRACKING_STATE', state }).catch(() => {});
  }
};

const startTracking = async () => {
  const sessionId = await ensureSession();
  await injectIntoOpenTabs();
  await setStorageState({
    trackingEnabled: true,
    status: 'tracking',
    lastError: null,
    sessionId,
  });
  await broadcastState();
  return sessionId;
};

const stopTracking = async () => {
  await flushQueues().catch(() => {});
  await setStorageState({
    trackingEnabled: false,
    status: 'idle',
  });
  await broadcastState();
};

const queueEvent = async (payload, sender) => {
  const state = await getStorageState();
  if (!state.trackingEnabled || !state.sessionId) return;

  eventQueue.push({
    session_id: state.sessionId,
    source: SOURCE,
    event_type: payload.eventType,
    timestamp: payload.timestamp || new Date().toISOString(),
    context: {
      url: payload.context?.url || sender?.tab?.url || null,
      title: payload.context?.title || sender?.tab?.title || null,
      viewport: payload.context?.viewport || null,
      tab_id: sender?.tab?.id || null,
    },
    payload: payload.payload || {},
  });
  await flushQueues();
};

const queueRrweb = async (payload, sender) => {
  const state = await getStorageState();
  if (!state.trackingEnabled || !state.sessionId) return;

  rrwebQueue.push({
    session_id: state.sessionId,
    source: SOURCE,
    timestamp: payload.timestamp || new Date().toISOString(),
    context: {
      url: payload.context?.url || sender?.tab?.url || null,
      title: payload.context?.title || sender?.tab?.title || null,
      viewport: payload.context?.viewport || null,
      tab_id: sender?.tab?.id || null,
    },
    events: payload.events || [],
  });
  await flushQueues();
};

chrome.runtime.onInstalled.addListener(async () => {
  await setStorageState({ ...DEFAULT_STATE });
});

chrome.runtime.onStartup.addListener(async () => {
  await getStorageState();
  await broadcastState();
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  (async () => {
    switch (request.type) {
      case 'GET_STATUS': {
        const state = await getStorageState();
        sendResponse({ ok: true, ...state });
        break;
      }
      case 'START_TRACKING': {
        const sessionId = await startTracking();
        sendResponse({ ok: true, sessionId });
        break;
      }
      case 'STOP_TRACKING': {
        await stopTracking();
        sendResponse({ ok: true });
        break;
      }
      case 'FLUSH_NOW': {
        await flushQueues();
        sendResponse({ ok: true });
        break;
      }
      case 'SET_GAZE': {
        await setStorageState({ captureGaze: Boolean(request.enabled) });
        await broadcastState();
        sendResponse({ ok: true });
        break;
      }
      case 'DIAGNOSTIC': {
        await setStorageState({
          lastDiagnostic: {
            message: request.message || 'unknown diagnostic',
            details: request.details || null,
            url: sender?.tab?.url || null,
            timestamp: new Date().toISOString(),
          },
        });
        sendResponse({ ok: true });
        break;
      }
      case 'TRACK_EVENT': {
        await queueEvent(request, sender);
        sendResponse({ ok: true });
        break;
      }
      case 'RRWEB_CHUNK': {
        await queueRrweb(request, sender);
        sendResponse({ ok: true });
        break;
      }
      default:
        sendResponse({ ok: false, error: 'Unknown message type' });
    }
  })().catch(async (error) => {
    await setStorageState({
      status: 'error',
      lastError: error.message,
    });
    sendResponse({ ok: false, error: error.message });
  });

  return true;
});
