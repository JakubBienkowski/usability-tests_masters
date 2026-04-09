# Usability Testing Platform Enhancement Plan

## 1. Goal

Build this project into a single usability testing platform that can:

- track gaze from webcam inside the browser,
- track usability activity outside the browser in desktop applications,
- correlate eye position with mouse position, clicks, scrolling, typing, and screen context,
- install required components in one setup flow,
- run backend, worker, frontend, browser extension, and desktop agent as one coherent system.

This document is the execution plan to follow while building the app.

## 2. Current State Summary

The repository already contains useful PoC pieces:

- `main.py`: FastAPI WebSocket ingestion to RabbitMQ.
- `worker.py`: async consumer persisting session events.
- `frontend-tracker/`: React app with webcam gaze tracking via `webgazer` and page event tracking.
- `ux-test-platform/`: browser extension scaffold with rrweb recording.
- `docker-compose.yml`: queue, API, and worker containers.

Main gaps:

- ingestion contract is inconsistent between frontend, extension, and backend,
- backend routes used by the frontend do not match the API currently implemented,
- no desktop-native tracking agent exists yet,
- no shared session model across browser and desktop sources,
- no unified installer or bootstrap command,
- metrics are stored as raw events only, without derived usability analytics.

## 3. Product Scope

### In scope

- Browser session recording.
- Webcam-based gaze estimation in browser.
- Desktop session recording outside the browser.
- Unified event schema for browser, extension, and desktop agent.
- Derived usability metrics and reports.
- One-command local setup for development.
- Installer flow for extension plus desktop agent.

### Out of scope for v1

- Clinical-grade eye tracking accuracy.
- Cross-device cloud synchronization.
- Mobile app tracking.
- Production hardening for enterprise rollout.

## 4. Target Architecture

### 4.1 Core components

1. `api-service`
   - FastAPI app.
   - Receives sessions, events, media metadata, calibration data, and derived metrics requests.
   - Exposes REST endpoints and WebSocket endpoints.

2. `event-worker`
   - Normalizes and validates raw events.
   - Persists events into storage.
   - Computes derived metrics asynchronously.

3. `frontend-dashboard`
   - React app for session control, calibration, live monitoring, and replay.

4. `browser-extension`
   - Injects content script into websites.
   - Captures DOM events, rrweb events, scroll, click, hover, viewport, and active tab metadata.
   - Coordinates with local desktop agent when needed.

5. `desktop-agent`
   - Native app running on the tester machine.
   - Captures active window, cursor position, keyboard metadata, screenshots or video frames, and webcam gaze stream.
   - Sends normalized events to the same backend.

6. `analytics-service`
   - Can initially live in the worker.
   - Produces heatmaps, fixation summaries, gaze-to-cursor correlation, hesitation metrics, and task completion indicators.

### 4.2 Recommended technical split

- Backend: FastAPI + Pydantic + PostgreSQL.
- Queue/background jobs: RabbitMQ already exists; keep it for asynchronous processing.
- Raw blob storage: local filesystem in dev, S3-compatible storage later.
- Frontend: existing React/Vite app.
- Browser extension: keep `ux-test-platform/` and convert it into the main browser capture client.
- Desktop agent:
  - Recommended: Electron for fastest integration with JS/TS stack and desktop packaging.
  - Alternative: Python desktop agent if webcam/computer-vision stack is easier there.

Recommendation: use Electron for the desktop agent and keep Python for backend analytics. That keeps browser extension and desktop client close in technology, while Python handles event processing and computer-vision support where needed.

## 5. Unified Session Model

Every recording should belong to a single `study_session`.

### 5.1 Main entities

- `study`
- `participant`
- `study_session`
- `capture_source`
  - `browser_extension`
  - `browser_webcam`
  - `desktop_agent`
- `event`
- `media_asset`
- `metric_snapshot`
- `task_marker`

### 5.2 Session identity rules

- One global `session_id` per test run.
- One `source_id` per producer.
- All timestamps stored in UTC ISO 8601 plus monotonic local offsets where possible.
- Desktop agent is the authority for machine-level time sync when both browser and desktop are active.

## 6. Event Schema

Introduce one normalized event contract used by all producers.

```json
{
  "session_id": "sess_123",
  "source": "desktop_agent",
  "event_type": "gaze_point",
  "timestamp": "2026-04-07T12:00:00.000Z",
  "sequence": 42,
  "context": {
    "app_name": "Chrome",
    "window_title": "Checkout",
    "url": "https://example.com/checkout"
  },
  "payload": {
    "screen_x": 1200,
    "screen_y": 540,
    "confidence": 0.81
  }
}
```

### 6.1 Required event groups

- Session lifecycle
  - `session_started`
  - `session_stopped`
  - `calibration_started`
  - `calibration_completed`
- Mouse
  - `mouse_move`
  - `mouse_click`
  - `mouse_down`
  - `mouse_up`
  - `scroll`
