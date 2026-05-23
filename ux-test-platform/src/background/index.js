import { normalizeCompletionRule } from '../shared/taskRules.js';

const API_URL = 'http://localhost:8000/api';
const DEFAULT_STATE = {
  trackingEnabled: false,
  captureGaze: true,
  captureScreen: true,
  status: 'idle',
  sessionId: null,
  activeTask: null,
  lastError: null,
  lastDiagnostic: null,
};
const SOURCE = 'browser_extension';
const EVENT_BATCH_SIZE = 20;
const RRWEB_BATCH_SIZE = 5;
const FLUSH_INTERVAL_MS = 2000;
const PERSISTED_EVENT_QUEUE_KEY = 'pendingEventQueue';
const PERSISTED_RRWEB_QUEUE_KEY = 'pendingRrwebQueue';
const MAX_PERSISTED_EVENTS = 1000;
const MAX_PERSISTED_RRWEB_CHUNKS = 120;
const SCREEN_QUEUE_DB_NAME = 'ux-screen-recording-queue';
const SCREEN_QUEUE_DB_VERSION = 1;
const SCREEN_QUEUE_STORE = 'screenChunks';
const MAX_PENDING_SCREEN_CHUNKS = 80;
const SCREEN_CHUNK_FLUSH_LIMIT = 1;

let eventQueue = [];
let rrwebQueue = [];
let stateCache = { ...DEFAULT_STATE };
let flushTimerId = null;
let offscreenReady = false;
let queuesLoaded = false;
let flushingQueues = false;
let flushingScreenChunks = false;

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

const trimQueue = (queue, maxItems) =>
  queue.length > maxItems ? queue.slice(queue.length - maxItems) : queue;

const persistQueues = async () => {
  eventQueue = trimQueue(eventQueue, MAX_PERSISTED_EVENTS);
  rrwebQueue = trimQueue(rrwebQueue, MAX_PERSISTED_RRWEB_CHUNKS);
  await chrome.storage.local.set({
    [PERSISTED_EVENT_QUEUE_KEY]: eventQueue,
    [PERSISTED_RRWEB_QUEUE_KEY]: rrwebQueue,
  });
};

const loadPersistedQueues = async () => {
  if (queuesLoaded) return;
  const stored = await chrome.storage.local.get([
    PERSISTED_EVENT_QUEUE_KEY,
    PERSISTED_RRWEB_QUEUE_KEY,
  ]);
  eventQueue = Array.isArray(stored[PERSISTED_EVENT_QUEUE_KEY])
    ? stored[PERSISTED_EVENT_QUEUE_KEY]
    : [];
  rrwebQueue = Array.isArray(stored[PERSISTED_RRWEB_QUEUE_KEY])
    ? stored[PERSISTED_RRWEB_QUEUE_KEY]
    : [];
  queuesLoaded = true;
};

const createSessionId = () => `sess_${Math.random().toString(36).slice(2, 11)}_${Date.now()}`;
const createTaskId = () => `task_${Math.random().toString(36).slice(2, 10)}_${Date.now()}`;

const idbRequest = (request) =>
  new Promise((resolve, reject) => {
    request.addEventListener('success', () => resolve(request.result));
    request.addEventListener('error', () => reject(request.error || new Error('indexeddb_request_failed')));
  });

const openScreenQueueDb = () =>
  new Promise((resolve, reject) => {
    const request = indexedDB.open(SCREEN_QUEUE_DB_NAME, SCREEN_QUEUE_DB_VERSION);
    request.addEventListener('upgradeneeded', () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(SCREEN_QUEUE_STORE)) {
        const store = db.createObjectStore(SCREEN_QUEUE_STORE, {
          keyPath: 'id',
          autoIncrement: true,
        });
        store.createIndex('createdAt', 'createdAt');
      }
    });
    request.addEventListener('success', () => resolve(request.result));
    request.addEventListener('error', () => reject(request.error || new Error('indexeddb_open_failed')));
  });

const withScreenQueueStore = async (mode, callback) => {
  const db = await openScreenQueueDb();
  try {
    const transaction = db.transaction(SCREEN_QUEUE_STORE, mode);
    const store = transaction.objectStore(SCREEN_QUEUE_STORE);
    const result = await callback(store);
    await new Promise((resolve, reject) => {
      transaction.addEventListener('complete', resolve);
      transaction.addEventListener('abort', () => reject(transaction.error || new Error('indexeddb_tx_aborted')));
      transaction.addEventListener('error', () => reject(transaction.error || new Error('indexeddb_tx_failed')));
    });
    return result;
  } finally {
    db.close();
  }
};

