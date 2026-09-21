import { normalizeCompletionRule } from '../shared/taskRules.js';

const API_URL = 'http://localhost:8000/api';
const DEFAULT_STATE = {
  trackingEnabled: false,
  captureGaze: true,
  captureScreen: true,
  status: 'idle',
  sessionId: null,
  runId: null,
  producerId: null,
  producerSequence: 0,
  activeTask: null,
  pendingTaskAssessment: null,
  targetTabId: null,
  targetTabUrl: null,
  targetTabTitle: null,
  lastError: null,
  lastDiagnostic: null,
  clockSync: null,
  droppedEventCount: 0,
  droppedRrwebChunkCount: 0,
  studyId: '',
  participantId: '',
  researchMode: true,
  desktopBridge: null,
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
const replacedTargetTabIds = new Set();
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
let producerSequence = 0;

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
  const droppedEvents = Math.max(0, eventQueue.length - MAX_PERSISTED_EVENTS);
  const droppedRrweb = Math.max(0, rrwebQueue.length - MAX_PERSISTED_RRWEB_CHUNKS);
  eventQueue = trimQueue(eventQueue, MAX_PERSISTED_EVENTS);
  rrwebQueue = trimQueue(rrwebQueue, MAX_PERSISTED_RRWEB_CHUNKS);
  await chrome.storage.local.set({
    [PERSISTED_EVENT_QUEUE_KEY]: eventQueue,
    [PERSISTED_RRWEB_QUEUE_KEY]: rrwebQueue,
  });
  if (droppedEvents || droppedRrweb) {
    const state = await getStorageState();
    await setStorageState({
      droppedEventCount: Number(state.droppedEventCount || 0) + droppedEvents,
      droppedRrwebChunkCount: Number(state.droppedRrwebChunkCount || 0) + droppedRrweb,
    });
  }
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
const createRunId = () => `run_${crypto.randomUUID()}`;
const createTaskId = () => `task_${Math.random().toString(36).slice(2, 10)}_${Date.now()}`;
const createEventId = () => crypto.randomUUID();

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
  const runId = currentState.runId || createRunId();
  const producerId = currentState.producerId || `browser_extension:${crypto.randomUUID()}`;

  if (!currentState.sessionId || !currentState.runId || !currentState.producerId) {
    await setStorageState({ sessionId, runId, producerId });
  }

  await postJson('/sessions', {
    session_id: sessionId,
    source: SOURCE,
    metadata: {
      extension: 'ux-test-platform',
      started_from: 'browser_extension',
      run_id: runId,
      study_id: currentState.studyId || null,
      participant_id: currentState.participantId || null,
    },
  });

  return sessionId;
};

const joinDesktopSession = async (sessionId, runId, studyId = null, participantId = null) => {
  const requestedAtMs = Date.now();
  const response = await fetch('http://127.0.0.1:8790/session/join', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      run_id: runId,
      study_id: studyId || null,
      participant_id: participantId || null,
      mode: 'web_desktop',
    }),
  });
  if (!response.ok) throw new Error(`desktop_session_join_failed:${response.status}`);
  const body = await response.json();
  const receivedAtMs = Date.now();
  const bridgeWallMs = Date.parse(body.bridge_wall_time);
  const roundTripMs = receivedAtMs - requestedAtMs;
  const estimatedOffsetMs = Number.isFinite(bridgeWallMs)
    ? bridgeWallMs - (requestedAtMs + roundTripMs / 2)
    : null;
  await setStorageState({
    clockSync: {
      measured_at: new Date(receivedAtMs).toISOString(),
      round_trip_ms: roundTripMs,
      estimated_bridge_offset_ms: estimatedOffsetMs,
    },
    desktopBridge: {
      connected: true,
      joined_at: new Date(receivedAtMs).toISOString(),
      calibration: body.calibration || body.calibration_status || null,
      machine_profile: body.machine_profile || null,
    },
  });
  return body;
};

const leaveDesktopSession = async () => {
  await fetch('http://127.0.0.1:8790/session/leave', { method: 'POST' });
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

const getActiveTargetTab = async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !isInjectableUrl(tab.url)) {
    throw new Error('active_tab_must_be_an_http_or_https_page');
  }
  return tab;
};