- Keyboard
  - `key_input`
  - `hotkey`
  - `text_input_metadata`
- Gaze
  - `gaze_point`
  - `gaze_fixation`
  - `gaze_saccade`
  - `gaze_lost`
- Screen and DOM
  - `dom_snapshot_chunk`
  - `screen_frame`
  - `active_window_changed`
  - `route_changed`
  - `viewport_changed`
- Study markers
  - `task_started`
  - `task_completed`
  - `friction_marker`
  - `note_added`

## 7. Tracking Capabilities to Build

### 7.1 Browser tracking

- Keep rrweb recording.
- Fix content-script and background message contract.
- Add stable batching, retry, compression, and offline buffering.
- Add browser-side calibration UI for gaze.
- Track viewport size, DOM target selector, route changes, and form interaction timing.

### 7.2 Webcam gaze tracking in browser

- Keep `webgazer` only as a short-term PoC.
- Wrap gaze provider behind an interface so it can be replaced later.
- Store raw gaze points and derived fixations separately.
- Capture calibration quality score.
- Add confidence thresholding and smoothing.

### 7.3 Desktop tracking outside the browser

Implement a native desktop agent that captures:

- active application name,
- active window title,
- global mouse position,
- mouse clicks and scroll,
- keyboard activity metadata,
- screenshot stream or low-FPS video frames,
- webcam gaze stream,
- monitor geometry and DPI scaling.

Recommended desktop-agent modules:

- `capture/window-tracker`
- `capture/input-tracker`
- `capture/screen-recorder`
- `capture/webcam-gaze`
- `transport/uploader`
- `session/local-buffer`

### 7.4 Browser + desktop coordination

- When the active window is a supported browser, correlate desktop cursor coordinates with browser viewport coordinates.
- If extension is installed, enrich browser windows with DOM selectors and rrweb snapshots.
- If extension is not installed, desktop agent still records app/window/screen interactions, but with reduced semantic detail.

## 8. Usability Metrics to Compute

The app should not only store raw events. It must compute metrics that matter for usability studies.

### 8.1 Core metrics

- gaze-to-cursor distance over time,
- gaze-to-click latency,
- fixation duration per UI element,
- first fixation time on target,
- time to first click,
- hesitation time before action,
- rage clicks,
- dead clicks,
- scroll depth and scroll velocity,
- form field dwell time,
- backtracking frequency,
- task completion time,
- task abandonment rate,
- navigation loops,
- attention ratio on primary CTA versus surrounding UI.

### 8.2 Correlation metrics

- correlation between gaze point and mouse point,
- correlation between gaze fixation and click target,
- lag between visual attention and action,
- mismatch between intended target area and actual cursor trajectory,
- repeated fixation without action,
- click without prior fixation.

### 8.3 Suggested derived outputs

- session summary JSON,
- replay overlay with gaze and cursor,
- heatmaps for gaze and cursor,
- per-element attention table,
- friction event timeline,
- exportable CSV for studies.

## 9. Data Pipeline Plan

### Phase A: raw ingestion

- Standardize all producers on one API contract.
- Replace ad hoc `/api/track` and `/api/record` assumptions with explicit backend routes.
- Persist raw events in append-only storage.

### Phase B: normalization

- Validate with Pydantic models.
- Add sequence numbers and server receive time.
- Enrich events with session metadata and source metadata.

### Phase C: analytics

- Run fixation detection and gaze smoothing.
- Build mouse-gaze correlation processor.
- Generate aggregated metrics per session and per task.

### Phase D: replay

- Reconstruct browser replay from rrweb.
- Overlay gaze, cursor, clicks, and task markers.
- Add desktop replay using screenshots or video frames plus cursor and gaze overlay.

## 10. One-Command Setup Strategy

The project should install and start from one entry point.

### 10.1 Developer bootstrap

Add a root bootstrap command such as:

```bash
./scripts/dev-setup.sh
```

This script should:

1. create Python virtual environment if missing,
2. install Python dependencies,
3. install root and frontend npm dependencies,
4. install extension dependencies,
5. install desktop-agent dependencies,
6. start Docker services for database, queue, and backend dependencies,
7. run DB migrations,
8. print exact URLs and next actions.

### 10.2 Developer run command

Add:

```bash
./scripts/dev-run.sh
```

This script should start:

- API,
- worker,
- frontend dashboard,
- extension dev build watcher,
- desktop agent in dev mode.

### 10.3 One-shot installer for end users

Create an installer bundle that:

- installs desktop agent,
- installs or guides installation of the browser extension,
- writes local config,
- checks webcam and screen-recording permissions,
- connects to the configured backend,
- launches a calibration wizard.

For v1, this can be a local installer plus setup wizard. Full silent installation can come later.

## 11. Recommended Repository Restructure

Move toward a clearer monorepo layout:

