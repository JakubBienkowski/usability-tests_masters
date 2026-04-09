import { record } from 'rrweb';
import * as faceLandmarksDetection from '@tensorflow-models/face-landmarks-detection';
import webgazer from 'webgazer';

if (window.__uxTestPlatformContentLoaded) {
  console.warn('[ux-test-platform] duplicate_content_script_skipped');
} else {
  window.__uxTestPlatformContentLoaded = true;

const SOURCE = 'browser_extension_content';
const TRACKER_NAME = 'ExtensionTfjsFaceMesh';
const GAZE_EVENT_INTERVAL_MS = 50;
const EYE_INDICES = {
  leftEyeUpper0: [466, 388, 387, 386, 385, 384, 398],
  leftEyeLower0: [263, 249, 390, 373, 374, 380, 381, 382, 362],
  rightEyeUpper0: [246, 161, 160, 159, 158, 157, 173],
  rightEyeLower0: [33, 7, 163, 144, 145, 153, 154, 155, 133],
};

let trackerState = {
  trackingEnabled: false,
  captureGaze: true,
  sessionId: null,
};

let rrwebStop = null;
let rrwebBuffer = [];
let rrwebInterval = null;
let initialized = false;
let listenersBound = false;
let routeObserver = null;
let currentUrl = window.location.href;
let lastGazeSentAt = 0;
let lastLookedElement = null;
let fixationStartedAt = Date.now();
let gazeInitialized = false;
let trackerRegistered = false;
let gazeSampleCount = 0;
let gazePointEventCount = 0;
let gazeNullCount = 0;
let gazeStartedAt = 0;
let firstGazeSampleReported = false;
let gazeWatchdogId = null;
let trainingSampleCount = 0;
let trackerNullCount = 0;
let facePredictionNullCount = 0;
let detectorSanityCheckCount = 0;
let lastDetectedEyes = null;
let lastDetectedEyesAt = 0;
let lastDetectedPositions = null;
const TRACKER_FALLBACK_MS = 5000;
let lastGazeData = null;
let lastGazeDataAt = 0;
const GAZE_FALLBACK_MS = 8000;
let extensionGazeDot = null;
let calibrationOverlay = null;
let calibrationActive = false;
let calibrationTargetIndex = 0;
let calibrationTargetClicks = 0;
const CALIBRATION_CLICKS_PER_TARGET = 2;
const CALIBRATION_MIN_EXISTING_SAMPLES = 18;
const CALIBRATION_TARGETS = [
  { x: 0.16, y: 0.2 },
  { x: 0.5, y: 0.2 },
  { x: 0.84, y: 0.2 },
  { x: 0.16, y: 0.5 },
  { x: 0.5, y: 0.5 },
  { x: 0.84, y: 0.5 },
  { x: 0.16, y: 0.8 },
  { x: 0.5, y: 0.8 },
  { x: 0.84, y: 0.8 },
];

const ensureExtensionGazeDot = () => {
  if (extensionGazeDot?.isConnected) return extensionGazeDot;

  const dot = document.createElement('div');
  dot.id = 'ux-test-platform-gaze-dot';
  dot.style.position = 'fixed';
  dot.style.left = '-9999px';
  dot.style.top = '-9999px';
  dot.style.width = '18px';
  dot.style.height = '18px';
  dot.style.marginLeft = '-9px';
  dot.style.marginTop = '-9px';
  dot.style.borderRadius = '999px';
  dot.style.background = '#00c853';
  dot.style.border = '2px solid #ffffff';
  dot.style.boxShadow = '0 0 0 4px rgba(0,0,0,0.25), 0 0 18px rgba(0,200,83,0.8)';
  dot.style.pointerEvents = 'none';
  dot.style.zIndex = '2147483647';
  dot.style.display = 'none';
  document.documentElement.appendChild(dot);
  extensionGazeDot = dot;
  return dot;
};

const showExtensionGazeDot = (x, y) => {
  const dot = ensureExtensionGazeDot();
  dot.style.display = 'block';
  dot.style.left = `${Math.round(x)}px`;
  dot.style.top = `${Math.round(y)}px`;
  dot.style.transform = 'translate(0, 0)';
};

const hideExtensionGazeDot = () => {
  if (!extensionGazeDot) return;
  extensionGazeDot.style.display = 'none';
};

const boundToViewport = (x, y) => ({
  x: Math.max(0, Math.min(window.innerWidth - 1, Math.round(x))),
  y: Math.max(0, Math.min(window.innerHeight - 1, Math.round(y))),
});

const calibrationTargetPoint = (target) =>
  boundToViewport(window.innerWidth * target.x, window.innerHeight * target.y);

const getRegressionDataSize = () => {
  try {
    const regressions = webgazer.getRegression?.();
    const data = regressions?.[0]?.getData?.();
    if (Array.isArray(data)) return data.length;
    if (data && typeof data === 'object') {
      return Object.values(data).reduce((count, value) => {
        if (Array.isArray(value)) return count + value.length;
        return count;
      }, 0);
    }
  } catch {}
  return null;
};

const getTrackerPositionsCount = () => {
  try {
    const positions = webgazer.getTracker?.()?.getPositions?.();
    return Array.isArray(positions) ? positions.length : 0;
  } catch {
    return null;
  }
};

const removeCalibrationOverlay = () => {
  calibrationActive = false;
  calibrationTargetIndex = 0;
  calibrationTargetClicks = 0;
  if (!calibrationOverlay) return;
  calibrationOverlay.remove();
  calibrationOverlay = null;
};

const emitCalibrationPoint = (x, y) => {
  trainingSampleCount += 1;
  try {
    if (trackerState.trackingEnabled && trackerState.captureGaze && webgazer) {
      webgazer.recordScreenPosition(x, y, 'click');
      const regressions = webgazer.getRegression?.() || [];
      if (lastDetectedEyes) {
        for (const regression of regressions) {
          regression?.addData?.(lastDetectedEyes, [x, y], 'click');
        }
      }
      reportDiagnostic('calibration_click_recorded', {
        x,
        y,
        regressionDataSize: getRegressionDataSize(),
        trackerPositionsCount: getTrackerPositionsCount(),
        hasLastDetectedEyes: Boolean(lastDetectedEyes),
      });
    }
  } catch (error) {
    reportDiagnostic('calibration_click_failed', {
      message: error?.message || String(error),
    });
  }
};

const finishCalibrationOverlay = () => {
  reportDiagnostic('calibration_overlay_completed', {
    regressionDataSize: getRegressionDataSize(),
  });
  removeCalibrationOverlay();
};

const renderCalibrationOverlay = () => {
  if (!calibrationOverlay) return;

  const progress = calibrationOverlay.querySelector('[data-role="progress"]');
  if (progress) {
    progress.textContent = `Target ${calibrationTargetIndex + 1}/${CALIBRATION_TARGETS.length} • Click ${calibrationTargetClicks + 1}/${CALIBRATION_CLICKS_PER_TARGET}`;
  }

  const buttons = calibrationOverlay.querySelectorAll('[data-calibration-index]');
  buttons.forEach((button) => {
    const index = Number(button.getAttribute('data-calibration-index'));
    const point = calibrationTargetPoint(CALIBRATION_TARGETS[index]);
    button.style.left = `${point.x}px`;
    button.style.top = `${point.y}px`;
    button.style.opacity = index === calibrationTargetIndex ? '1' : '0.28';
    button.style.transform = index === calibrationTargetIndex ? 'scale(1.08)' : 'scale(0.92)';
    button.style.boxShadow =
      index === calibrationTargetIndex
        ? '0 0 0 6px rgba(255,255,255,0.2), 0 0 0 14px rgba(0,200,83,0.16)'
        : '0 0 0 3px rgba(255,255,255,0.08)';
  });
};

const startCalibrationOverlay = () => {
  if (calibrationOverlay?.isConnected) {
    calibrationActive = true;
    renderCalibrationOverlay();
    return;
  }

  calibrationActive = true;
  calibrationTargetIndex = 0;
  calibrationTargetClicks = 0;

  const overlay = document.createElement('div');
  overlay.id = 'ux-test-platform-calibration-overlay';
  overlay.style.position = 'fixed';
  overlay.style.inset = '0';
  overlay.style.zIndex = '2147483646';
  overlay.style.pointerEvents = 'none';
  overlay.style.background = 'radial-gradient(circle at center, rgba(0,0,0,0.04), rgba(0,0,0,0.14))';

  const panel = document.createElement('div');
  panel.style.position = 'fixed';
  panel.style.top = '20px';
  panel.style.left = '50%';
  panel.style.transform = 'translateX(-50%)';
  panel.style.padding = '10px 14px';
  panel.style.borderRadius = '999px';
  panel.style.background = 'rgba(18, 18, 18, 0.82)';
  panel.style.color = '#fff';
  panel.style.font = '600 13px/1.2 system-ui, sans-serif';
  panel.style.letterSpacing = '0.02em';
  panel.style.pointerEvents = 'none';

  const title = document.createElement('div');
  title.textContent = 'Calibration';
  title.style.fontWeight = '700';
  title.style.marginBottom = '4px';
  panel.appendChild(title);

  const progress = document.createElement('div');
  progress.setAttribute('data-role', 'progress');
  panel.appendChild(progress);
  overlay.appendChild(panel);

  CALIBRATION_TARGETS.forEach((target, index) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.setAttribute('data-calibration-index', String(index));
    button.style.position = 'fixed';
    button.style.width = '30px';
    button.style.height = '30px';
    button.style.marginLeft = '-15px';
    button.style.marginTop = '-15px';
    button.style.borderRadius = '999px';
    button.style.border = '2px solid rgba(255,255,255,0.92)';
    button.style.background = index === calibrationTargetIndex ? '#00c853' : 'rgba(255,255,255,0.2)';
    button.style.cursor = 'crosshair';
    button.style.pointerEvents = 'auto';
    button.style.transition = 'transform 120ms ease, opacity 120ms ease, box-shadow 120ms ease';
    button.addEventListener('click', (event) => {
      event.preventDefault();
      event.stopPropagation();
      if (!trackerState.trackingEnabled || !trackerState.captureGaze) return;
      if (index !== calibrationTargetIndex) return;

      const point = calibrationTargetPoint(target);
      emitCalibrationPoint(point.x, point.y);
      calibrationTargetClicks += 1;

      if (calibrationTargetClicks >= CALIBRATION_CLICKS_PER_TARGET) {
        calibrationTargetClicks = 0;
        calibrationTargetIndex += 1;
      }

      if (calibrationTargetIndex >= CALIBRATION_TARGETS.length) {
        finishCalibrationOverlay();
        return;
      }

      renderCalibrationOverlay();
    });
    overlay.appendChild(button);
  });

  document.documentElement.appendChild(overlay);
  calibrationOverlay = overlay;
  renderCalibrationOverlay();
};