const injectIntoTab = async (tabId) => {
  const tab = await chrome.tabs.get(tabId);
  if (!isInjectableUrl(tab.url)) throw new Error('target_tab_is_not_injectable');
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ['content.js'],
    });
  } catch (error) {
    await setStorageState({
      lastDiagnostic: {
        message: 'inject_failed',
        details: {
          tabId,
          url: tab.url || null,
          error: error?.message || String(error),
        },
        url: tab.url || null,
        timestamp: new Date().toISOString(),
      },
    });
    throw error;
  }
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
      const batchesBySession = new Map();
      for (const event of pendingEvents) {
        const sessionId = event.sessionId || event.session_id || '__missing_session__';
        if (!batchesBySession.has(sessionId)) batchesBySession.set(sessionId, []);
        batchesBySession.get(sessionId).push(event);
      }
      for (const batch of batchesBySession.values()) {
        await sendEventBatch(batch);
      }
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
  if (!state.targetTabId) return;
  await chrome.tabs
    .sendMessage(state.targetTabId, {
      type: 'TRACKING_STATE',
      state: {
        ...state,
        currentTabId: state.targetTabId,
      },
    })
    .catch(() => {});
};

const startTracking = async () => {
  await loadPersistedQueues();
  const existingState = await getStorageState();
  if (existingState.trackingEnabled && existingState.sessionId) {
    await joinDesktopSession(
      existingState.sessionId,
      existingState.runId,
      existingState.studyId,
      existingState.participantId
    );
    return existingState.sessionId;
  }
  const targetTab = await getActiveTargetTab();
  const sessionId = await ensureSession();
  const currentState = await getStorageState();
  producerSequence = Number(currentState.producerSequence || 0);

  try {
    await joinDesktopSession(
      sessionId,
      currentState.runId,
      currentState.studyId,
      currentState.participantId
    );
    await setStorageState({
      trackingEnabled: true,
      status: 'tracking',
      lastError: null,
      sessionId,
      targetTabId: targetTab.id,
      targetTabUrl: targetTab.url || null,
      targetTabTitle: targetTab.title || null,
    });
    await injectIntoTab(targetTab.id);
    await broadcastState();
  } catch (error) {
    await stopScreenRecording().catch(() => {});
    await leaveDesktopSession().catch(() => {});
    await setStorageState({
      trackingEnabled: false,
      status: 'error',
      lastError: error?.message || String(error),
      sessionId: null,
      runId: null,
      targetTabId: null,
      targetTabUrl: null,
      targetTabTitle: null,
      desktopBridge: null,
    });
    throw error;
  }

  ensureFlushTimer();
  return sessionId;
};

const stopTracking = async () => {
  const currentState = await getStorageState();
  if (currentState.pendingTaskAssessment) {
    throw new Error('complete_pending_task_assessment_before_stopping');
  }
  if (currentState.activeTask) {
    await completeTask({
      taskId: currentState.activeTask.id,
      label: currentState.activeTask.label,
      completionSource: 'session_stop',
      outcome: 'abandoned',
      seqRating: null,
      assessmentNote: 'Automatically closed when the session was stopped.',
      requestAssessment: false,
    });
  }
  await queueMarkerEvent('session_stopped', {
    completion_source: 'extension_stop',
  }).catch(() => {});
  await flushQueues().catch(() => {});
  await flushScreenRecordingQueue().catch(() => {});
  await leaveDesktopSession().catch(() => {});
  stopFlushTimer();
  await setStorageState({ trackingEnabled: false, status: 'idle' });
  await broadcastState();
  await setStorageState({
    activeTask: null,
    sessionId: null,
    runId: null,
    targetTabId: null,
    targetTabUrl: null,
    targetTabTitle: null,
    desktopBridge: null,
  });
};

const resumeTrackingSession = async () => {
  const state = await getStorageState();
  if (!state.trackingEnabled || !state.sessionId || !state.runId) return;
  producerSequence = Number(state.producerSequence || 0);
  if (!state.targetTabId) {
    await setStorageState({
      trackingEnabled: false,
      status: 'error',
      lastError: 'target_tab_missing_for_resumed_session',
    });
    return;
  }
  await joinDesktopSession(state.sessionId, state.runId, state.studyId, state.participantId);
  ensureFlushTimer();
  await injectIntoTab(state.targetTabId);
  await broadcastState();
};

