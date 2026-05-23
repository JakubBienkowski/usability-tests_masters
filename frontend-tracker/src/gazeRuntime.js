export const GAZE_CONTRACT_VERSION = '1.0';
export const GAZE_SAMPLE_INTERVAL_MS = 200;
export const GAZE_FIXATION_MIN_DURATION_MS = 500;
export const GAZE_CONFIDENCE_THRESHOLD = 0.35;
export const GAZE_LOST_TIMEOUT_MS = 1000;

export const GAZE_PROVIDER = {
  name: 'webgazer',
  type: 'browser_webcam',
  sampleIntervalMs: GAZE_SAMPLE_INTERVAL_MS,
};

export const getElementDescriptor = (element) => {
  if (!(element instanceof Element)) {
    return {
      tag_name: null,
      id: null,
      path: null,
      text: null,
    };
  }

  const path = [];
  let current = element;

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

  return {
    tag_name: element.tagName.toLowerCase(),
    id: element.id || null,
    path: path.join(' > '),
    text: element.innerText?.substring(0, 80) || null,
  };
};

const providerFields = () => ({
  gaze_contract_version: GAZE_CONTRACT_VERSION,
  provider: GAZE_PROVIDER.name,
  provider_type: GAZE_PROVIDER.type,
  sample_interval_ms: GAZE_PROVIDER.sampleIntervalMs,
});

export const buildGazeStatusPayload = (status, extra = {}) => ({
  ...providerFields(),
  status,
  ...extra,
});

export const buildGazePointPayload = (x, y, confidence, extra = {}) => ({
  ...providerFields(),
  screen_x: Math.round(x),
  screen_y: Math.round(y),
  normalized_x: Number((x / Math.max(window.innerWidth, 1)).toFixed(6)),
  normalized_y: Number((y / Math.max(window.innerHeight, 1)).toFixed(6)),
  confidence: typeof confidence === 'number' ? confidence : null,
  confidence_threshold: GAZE_CONFIDENCE_THRESHOLD,
  viewport: {
    width: window.innerWidth,
    height: window.innerHeight,
  },
  ...extra,
});

export const buildGazeLostPayload = (reason, extra = {}) => ({
  ...providerFields(),
  reason,
  lost_timeout_ms: GAZE_LOST_TIMEOUT_MS,
  ...extra,
});

export const buildGazeFixationPayload = (element, durationMs, extra = {}) => ({
  ...providerFields(),
  ...getElementDescriptor(element),
  duration_ms: durationMs,
  fixation_min_duration_ms: GAZE_FIXATION_MIN_DURATION_MS,
  ...extra,
});