```text
/apps
  /api
  /worker
  /dashboard
  /browser-extension
  /desktop-agent
/packages
  /event-schema
  /analytics-core
  /shared-ui
/scripts
/infra
/docs
```

### Migration mapping from current repo

- `main.py` -> `apps/api/`
- `worker.py` -> `apps/worker/`
- `frontend-tracker/` -> split between `apps/dashboard/` and shared capture logic
- `ux-test-platform/` -> `apps/browser-extension/`
- `docker-compose.yml` -> `infra/docker-compose.yml`

## 12. Phased Delivery Plan

### Phase 1: Stabilize current PoC

- Fix backend API routes to match frontend usage.
- Introduce shared event schema.
- Unify session creation and persistence.
- Fix browser extension event batching and rrweb upload.
- Remove broken references and runtime errors in current code.

Exit criteria:

- browser capture works reliably,
- webcam gaze events reach backend,
- rrweb chunks are stored consistently,
- sessions can be replayed from one session identifier.

### Phase 2: Build desktop agent MVP

- Create Electron app with local tray control.
- Add global mouse and keyboard tracking metadata.
- Add active-window detection.
- Add screenshot capture at controlled FPS.
- Add webcam gaze collection using pluggable provider.
- Send all events to backend using same schema.

Exit criteria:

- desktop activity outside browser is recorded,
- mouse/gaze/screen timestamps are aligned,
- session replay shows desktop timeline with overlays.

### Phase 3: Cross-source correlation

- Merge browser and desktop streams by session and time.
- Map browser viewport coordinates into desktop screen coordinates.
- Generate gaze-to-cursor correlation metrics.
- Add element-level fixation summaries.

Exit criteria:

- analytics can report correlation and lag metrics,
- replay can switch between browser and desktop contexts,
- summaries identify friction hotspots.

### Phase 4: Setup automation

- Add bootstrap scripts.
- Add config templates.
- Package extension and desktop agent.
- Build setup wizard.

Exit criteria:

- new developer can start full stack from one documented flow,
- test participant machine can be prepared with minimal manual steps.

### Phase 5: Study workflow and reporting

- Add study creation and participant assignment.
- Add session dashboard and exports.
- Add annotations and task markers.
- Add report generation.

Exit criteria:

- researcher can run, review, and export a complete study session.

## 13. Privacy and Consent Requirements

This app processes sensitive behavioral and possibly biometric data. Build privacy into v1.

- require explicit participant consent before recording,
- show active recording indicator,
- allow pause and stop at all times,
- avoid storing raw keystrokes by default,
- redact sensitive fields and password inputs,
- allow screenshot exclusion zones,
- store retention policy in config,
- separate participant identity from recording data where possible.

## 14. Testing Strategy

### Automated

- schema validation tests,
- API contract tests,
- worker processing tests,
- analytics unit tests,
- replay synchronization tests,
- extension message flow tests,
- desktop-agent integration smoke tests.

### Manual

- webcam permission flow,
- browser extension install flow,
- multi-monitor coordinate mapping,
- browser + desktop concurrent session,
- degraded mode without extension,
- degraded mode without webcam,
- recovery after network interruption.

## 15. Immediate Code Changes to Prioritize

1. Create explicit FastAPI routes:
   - `POST /api/sessions`
   - `POST /api/events`
   - `POST /api/rrweb`
   - `GET /api/sessions/{id}`
   - `GET /api/sessions/{id}/metrics`

2. Move event payload definitions into shared models.

3. Fix current frontend tracker bugs:
   - broken `target` reference in click handler,
   - inconsistent API route usage,
   - incomplete cleanup,
   - weak batching and error handling.

4. Fix extension bugs:
   - incorrect CSS path return,
   - inconsistent payload naming,
   - lack of retry and flush on unload.

5. Add a proper storage layer:
   - start with PostgreSQL for metadata,
   - keep raw event files for large payloads in dev.

6. Introduce `docs/architecture.md` and `docs/event-schema.md` after this plan is approved.

## 16. Recommended Implementation Order

1. Stabilize backend contracts.
2. Make browser capture reliable.
3. Add shared schema package.
4. Build session dashboard and replay.
5. Build desktop agent MVP.
6. Add cross-source correlation analytics.
7. Add one-command setup and installer flow.
8. Add study/reporting features.

## 17. Definition of Done for the App

The app is considered ready for a usable v1 when:

- a researcher can install the required components from one guided flow,
- browser activity and desktop activity can be recorded under one session,
- webcam gaze works with calibration and confidence scoring,
- mouse and gaze correlation metrics are computed automatically,
- replay shows screen context, cursor, gaze, and key usability markers,
- privacy controls are enabled by default,
- a session summary can be exported after the test.

## 18. Next Document to Create After This Plan

After following this plan, the next implementation documents should be:

1. `docs/architecture.md`
2. `docs/event-schema.md`
3. `docs/setup-flow.md`
4. `docs/desktop-agent-design.md`
5. `docs/analytics-metrics.md`