const queueEvent = async (payload, sender) => {
  await loadPersistedQueues();
  const state = await getStorageState();
  if (!state.trackingEnabled || !state.sessionId) return;
  if (sender?.tab?.id && sender.tab.id !== state.targetTabId) return;
  producerSequence = Math.max(producerSequence, Number(state.producerSequence || 0)) + 1;
  await setStorageState({ producerSequence });

  eventQueue.push({
    event_id: createEventId(),
    schema_version: '2.0',
    session_id: state.sessionId,
    run_id: state.runId,
    producer_id: state.producerId || SOURCE,
    producer_sequence: producerSequence,
    source: SOURCE,
    event_type: payload.eventType,
    captured_at: payload.timestamp || new Date().toISOString(),
    timestamp: payload.timestamp || new Date().toISOString(),
    monotonic_ns: Math.round(performance.now() * 1_000_000),
    coordinate_space: payload.coordinateSpace || null,
    quality: payload.quality || {},
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

  await setStorageState({ activeTask, pendingTaskAssessment: null });
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
  outcome = 'success',
  seqRating = null,
  assessmentNote = null,
  requestAssessment = false,
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
    outcome,
    seq_rating: seqRating,
    assessment_note: assessmentNote,
    assessment_pending: requestAssessment,
  });

  if (!activeTask || activeTask.id === resolvedTaskId) {
    await setStorageState({
      activeTask: null,
      pendingTaskAssessment: requestAssessment
        ? {
            taskId: resolvedTaskId,
            label: resolvedLabel,
            completionSource,
            completedAt: new Date().toISOString(),
            defaultOutcome: outcome,
          }
        : null,
    });
    await broadcastState();
  }
};

const assessCompletedTask = async (request) => {
  const state = await getStorageState();
  const pending = state.pendingTaskAssessment;
  if (!pending?.taskId) throw new Error('no_task_pending_assessment');
  const seqRating = Number(request.seqRating);
  if (!Number.isInteger(seqRating) || seqRating < 1 || seqRating > 7) {
    throw new Error('seq_rating_must_be_between_1_and_7');
  }
  await queueMarkerEvent('task_assessed', {
    task_id: pending.taskId,
    label: pending.label,
    completion_source: pending.completionSource,
    outcome: request.outcome || pending.defaultOutcome || 'success',
    seq_rating: seqRating,
    assessment_note: String(request.assessmentNote || '').trim().slice(0, 1000) || null,
  });
  await setStorageState({ pendingTaskAssessment: null });
  await broadcastState();
};

const queueRrweb = async (payload, sender) => {
  await loadPersistedQueues();
  const state = await getStorageState();
  if (!state.trackingEnabled || !state.sessionId) return;
  if (!sender?.tab?.id || sender.tab.id !== state.targetTabId) return;

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
  await resumeTrackingSession().catch(() => {});
});

chrome.runtime.onStartup.addListener(async () => {
  await getStorageState();
  await loadPersistedQueues();
  await resumeTrackingSession().catch(() => {});
  await broadcastState();
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status !== 'complete') return;
  (async () => {
    const state = await getStorageState();
    if (!state.trackingEnabled || state.targetTabId !== tabId) return;
    if (!isInjectableUrl(tab.url)) {
      await setStorageState({
        status: 'error',
        lastError: 'target_tab_navigated_to_unsupported_page',
      });
      return;
    }
    await setStorageState({
      status: 'tracking',
      lastError: null,
      targetTabUrl: tab.url || null,
      targetTabTitle: tab.title || null,
    });
    await queueMarkerEvent('page_navigation_completed', {
      tab_id: tabId,
      url: tab.url || null,
      title: tab.title || null,
    }).catch(() => {});
    await injectIntoTab(tabId);
    await broadcastState();
  })().catch(async (error) => {
    await setStorageState({
      status: 'error',
      lastError: error?.message || String(error),
    });
  });
});

