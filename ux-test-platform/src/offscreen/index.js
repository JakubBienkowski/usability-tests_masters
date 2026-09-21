let recorder = null;
let stream = null;
let chunkIndex = 0;
let stopping = false;
const pendingChunkSends = new Set();

const blobToBase64 = (blob) =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener('loadend', () => {
      const result = typeof reader.result === 'string' ? reader.result : '';
      resolve(result.includes(',') ? result.split(',').pop() : result);
    });
    reader.addEventListener('error', () => reject(reader.error || new Error('blob_read_failed')));
    reader.readAsDataURL(blob);
  });

const bestMimeType = () => {
  const candidates = [
    'video/webm;codecs=vp9',
    'video/webm;codecs=vp8',
    'video/webm',
  ];
  return candidates.find((mimeType) => MediaRecorder.isTypeSupported(mimeType)) || '';
};

const sendChunk = async (event) => {
  if (!event.data?.size) return;

  const currentIndex = chunkIndex;
  chunkIndex += 1;
  const dataBase64 = await blobToBase64(event.data);

  await chrome.runtime.sendMessage({
    type: 'SCREEN_RECORDING_CHUNK',
    timestamp: new Date().toISOString(),
    chunkIndex: currentIndex,
    mimeType: recorder?.mimeType || event.data.type || 'video/webm',
    dataBase64,
    final: stopping || recorder?.state === 'inactive',
  });
};

const stopRecording = async () => {
  stopping = true;

  let stopped;
  const stoppedPromise = new Promise((resolve) => {
    stopped = resolve;
  });
  if (recorder && recorder.state !== 'inactive') {
    recorder.addEventListener('stop', stopped, { once: true });
    recorder.stop();
  } else {
    stopped();
  }

  if (stream) {
    for (const track of stream.getTracks()) {
      track.stop();
    }
  }

  await stoppedPromise;
  await Promise.allSettled([...pendingChunkSends]);
  recorder = null;
  stream = null;
};

const startRecording = async (streamId) => {
  await stopRecording();
  chunkIndex = 0;
  stopping = false;

  stream = await navigator.mediaDevices.getUserMedia({
    audio: false,
    video: {
      mandatory: {
        chromeMediaSource: 'desktop',
        chromeMediaSourceId: streamId,
        maxFrameRate: 30,
      },
    },
  });

  const mimeType = bestMimeType();
  recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  recorder.addEventListener('dataavailable', (event) => {
    const sendPromise = sendChunk(event)
      .catch((error) => {
        chrome.runtime.sendMessage({
          type: 'DIAGNOSTIC',
          message: 'screen_recording_chunk_failed',
          details: { message: error?.message || String(error) },
        });
      })
      .finally(() => {
        pendingChunkSends.delete(sendPromise);
      });
    pendingChunkSends.add(sendPromise);
  });
  recorder.addEventListener('stop', () => {
    chrome.runtime.sendMessage({
      type: 'TRACK_EVENT',
      eventType: 'screen_recording_stopped',
      timestamp: new Date().toISOString(),
      payload: { chunks_recorded: chunkIndex },
    });
  });
  stream.getVideoTracks()[0]?.addEventListener('ended', () => {
    stopRecording().catch(() => {});
  });
  recorder.start(4000);

  await chrome.runtime.sendMessage({
    type: 'TRACK_EVENT',
    eventType: 'screen_recording_started',
    timestamp: new Date().toISOString(),
    payload: {
      mime_type: recorder.mimeType || mimeType || 'default',
      capture_source: 'desktopCapture_offscreen',
    },
  });
};

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.target !== 'offscreen') return false;

  (async () => {
    if (message.type === 'START_SCREEN_RECORDING') {
      await startRecording(message.streamId);
      sendResponse({ ok: true });
      return;
    }

    if (message.type === 'STOP_SCREEN_RECORDING') {
      await stopRecording();
      sendResponse({ ok: true });
      return;
    }

    sendResponse({ ok: false, error: 'Unknown offscreen message type' });
  })().catch((error) => {
    sendResponse({ ok: false, error: error?.message || String(error) });
  });

  return true;
});
