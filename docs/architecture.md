# Architecture

## Current implementation status

The repository now has the Phase 1 foundation for a unified usability tracking stack:

- `main.py`
  - FastAPI API with explicit session, event, rrweb, screen recording, replay, timeline, and metrics routes.
  - Shared request models imported from `event_models.py`.
  - Batched `POST /api/events` ingestion for browser and desktop producers.
- `worker.py`
  - RabbitMQ consumer persisting normalized events and rrweb chunks into append-only session files.
- `frontend-tracker/`
  - Browser PoC for rrweb capture and webcam gaze capture.
  - Browser interaction events now flush in batches to the shared event API.
- `ux-test-platform/`
  - Browser extension with rrweb and gaze capture.
  - Background transport now batches unified events before upload.
- `desktop_agent.py`
  - Desktop MVP for active window, mouse, scroll, keyboard metadata, and pluggable gaze provider heartbeats.

## Runtime flow

1. A producer creates or reuses a `session_id`.
2. The producer sends `POST /api/sessions`.
3. The producer submits normalized events to `POST /api/events`.
4. rrweb chunks are submitted to `POST /api/rrweb`.
5. Screen recording chunks are submitted to `POST /api/screen-recording`.
6. The API pushes event and rrweb payloads into RabbitMQ.
7. `worker.py` persists raw session artifacts under `recorded_sessions/<session_id>/`.
8. Replay, timeline, and metrics endpoints read those persisted artifacts.

## Storage layout in dev

Each session currently writes to local filesystem storage:

- `recorded_sessions/<session_id>/session.json`
- `recorded_sessions/<session_id>/events.jsonl`
- `recorded_sessions/<session_id>/dom_recording.jsonl`
- `recorded_sessions/<session_id>/screen_recording.jsonl`
- `recorded_sessions/<session_id>/screen_recording.webm`

This remains file-based for dev, while the plan still calls for PostgreSQL metadata later.

## Producer contract

All producers should emit the same top-level event shape:

- `session_id`
- `source`
- `event_type`
- `timestamp`
- `sequence`
- `context`
- `payload`

The API is responsible for normalizing missing sequence numbers before queueing.

## Known gaps versus the plan

- Storage is still filesystem-first rather than PostgreSQL-backed.
- The desktop agent is Python-based MVP rather than Electron.
- Cross-source correlation is available in metrics and timeline overlay data, but a full visual replay UI is not implemented here.
- Setup automation scripts and installer flow are still missing.
- There is no dedicated shared package consumed by both Python and JS yet; the shared contract is aligned logically, but not generated from one source artifact.