class ExtensionTfjsFaceMesh {
  constructor() {
    this.model = faceLandmarksDetection.SupportedModels.MediaPipeFaceMesh;
    this.detector = null;
    this.predictionReady = false;
    this.positionsArray = null;
  }

  async init() {
    if (this.detector) return this.detector;

    const detectorConfig = {
      runtime: 'tfjs',
      maxFaces: 1,
      refineLandmarks: false,
    };

    this.detector = await faceLandmarksDetection.createDetector(this.model, detectorConfig);
    reportDiagnostic('tracker_detector_ready', {
      runtime: detectorConfig.runtime,
      maxFaces: detectorConfig.maxFaces,
      refineLandmarks: detectorConfig.refineLandmarks,
    });
    return this.detector;
  }

  async getEyePatches(video, imageCanvas) {
    if (imageCanvas.width === 0) return null;

    await this.init();
    let predictions = await this.detector.estimateFaces(video);

    if (!predictions.length) {
      let canvasPredictions = [];
      try {
        canvasPredictions = await this.detector.estimateFaces(imageCanvas);
      } catch (error) {
        reportDiagnostic('tracker_canvas_check_failed', {
          message: error?.message || String(error),
        });
      }

      if (detectorSanityCheckCount < 10 || canvasPredictions.length) {
        detectorSanityCheckCount += 1;
        reportDiagnostic('tracker_sanity_check', {
          count: detectorSanityCheckCount,
          videoFaces: predictions.length,
          canvasFaces: canvasPredictions.length,
          videoWidth: video?.videoWidth || null,
          videoHeight: video?.videoHeight || null,
          canvasWidth: imageCanvas.width,
          canvasHeight: imageCanvas.height,
          readyState: video?.readyState ?? null,
        });
      }

      if (canvasPredictions.length) {
        predictions = canvasPredictions;
      }
    }

    if (!predictions.length) {
      facePredictionNullCount += 1;
      const fallbackAge = lastDetectedEyesAt ? Date.now() - lastDetectedEyesAt : null;
      if (lastDetectedEyes && fallbackAge !== null && fallbackAge <= TRACKER_FALLBACK_MS) {
        this.positionsArray = lastDetectedPositions;
        if (facePredictionNullCount === 1 || facePredictionNullCount % 20 === 0) {
          reportDiagnostic('tracker_using_fallback', {
            count: facePredictionNullCount,
            fallbackAge,
            trackerPositionsCount: this.positionsArray?.length || 0,
          });
        }
        return lastDetectedEyes;
      }
      if (facePredictionNullCount === 1 || facePredictionNullCount % 20 === 0) {
        reportDiagnostic('tracker_no_face', {
          count: facePredictionNullCount,
          videoWidth: video?.videoWidth || null,
          videoHeight: video?.videoHeight || null,
          canvasWidth: imageCanvas.width,
          canvasHeight: imageCanvas.height,
          readyState: video?.readyState ?? null,
        });
      }
      return false;
    }
    facePredictionNullCount = 0;

    reportDiagnostic('tracker_face_detected', {
      faces: predictions.length,
      keypoints: predictions[0]?.keypoints?.length || 0,
    });

    const keypoints = predictions[0].keypoints;
    this.positionsArray = keypoints.map((kp) => [kp.x, kp.y, kp.z || 0]);

    const getPointsByIndices = (indices) =>
      indices.map((idx) => [keypoints[idx].x, keypoints[idx].y, keypoints[idx].z || 0]);

    const [leftBBox, rightBBox] = [
      {
        eyeTopArc: getPointsByIndices(EYE_INDICES.leftEyeUpper0),
        eyeBottomArc: getPointsByIndices(EYE_INDICES.leftEyeLower0),
      },
      {
        eyeTopArc: getPointsByIndices(EYE_INDICES.rightEyeUpper0),
        eyeBottomArc: getPointsByIndices(EYE_INDICES.rightEyeLower0),
      },
    ].map(({ eyeTopArc, eyeBottomArc }) => {
      const topLeftOrigin = {
        x: Math.round(Math.min(...eyeTopArc.map((v) => v[0]))),
        y: Math.round(Math.min(...eyeTopArc.map((v) => v[1]))),
      };
      const bottomRightOrigin = {
        x: Math.round(Math.max(...eyeBottomArc.map((v) => v[0]))),
        y: Math.round(Math.max(...eyeBottomArc.map((v) => v[1]))),
      };

      return {
        origin: topLeftOrigin,
        width: bottomRightOrigin.x - topLeftOrigin.x,
        height: bottomRightOrigin.y - topLeftOrigin.y,
      };
    });

    const leftOriginX = leftBBox.origin.x;
    const leftOriginY = leftBBox.origin.y;
    const leftWidth = leftBBox.width;
    const leftHeight = leftBBox.height;
    const rightOriginX = rightBBox.origin.x;
    const rightOriginY = rightBBox.origin.y;
    const rightWidth = rightBBox.width;
    const rightHeight = rightBBox.height;

    if (!leftWidth || !rightWidth || !leftHeight || !rightHeight) return null;

    const context = imageCanvas.getContext('2d', { willReadFrequently: true });

    const detectedEyes = {
      left: {
        patch: context.getImageData(leftOriginX, leftOriginY, leftWidth, leftHeight),
        imagex: leftOriginX,
        imagey: leftOriginY,
        width: leftWidth,
        height: leftHeight,
      },
      right: {
        patch: context.getImageData(rightOriginX, rightOriginY, rightWidth, rightHeight),
        imagex: rightOriginX,
        imagey: rightOriginY,
        width: rightWidth,
        height: rightHeight,
      },
    };

    lastDetectedEyes = detectedEyes;
    lastDetectedEyesAt = Date.now();
    lastDetectedPositions = this.positionsArray;
    return detectedEyes;
  }