const countPendingScreenChunks = async () =>
  withScreenQueueStore('readonly', (store) => idbRequest(store.count()));

const deleteOldestScreenChunks = async (deleteCount) => {
  if (deleteCount <= 0) return;
  await withScreenQueueStore('readwrite', (store) =>
    new Promise((resolve, reject) => {
      let deleted = 0;
      const request = store.openCursor();
      request.addEventListener('success', () => {
        const cursor = request.result;
        if (!cursor || deleted >= deleteCount) {
          resolve();
          return;
        }
        cursor.delete();
        deleted += 1;
        cursor.continue();
      });
      request.addEventListener('error', () => reject(request.error || new Error('screen_queue_trim_failed')));
    })
  );
};

const enqueueScreenRecordingChunk = async (chunk) => {
  await withScreenQueueStore('readwrite', (store) =>
    idbRequest(
      store.add({
        ...chunk,
        createdAt: Date.now(),
      })
    )
  );
  const pendingCount = await countPendingScreenChunks();
  if (pendingCount > MAX_PENDING_SCREEN_CHUNKS) {
    await deleteOldestScreenChunks(pendingCount - MAX_PENDING_SCREEN_CHUNKS);
  }
};

const getPendingScreenChunks = async (limit) =>
  withScreenQueueStore('readonly', (store) =>
    new Promise((resolve, reject) => {
      const chunks = [];
      const request = store.openCursor();
      request.addEventListener('success', () => {
        const cursor = request.result;
        if (!cursor || chunks.length >= limit) {
          resolve(chunks);
          return;
        }
        chunks.push(cursor.value);
        cursor.continue();
      });
      request.addEventListener('error', () => reject(request.error || new Error('screen_queue_read_failed')));
    })
  );

const deleteScreenRecordingChunk = async (id) => {
  await withScreenQueueStore('readwrite', (store) => idbRequest(store.delete(id)));
};

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
  await postJson('/events', {
    events: queue,
  });
};

const sendRrwebChunk = async (chunk) => {
  await postJson('/rrweb', chunk);
};

const sendScreenRecordingChunk = async (chunk) => {
  await postJson('/screen-recording', chunk);
};