chrome.tabs.onReplaced.addListener((addedTabId, removedTabId) => {
  replacedTargetTabIds.add(removedTabId);
  (async () => {
    const state = await getStorageState();
    if (!state.trackingEnabled || state.targetTabId !== removedTabId) return;
    const tab = await chrome.tabs.get(addedTabId);
    await setStorageState({
      status: 'tracking',
      lastError: null,
      targetTabId: addedTabId,
      targetTabUrl: tab.url || null,
      targetTabTitle: tab.title || null,
    });
    await queueMarkerEvent('target_tab_replaced', {
      previous_tab_id: removedTabId,
      tab_id: addedTabId,
      url: tab.url || null,
    }).catch(() => {});
    if (isInjectableUrl(tab.url)) {
      await injectIntoTab(addedTabId);
    }
    await broadcastState();
  })().catch(async (error) => {
    await setStorageState({
      status: 'tracking',
      lastError: `target_tab_replacement_recovery_failed:${error?.message || String(error)}`,
    });
  }).finally(() => {
    setTimeout(() => replacedTargetTabIds.delete(removedTabId), 5000);
  });
});

chrome.tabs.onRemoved.addListener((tabId) => {
  (async () => {
    if (replacedTargetTabIds.has(tabId)) return;
    const state = await getStorageState();
    if (!state.trackingEnabled || state.targetTabId !== tabId) return;

    const candidates = await chrome.tabs.query({});
    const replacement = candidates.find((tab) => isInjectableUrl(tab.url));
    await setStorageState({
      status: 'tracking',
      lastError: replacement ? null : 'web_tab_closed_desktop_capture_continues',
      targetTabId: replacement?.id || null,
      targetTabUrl: replacement?.url || null,
      targetTabTitle: replacement?.title || null,
    });
    await queueMarkerEvent('target_tab_closed', {
      previous_tab_id: tabId,
      replacement_tab_id: replacement?.id || null,
      recording_continues: true,
    }).catch(() => {});
    if (replacement?.id) await injectIntoTab(replacement.id);
    await broadcastState();
  })().catch(() => {});
});

chrome.tabs.onActivated.addListener(({ tabId }) => {
  (async () => {
    const state = await getStorageState();
    if (!state.trackingEnabled || state.targetTabId) return;
    const tab = await chrome.tabs.get(tabId);
    if (!isInjectableUrl(tab.url)) return;
    await setStorageState({
      status: 'tracking',
      lastError: null,
      targetTabId: tab.id,
      targetTabUrl: tab.url || null,
      targetTabTitle: tab.title || null,
    });
    await injectIntoTab(tab.id);
    await broadcastState();
  })().catch(() => {});
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
        const seqRating = Number(request.seqRating);
        if (!Number.isInteger(seqRating) || seqRating < 1 || seqRating > 7) {
          throw new Error('seq_rating_must_be_between_1_and_7');
        }
        await completeTask({
          label: typeof request.label === 'string' && request.label.trim() ? request.label.trim() : null,
          completionSource: 'manual',
          outcome: request.outcome || 'success',
          seqRating,
          assessmentNote: String(request.assessmentNote || '').trim().slice(0, 1000) || null,
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
          outcome: 'success',
          requestAssessment: true,
        });
        sendResponse({ ok: true });
        break;
      }
      case 'TASK_ASSESSED': {
        await assessCompletedTask(request);
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
      case 'ATTENTION_PROBE_RESPONSE': {
        const rating = Number(request.rating);
        if (!Number.isInteger(rating) || rating < 1 || rating > 5) {
          throw new Error('attention_rating_must_be_between_1_and_5');
        }
        await queueMarkerEvent('attention_probe_response', {
          rating,
          mind_wandering: rating <= 2,
          scale: 'focus_1_5',
          prompt: 'Focused right now?',
        });
        sendResponse({ ok: true });
        break;
      }
      case 'SESSION_QUESTIONNAIRE_RESPONSE': {
        const answers = Array.isArray(request.susAnswers)
          ? request.susAnswers.map(Number)
          : [];
        if (answers.length !== 10 || answers.some((value) => !Number.isInteger(value) || value < 1 || value > 5)) {
          throw new Error('sus_requires_ten_answers_between_1_and_5');
        }
        await queueMarkerEvent('session_questionnaire_response', {
          questionnaire: 'SUS',
          questionnaire_version: 'sus_10_item_custom_pl_wording_v1',
          validated_translation: false,
          sus_answers: answers,
        });
        sendResponse({ ok: true });
        break;
      }
      case 'SET_STUDY_CONTEXT': {
        const state = await getStorageState();
        if (state.trackingEnabled) {
          throw new Error('study_context_cannot_change_during_tracking');
        }
        await setStorageState({
          studyId: String(request.studyId || '').trim(),
          participantId: String(request.participantId || '').trim(),
        });
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