  getPositions() {
    return this.positionsArray;
  }

  reset() {}

  drawFaceOverlay(ctx, keypoints) {
    if (!keypoints) return;

    ctx.fillStyle = '#32EEDB';
    ctx.strokeStyle = '#32EEDB';
    ctx.lineWidth = 0.5;

    for (let i = 0; i < keypoints.length; i += 1) {
      const x = keypoints[i][0];
      const y = keypoints[i][1];
      ctx.beginPath();
      ctx.arc(x, y, 1, 0, 2 * Math.PI);
      ctx.closePath();
      ctx.fill();
    }
  }
}

const postMessage = (payload) =>
  chrome.runtime.sendMessage(payload).catch(() => {});

const reportDiagnostic = (message, details = {}) => {
  console.log('[ux-test-platform]', message, details);
  postMessage({
    type: 'DIAGNOSTIC',
    message,
    details,
  });
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

const getElementPayload = (element) => ({
  tag_name: element?.tagName?.toLowerCase() || null,
  id: element?.id || null,
  class_name: typeof element?.className === 'string' ? element.className : null,
  text: element?.innerText?.substring(0, 80) || null,
  path: getCssPath(element),
});

const baseContext = () => ({
  url: window.location.href,
  title: document.title,
  viewport: {
    width: window.innerWidth,
    height: window.innerHeight,
  },
});

const sendEvent = (eventType, payload = {}) => {
  if (!trackerState.trackingEnabled) return;
  postMessage({
    type: 'TRACK_EVENT',
    eventType,
    timestamp: new Date().toISOString(),
    context: baseContext(),
    payload,
  });
};

const flushRrweb = () => {
  if (!trackerState.trackingEnabled || !rrwebBuffer.length) return;
  const chunk = [...rrwebBuffer];
  rrwebBuffer = [];
  postMessage({
    type: 'RRWEB_CHUNK',
    timestamp: new Date().toISOString(),
    context: baseContext(),
    events: chunk,
  });
};

const startRrweb = () => {
  if (rrwebStop) return;

  try {
    rrwebStop = record({
      emit(event) {
        rrwebBuffer.push(event);
        if (rrwebBuffer.length >= 100) {
          flushRrweb();
        }
      },
      maskAllInputs: false,
      checkoutEveryNth: 100,
    });
  } catch (error) {
    reportDiagnostic('rrweb_start_failed', {
      message: error?.message || String(error),
    });
    throw error;
  }

  rrwebInterval = window.setInterval(flushRrweb, 5000);
  reportDiagnostic('rrweb_started');
};

const stopRrweb = () => {
  if (rrwebInterval) {
    window.clearInterval(rrwebInterval);
    rrwebInterval = null;
  }
  flushRrweb();
  if (typeof rrwebStop === 'function') {
    rrwebStop();
  }
  rrwebStop = null;
};

const startGazeTracking = async () => {
  if (gazeInitialized || !trackerState.captureGaze) return;
  gazeInitialized = true;
  gazeStartedAt = Date.now();
  gazeSampleCount = 0;
  gazePointEventCount = 0;
  gazeNullCount = 0;
  trackerNullCount = 0;
  firstGazeSampleReported = false;

  if (!trackerRegistered) {
    webgazer.addTrackerModule(TRACKER_NAME, ExtensionTfjsFaceMesh);
    trackerRegistered = true;
  }
  webgazer.setTracker(TRACKER_NAME);
  webgazer.showVideoPreview(true);
  webgazer.showFaceOverlay(true);
  webgazer.showFaceFeedbackBox(true);
  reportDiagnostic('gaze_starting', {
    secureContext: window.isSecureContext,
    hasMediaDevices: Boolean(navigator.mediaDevices),
    hasGetUserMedia: typeof navigator.mediaDevices?.getUserMedia === 'function',
    tracker: TRACKER_NAME,
  });

  if (gazeWatchdogId) {
    window.clearTimeout(gazeWatchdogId);
  }
  gazeWatchdogId = window.setTimeout(() => {
    reportDiagnostic('gaze_watchdog', {
      sampleCount: gazeSampleCount,
      pointEventCount: gazePointEventCount,
      nullCount: gazeNullCount,
      trainingSampleCount,
      regressionDataSize: getRegressionDataSize(),
      trackerPositionsCount: getTrackerPositionsCount(),
      elapsedMs: Date.now() - gazeStartedAt,
    });
  }, 5000);

  try {
    await webgazer
      .setGazeListener((data) => {
        if (!trackerState.trackingEnabled || !trackerState.captureGaze) return;

        if (!data) {
          gazeNullCount += 1;
          const gazeFallbackAge = lastGazeDataAt ? Date.now() - lastGazeDataAt : null;
          if (lastGazeData && gazeFallbackAge !== null && gazeFallbackAge <= GAZE_FALLBACK_MS) {
            if (gazeNullCount === 1 || gazeNullCount % 20 === 0) {
              reportDiagnostic('gaze_using_fallback', {
                nullCount: gazeNullCount,
                fallbackAge: gazeFallbackAge,
                regressionDataSize: getRegressionDataSize(),
              });
            }
            data = lastGazeData;
          }
        }

        if (!data) {
          if (gazeNullCount === 1 || gazeNullCount % 20 === 0) {
            const trackerPositionsCount = getTrackerPositionsCount();
            if (trackerPositionsCount === 0) {
              trackerNullCount += 1;
            }
            reportDiagnostic('gaze_listener_null', {
              nullCount: gazeNullCount,
              trackerPositionsCount,
              trackerNullCount,
              trainingSampleCount,
              regressionDataSize: getRegressionDataSize(),
            });
          }
          return;
        }

        gazeSampleCount += 1;
        if (!firstGazeSampleReported) {
          firstGazeSampleReported = true;
          reportDiagnostic('gaze_first_sample', {
            sampleCount: gazeSampleCount,
            x: Math.round(data.x),
            y: Math.round(data.y),
            confidence: typeof data.confidence === 'number' ? data.confidence : null,
          });
        }

        const boundedPoint = boundToViewport(data.x, data.y);
        lastGazeData = boundedPoint;
        lastGazeDataAt = Date.now();
        showExtensionGazeDot(boundedPoint.x, boundedPoint.y);

        const now = Date.now();
        const x = data.x;
        const y = data.y;
        const pointedElement = document.elementFromPoint(x, y);
        const meaningfulElement = pointedElement?.closest(
          'button, input, a, h1, h2, h3, p, img, form, textarea, label'
        );

        if (now - lastGazeSentAt >= GAZE_EVENT_INTERVAL_MS) {
          lastGazeSentAt = now;
          gazePointEventCount += 1;
          sendEvent('gaze_point', {
            screen_x: boundedPoint.x,
            screen_y: boundedPoint.y,
            confidence: typeof data.confidence === 'number' ? data.confidence : null,
          });
          if (gazePointEventCount === 1 || gazePointEventCount % 20 === 0) {
            reportDiagnostic('gaze_point_sent', {
              pointEventCount: gazePointEventCount,
              sampleCount: gazeSampleCount,
              x: boundedPoint.x,
              y: boundedPoint.y,
            });
          }
        }

        if (!meaningfulElement) return;

        if (meaningfulElement !== lastLookedElement) {
          const duration = now - fixationStartedAt;
          if (lastLookedElement && duration > 400) {
            sendEvent('gaze_fixation', {
              ...getElementPayload(lastLookedElement),
              duration_ms: duration,
            });
          }
          lastLookedElement = meaningfulElement;
          fixationStartedAt = now;
        }
      })
      .begin();

    webgazer.showVideoPreview(false);
    webgazer.showPredictionPoints(true);
    reportDiagnostic('gaze_started');
    if (!trackerState.trackingEnabled || !trackerState.captureGaze) {
      webgazer.pause();
    }
  } catch (error) {
    reportDiagnostic('gaze_init_failed', {
      message: error?.message || String(error),
      name: error?.name || null,
    });
    sendEvent('gaze_init_failed', {
      message: error.message,
    });
  }
};

const updateGazeState = () => {
  if (!webgazer) return;

  if (trackerState.trackingEnabled && trackerState.captureGaze) {
    webgazer.resume();
    webgazer.showPredictionPoints(false);
    if (!calibrationActive && (getRegressionDataSize() ?? 0) < CALIBRATION_MIN_EXISTING_SAMPLES) {
      startCalibrationOverlay();
    } else if (calibrationActive) {
      renderCalibrationOverlay();
    }
  } else {
    webgazer.pause();
    webgazer.showPredictionPoints(false);
    hideExtensionGazeDot();
    removeCalibrationOverlay();
  }
};

const handleClick = (event) => {
  if (event.target?.closest?.('#ux-test-platform-calibration-overlay')) return;
  trainingSampleCount += 1;
  console.error('[ux-test-platform] calibration_click_handler', {
    x: event.clientX,
    y: event.clientY,
    trackingEnabled: trackerState.trackingEnabled,
    captureGaze: trackerState.captureGaze,
    hasWebgazer: Boolean(webgazer),
    hasLastDetectedEyes: Boolean(lastDetectedEyes),
  });
  sendEvent('mouse_click', {
    x: event.clientX,
    y: event.clientY,
    button: event.button,
    ...getElementPayload(event.target),
  });
};

const handlePointerDown = (event) => {
  if (event.target?.closest?.('#ux-test-platform-calibration-overlay')) return;
  console.error('[ux-test-platform] calibration_pointerdown', {
    x: event.clientX,
    y: event.clientY,
    regressionDataSize: getRegressionDataSize(),
    trackerPositionsCount: getTrackerPositionsCount(),
  });
};

const handleScroll = () => {
  sendEvent('scroll', {
    scroll_x: window.scrollX,
    scroll_y: window.scrollY,
  });
};

const handleResize = () => {
  if (calibrationActive) {
    renderCalibrationOverlay();
  }
  sendEvent('viewport_changed', {
    width: window.innerWidth,
    height: window.innerHeight,
  });
};

const handleInput = (event) => {
  const target = event.target;
  sendEvent('text_input_metadata', {
    ...getElementPayload(target),
    input_type: target?.type || null,
    value_length: typeof target?.value === 'string' ? target.value.length : null,
  });
};

const handleMouseMove = () => {
  trainingSampleCount += 1;
};

const bindListeners = () => {
  if (listenersBound) return;
  listenersBound = true;

  document.addEventListener('click', handleClick, true);
  document.addEventListener('pointerdown', handlePointerDown, true);
  document.addEventListener('input', handleInput, true);
  document.addEventListener('mousemove', handleMouseMove, true);
  window.addEventListener('scroll', handleScroll, { passive: true });
  window.addEventListener('resize', handleResize);
  window.addEventListener('pagehide', flushRrweb);

  routeObserver = new MutationObserver(() => {
    if (window.location.href === currentUrl) return;
    const previousUrl = currentUrl;
    currentUrl = window.location.href;
    sendEvent('route_changed', {
      from: previousUrl,
      to: currentUrl,
    });
  });
  routeObserver.observe(document, { subtree: true, childList: true });
};

const applyState = async (state) => {
  trackerState = {
    trackingEnabled: Boolean(state.trackingEnabled),
    captureGaze: state.captureGaze !== false,
    sessionId: state.sessionId || null,
  };

  if (trackerState.trackingEnabled) {
    reportDiagnostic('tracking_enabled', {
      captureGaze: trackerState.captureGaze,
      url: window.location.href,
    });
    startRrweb();
    await startGazeTracking();
    updateGazeState();
    sendEvent('viewport_changed', {
      width: window.innerWidth,
      height: window.innerHeight,
      source: SOURCE,
    });
  } else {
    reportDiagnostic('tracking_disabled', {
      url: window.location.href,
    });
    stopRrweb();
    updateGazeState();
  }
};

const initialize = async () => {
  if (initialized) return;
  initialized = true;
  bindListeners();
  reportDiagnostic('content_initialized', {
    url: window.location.href,
  });

  const response = await chrome.runtime.sendMessage({ type: 'GET_STATUS' });
  if (response?.ok) {
    reportDiagnostic('status_received', {
      trackingEnabled: Boolean(response.trackingEnabled),
      captureGaze: response.captureGaze !== false,
    });
    await applyState(response);
  }
};

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === 'TRACKING_STATE') {
    applyState(message.state).catch(() => {});
  }
});

initialize().catch(() => {});
}