const flushScreenRecordingQueue = async () => {
  if (flushingScreenChunks) return;
  flushingScreenChunks = true;
  try {
    const pendingChunks = await getPendingScreenChunks(SCREEN_CHUNK_FLUSH_LIMIT);
    for (const chunk of pendingChunks) {
      const { id, createdAt, ...payload } = chunk;
      void createdAt;
      await sendScreenRecordingChunk(payload);
      await deleteScreenRecordingChunk(id);
    }
  } finally {
    flushingScreenChunks = false;
  }
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

const chooseScreenCapture = async () =>
  new Promise((resolve, reject) => {
    if (!chrome.desktopCapture?.chooseDesktopMedia) {
      reject(new Error('desktopCapture API is not available'));
      return;
    }

    const callback = (streamId, options) => {
      if (!streamId) {
        reject(new Error('Screen recording was cancelled'));
        return;
      }
      resolve({
        streamId,
        canRequestAudioTrack: Boolean(options?.canRequestAudioTrack),
        requestedAt: new Date().toISOString(),
      });
    };

    chrome.desktopCapture.chooseDesktopMedia(['screen', 'window', 'tab'], callback);
  });

const ensureOffscreenDocument = async () => {
  if (offscreenReady) return;
  if (!chrome.offscreen?.createDocument) {
    throw new Error('offscreen API is not available');
  }

  const offscreenUrl = chrome.runtime.getURL('src/offscreen/index.html');
  const contexts = chrome.runtime.getContexts
    ? await chrome.runtime.getContexts({
        contextTypes: ['OFFSCREEN_DOCUMENT'],
        documentUrls: [offscreenUrl],
      })
    : [];

  if (!contexts.length) {
    try {
      await chrome.offscreen.createDocument({
        url: 'src/offscreen/index.html',
        reasons: ['USER_MEDIA'],
        justification: 'Record a user-selected screen or window for UX test sessions.',
      });
    } catch (error) {
      if (!String(error?.message || error).includes('Only a single offscreen')) {
        throw error;
      }
    }
  }

  offscreenReady = true;
};

const sendOffscreenMessage = async (message) => {
  await ensureOffscreenDocument();
  return chrome.runtime.sendMessage({ ...message, target: 'offscreen' });
};

const startScreenRecording = async (sessionId) => {
  const capture = await chooseScreenCapture();
  const response = await sendOffscreenMessage({
    type: 'START_SCREEN_RECORDING',
    streamId: capture.streamId,
    sessionId,
  });
  if (!response?.ok) {
    throw new Error(response?.error || 'screen_recording_start_failed');
  }
  await setStorageState({
    lastDiagnostic: {
      message: 'screen_recording_started',
      details: {
        requestedAt: capture.requestedAt,
      },
      url: null,
      timestamp: new Date().toISOString(),
    },
  });
};

const stopScreenRecording = async () => {
  if (!offscreenReady) return;
  await chrome.runtime.sendMessage({ type: 'STOP_SCREEN_RECORDING', target: 'offscreen' }).catch(() => {});
};

const flushQueues = async () => {
  await loadPersistedQueues();
  if (flushingQueues) return;
  if (!eventQueue.length && !rrwebQueue.length) return;
  flushingQueues = true;

  const pendingEvents = [...eventQueue];
  const pendingRrweb = [...rrwebQueue];

  try {
    if (pendingEvents.length) {
      await sendEventBatch(pendingEvents);
      eventQueue = eventQueue.slice(pendingEvents.length);
      await persistQueues();
    }
    for (const chunk of pendingRrweb) {
      await sendRrwebChunk(chunk);
      rrwebQueue = rrwebQueue.slice(1);
      await persistQueues();
    }
    await flushScreenRecordingQueue();
    await setStorageState({
      status: 'tracking',
      lastError: null,
    });
  } catch (error) {
    await persistQueues().catch(() => {});
    await setStorageState({
      status: 'error',
      lastError: error.message,
    });
    throw error;
  } finally {
    flushingQueues = false;
  }
};

const ensureFlushTimer = () => {
  if (flushTimerId) return;
  flushTimerId = setInterval(() => {
    flushQueues().catch(() => {});
    flushScreenRecordingQueue().catch(() => {});
  }, FLUSH_INTERVAL_MS);
};

const stopFlushTimer = () => {
  if (!flushTimerId) return;
  clearInterval(flushTimerId);
  flushTimerId = null;
};

const broadcastState = async () => {
  const state = await getStorageState();
  const tabs = await chrome.tabs.query({});
  for (const tab of tabs) {
    if (!tab.id) continue;
    chrome.tabs
      .sendMessage(tab.id, {
        type: 'TRACKING_STATE',
        state: {
          ...state,
          currentTabId: tab.id,
        },
      })
      .catch(() => {});
  }
};

const startTracking = async () => {
  await loadPersistedQueues();
  const sessionId = await ensureSession();
  const currentState = await getStorageState();

  if (currentState.captureScreen !== false) {
    await startScreenRecording(sessionId);
  }

  ensureFlushTimer();
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
  await stopScreenRecording();
  await flushQueues().catch(() => {});
  await flushScreenRecordingQueue().catch(() => {});
  stopFlushTimer();
  await setStorageState({
    trackingEnabled: false,
    status: 'idle',
    activeTask: null,
  });
  await broadcastState();
};

const queueEvent = async (payload, sender) => {
  await loadPersistedQueues();
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
  await persistQueues();
  if (eventQueue.length >= EVENT_BATCH_SIZE) {
    await flushQueues();
  }
};

const queueMarkerEvent = async (eventType, payload = {}) => {
  await queueEvent(
    {
      eventType,
      timestamp: new Date().toISOString(),
      context: {},
      payload: {
        ...payload,
        source_ui: payload.source_ui || 'extension_popup',
      },
    },
    null
  );
  await flushQueues();
};

const startTask = async (request) => {
  const label = typeof request.label === 'string' && request.label.trim()
    ? request.label.trim()
    : 'Task';
  const activeTask = {
    id: createTaskId(),
    label,
    completionRule: normalizeCompletionRule(request.completionRule),
    startedAt: new Date().toISOString(),
  };

  await setStorageState({ activeTask });
  await queueMarkerEvent('task_started', {
    task_id: activeTask.id,
    label: activeTask.label,
    completion_rule: activeTask.completionRule,
  });
  await broadcastState();
  return activeTask;
};

const completeTask = async ({
  taskId = null,
  label = null,
  completionSource = 'manual',
  matchedRule = null,
  matchedValue = null,
  sourceUi = 'extension_popup',
} = {}) => {
  const state = await getStorageState();
  const activeTask = state.activeTask;
  const resolvedTaskId = taskId || activeTask?.id || createTaskId();
  const resolvedLabel = label || activeTask?.label || 'Task';

  await queueMarkerEvent('task_completed', {
    task_id: resolvedTaskId,
    label: resolvedLabel,
    completion_source: completionSource,
    matched_rule: matchedRule,
    matched_value: matchedValue,
    started_at: activeTask?.startedAt || null,
    source_ui: sourceUi,
  });

  if (!activeTask || activeTask.id === resolvedTaskId) {
    await setStorageState({ activeTask: null });
    await broadcastState();
  }
};

const queueRrweb = async (payload, sender) => {
  await loadPersistedQueues();
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
  await persistQueues();
  if (rrwebQueue.length >= RRWEB_BATCH_SIZE) {
    await flushQueues();
  }
};

chrome.runtime.onInstalled.addListener(async (details) => {
  if (details.reason === 'install') {
    await chrome.storage.local.set({
      ...DEFAULT_STATE,
      [PERSISTED_EVENT_QUEUE_KEY]: [],
      [PERSISTED_RRWEB_QUEUE_KEY]: [],
    });
    eventQueue = [];
    rrwebQueue = [];
    queuesLoaded = true;
    return;
  }

  await getStorageState();
  await loadPersistedQueues();
});

chrome.runtime.onStartup.addListener(async () => {
  await getStorageState();
  await loadPersistedQueues();
  ensureFlushTimer();
  await broadcastState();
});

chrome.runtime.onSuspend.addListener(() => {
  flushQueues().catch(() => {});
});

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  (async () => {
    switch (request.type) {
      case 'GET_STATUS': {
        const state = await getStorageState();
        sendResponse({ ok: true, ...state, currentTabId: sender?.tab?.id || null });
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
        await flushScreenRecordingQueue();
        sendResponse({ ok: true });
        break;
      }
      case 'TASK_STARTED': {
        const activeTask = await startTask(request);
        sendResponse({ ok: true, activeTask });
        break;
      }
      case 'TASK_COMPLETED': {
        await completeTask({
          label: typeof request.label === 'string' && request.label.trim() ? request.label.trim() : null,
          completionSource: 'manual',
        });
        sendResponse({ ok: true });
        break;
      }
      case 'TASK_AUTO_COMPLETED': {
        const state = await getStorageState();
        if (!state.activeTask || state.activeTask.id !== request.taskId) {
          sendResponse({ ok: true, skipped: true });
          break;
        }
        await completeTask({
          taskId: request.taskId,
          label: request.label,
          completionSource: 'auto_rule',
          matchedRule: request.matchedRule || null,
          matchedValue: request.matchedValue || null,
          sourceUi: 'content_auto_rule',
        });
        sendResponse({ ok: true });
        break;
      }
      case 'NOTE_ADDED': {
        await queueMarkerEvent('note_added', {
          note: request.note || '',
        });
        sendResponse({ ok: true });
        break;
      }
      case 'SET_GAZE': {
        await setStorageState({ captureGaze: Boolean(request.enabled) });
        await broadcastState();
        sendResponse({ ok: true });
        break;
      }
      case 'SET_SCREEN_CAPTURE': {
        await setStorageState({ captureScreen: Boolean(request.enabled) });
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
      case 'SCREEN_RECORDING_CHUNK': {
        const state = await getStorageState();
        if (!state.sessionId) {
          sendResponse({ ok: true, skipped: true });
          break;
        }
        await enqueueScreenRecordingChunk({
          session_id: state.sessionId,
          source: SOURCE,
          timestamp: request.timestamp || new Date().toISOString(),
          chunk_index: request.chunkIndex,
          mime_type: request.mimeType,
          data_base64: request.dataBase64,
          final: Boolean(request.final),
          context: {
            url: sender?.tab?.url || null,
            title: sender?.tab?.title || null,
            tab_id: sender?.tab?.id || null,
          },
        });
        await flushScreenRecordingQueue();
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
