# Event Schema

## Session creation

`POST /api/sessions`

```json
{
  "session_id": "sess_123",
  "source": "frontend_tracker",
  "started_at": "2026-04-26T10:00:00.000Z",
  "metadata": {
    "initial_url": "https://example.com",
    "viewport": {
      "width": 1440,
      "height": 900
    }
  }
}
```

## Event ingestion

`POST /api/events`

Supports either one event or a batch:

```json
{
  "events": [
    {
      "session_id": "sess_123",
      "source": "browser_extension",
      "event_type": "mouse_click",
      "timestamp": "2026-04-26T10:00:01.000Z",
      "sequence": 7,
      "context": {
        "url": "https://example.com/checkout",
        "title": "Checkout",
        "viewport": {
          "width": 1440,
          "height": 900
        },
        "tab_id": 101
      },
      "payload": {
        "x": 812,
        "y": 533,
        "button": 0,
        "tag_name": "button",
        "id": "submit-order",
        "path": "form > button#submit-order"
      }
    }
  ]
}
```

If `sequence` is omitted, the API assigns one for that session before queueing.

## rrweb ingestion

`POST /api/rrweb`

```json
{
  "session_id": "sess_123",
  "source": "frontend_tracker",
  "timestamp": "2026-04-26T10:00:05.000Z",
  "context": {
    "url": "https://example.com/checkout",
    "title": "Checkout",
    "viewport": {
      "width": 1440,
      "height": 900
    }
  },
  "events": [
    {
      "type": 2,
      "timestamp": 1777197605000
    }
  ]
}
```

## Timeline replay data

`GET /api/sessions/{session_id}/timeline`

Returns one normalized timeline for replay/export clients. It combines:

- raw event log entries
- overlay events such as `gaze_point`, `cursor_position`, `mouse_click`, `gaze_cursor_distance`, and `gaze_fixation`
- `friction_marker` entries
- rrweb chunk metadata
- screen recording chunk metadata

Each timeline item includes:

- `kind`
- `timestamp`
- `offset_ms`
- `source`
- `context`
- type-specific fields and payload

## Context fields

The shared context model currently accepts:

- `app_name`
- `window_title`
- `url`
- `title`
- `viewport.width`
- `viewport.height`
- `tab_id`

Additional fields are allowed and preserved.

## Shared gaze contract

Both the desktop agent and browser webcam tracker should emit these common gaze payload fields:

- `gaze_contract_version`
- `provider`
- `provider_type`
- `sample_interval_ms`

`gaze_point` should also include:

- `screen_x`
- `screen_y`
- `normalized_x`
- `normalized_y`
- `confidence`
- `confidence_threshold`

`gaze_fixation` should also include:

- `duration_ms`
- `fixation_min_duration_ms`
- element descriptor fields such as `tag_name`, `id`, and `path` when available

`gaze_lost` should also include:

- `reason`
- `lost_timeout_ms` when timeout-based

`gaze_provider_status` should include:

- `status`
- optional `message` or provider-specific diagnostics

## Local gaze bridge

The desktop agent now exposes a local bridge for browser consumers:

- `GET http://127.0.0.1:8790/health`
- `GET http://127.0.0.1:8790/gaze/latest`
- `GET http://127.0.0.1:8790/machine-profile`
- `GET http://127.0.0.1:8790/calibration/status`
- `POST http://127.0.0.1:8790/calibration/start`
- `POST http://127.0.0.1:8790/calibration/sample`
- `WS  ws://127.0.0.1:8790/ws/gaze`

The browser tracker should prefer this local bridge over running its own webcam tracker when the agent is available.

## Required event groups in current codebase

Currently implemented or partially implemented:

- `session_started`
- `session_stopped`
- `calibration_started`
- `calibration_completed`
- `mouse_move`
- `cursor_position`
- `mouse_click`
- `mouse_up`
- `scroll`
- `key_input`
- `text_input_metadata`
- `gaze_point`
- `gaze_fixation`
- `gaze_lost`
- `gaze_provider_status`
- `active_window_changed`
- `route_changed`
- `viewport_changed`
- `gaze_cursor_distance`
- `friction_marker`

## Gaze-to-cursor live metric

The desktop agent actively emits `cursor_position` samples at a fixed interval.
The RabbitMQ worker pairs the latest `gaze_point` with the latest cursor sample and writes:

- raw derived `gaze_cursor_distance` events to the session event log
- sample rows to `gaze_cursor_samples`
- rolling aggregates to `gaze_cursor_session_metrics`

`gaze_cursor_distance` payload fields:

- `gaze_x`, `gaze_y`
- `cursor_x`, `cursor_y`
- `distance_px`
- `gaze_age_ms`
- `cursor_age_ms`
- `clarity_signal`: `close`, `medium`, or `far`

## Live friction markers

The RabbitMQ worker emits `friction_marker` events when it detects usability friction from the live event stream.
For desktop sessions, the desktop agent also emits live `gaze_cursor_distance` and `friction_marker`
events locally so the desktop log window can surface these measures immediately. The worker stores
desktop-emitted gaze/cursor samples in PostgreSQL and avoids duplicating desktop-derived markers.

Currently emitted marker types:

- `rage_click`: repeated clicks in a small screen area within a short time window
- `click_without_recent_gaze`: click is far from the latest gaze point

Common payload fields:

- `marker_type`
- `severity`
- `screen_x`, `screen_y`
- `reason`

## Task and note markers

The browser extension popup can emit study/task annotations while tracking is active:

- `task_started`
- `task_completed`
- `note_added`

These markers use the same event ingestion path and retry queue as regular browser extension events.
The payload includes `source_ui` and optional fields such as `label` or `note`.

Task payload fields:

- `task_id`: stable identifier generated by the extension background worker
- `label`: human-readable task name from the popup
- `completion_rule`: optional rule saved on `task_started`
- `completion_source`: `manual` or `auto_rule` on `task_completed`
- `matched_rule`, `matched_value`: populated when a content-script rule completed the task
- `started_at`: timestamp copied from the active task when available

Supported automatic completion rules in the web extension:

- `manual`: no automatic completion, user clicks `Task done`
- `url_contains`: completes when `window.location.href` contains the configured value
- `selector_exists`: completes when `document.querySelector(value)` matches
- `text_contains`: completes when visible page text contains the configured value

Planned but not fully implemented yet:

- `mouse_down`
- `hotkey`
- `gaze_saccade`
- `dom_snapshot_chunk`
- `screen_frame`
