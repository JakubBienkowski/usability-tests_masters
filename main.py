import base64
import json
import os
from collections import Counter
from datetime import datetime, timezone
from math import hypot
from pathlib import Path
from statistics import median
from typing import Any

import aio_pika
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from db import get_gaze_cursor_metrics
from db import get_session as db_get_session
from db import init_db, list_sessions as db_list_sessions, upsert_session
from event_models import EventBatchIn, EventIn, RrwebChunkIn, ScreenRecordingChunkIn, SessionCreate


RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq/")
BASE_DIR = Path(os.getenv("RECORDED_SESSIONS_DIR", "recorded_sessions"))
EVENTS_FILE = "events.jsonl"
RRWEB_FILE = "dom_recording.jsonl"
SCREEN_RECORDING_FILE = "screen_recording.jsonl"
SESSION_FILE = "session.json"

app = FastAPI(title="UX Tracking API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event() -> None:
    init_db()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def session_path(session_id: str) -> Path:
    return BASE_DIR / session_id


def ensure_session_dir(session_id: str) -> Path:
    path = session_path(session_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_file_path(session_id: str) -> Path:
    return session_path(session_id) / SESSION_FILE


def write_session_metadata(session_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
    ensure_session_dir(session_id)
    target = session_file_path(session_id)
    current = {}
    if target.exists():
        current = json.loads(target.read_text())
    current.update(metadata)
    target.write_text(json.dumps(current, ensure_ascii=True, indent=2))
    return current


def load_session_metadata(session_id: str) -> dict[str, Any]:
    db_session = db_get_session(session_id)
    if db_session:
        return db_session
    target = session_file_path(session_id)
    if not target.exists():
        return {}
    return json.loads(target.read_text())


def persist_session_metadata(session_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
    current = write_session_metadata(session_id, metadata)
    upsert_session(
        session_id=session_id,
        source=current.get("source", "unknown"),
        started_at=parse_timestamp(current.get("started_at")) or now_utc(),
        updated_at=parse_timestamp(current.get("updated_at")) or now_utc(),
        next_sequence=int(current.get("next_sequence", 1)),
        metadata=current.get("metadata", {}),
    )
    return current


def load_json_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    rows: list[dict[str, Any]] = []
    with path.open() as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def parse_timestamp(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def duration_ms(start: datetime | None, end: datetime | None) -> float | None:
    if not start or not end:
        return None
    return max((end - start).total_seconds() * 1000, 0.0)


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def timestamp_sort_value(value: str | None) -> float:
    parsed = parse_timestamp(value)
    return parsed.timestamp() if parsed else 0.0


def event_offset_ms(timestamp: str | None, start: datetime | None) -> float | None:
    parsed = parse_timestamp(timestamp)
    if not parsed or not start:
        return None
    return round(duration_ms(start, parsed) or 0, 2)


def session_sort_key(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


async def push_to_queue(data: dict[str, Any]) -> None:
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    async with connection:
        channel = await connection.channel()
        await channel.default_exchange.publish(
            aio_pika.Message(body=json.dumps(data).encode()),
            routing_key="ux_events",
        )


async def push_many_to_queue(items: list[dict[str, Any]]) -> None:
    if not items:
        return

    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    async with connection:
        channel = await connection.channel()
        for item in items:
            await channel.default_exchange.publish(
                aio_pika.Message(body=json.dumps(item).encode()),
                routing_key="ux_events",
            )


def allocate_sequences(session_id: str, events: list[EventIn]) -> list[int]:
    metadata = load_session_metadata(session_id)
    next_sequence = metadata.get("next_sequence", 1)
    assigned_sequences: list[int] = []

    for event in events:
        if event.sequence is not None:
            assigned_sequences.append(event.sequence)
            next_sequence = max(next_sequence, event.sequence + 1)
            continue
        assigned_sequences.append(next_sequence)
        next_sequence += 1

    persist_session_metadata(
        session_id,
        {
            "updated_at": now_iso(),
            "next_sequence": next_sequence,
        },
    )
    return assigned_sequences


def normalize_event(event: EventIn, sequence: int | None = None) -> dict[str, Any]:
    return {
        "session_id": event.session_id,
        "source": event.source,
        "event_type": event.event_type,
        "timestamp": event.timestamp or now_iso(),
        "received_at": now_iso(),
        "sequence": sequence,
        "context": event.context.model_dump(exclude_none=True),
        "payload": event.payload,
    }


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok", "timestamp": now_iso()}


@app.post("/api/sessions")
async def create_session(body: SessionCreate) -> dict[str, Any]:
    existing = load_session_metadata(body.session_id)
    metadata = persist_session_metadata(
        body.session_id,
        {
            "session_id": body.session_id,
            "source": body.source,
            "started_at": existing.get("started_at") or body.started_at or now_iso(),
            "updated_at": now_iso(),
            "next_sequence": existing.get("next_sequence", 1),
            "metadata": {
                **existing.get("metadata", {}),
                **body.metadata,
            },
        },
    )
    if not existing:
        await push_to_queue(
            {
                "kind": "event",
                "event": {
                    "session_id": body.session_id,
                    "source": body.source,
                    "event_type": "session_started",
                    "timestamp": body.started_at or now_iso(),
                    "received_at": now_iso(),
                    "sequence": 0,
                    "context": {},
                    "payload": body.metadata,
                },
            }
        )
    return {"ok": True, "session": metadata}


@app.post("/api/events")
async def create_events(body: EventIn | EventBatchIn) -> dict[str, Any]:
    incoming_events = [body] if isinstance(body, EventIn) else body.events
    if not incoming_events:
        return {"ok": True, "events_received": 0}

    session_ids = {item.session_id for item in incoming_events}
    if len(session_ids) != 1:
        raise HTTPException(status_code=400, detail="All events in a batch must share one session_id")

    session_id = incoming_events[0].session_id
    ensure_session_dir(session_id)
    sequences = allocate_sequences(session_id, incoming_events)
    normalized_events = [
        normalize_event(event, sequence)
        for event, sequence in zip(incoming_events, sequences, strict=False)
    ]
    await push_many_to_queue([{"kind": "event", "event": event} for event in normalized_events])
    return {"ok": True, "events_received": len(normalized_events)}


@app.post("/api/rrweb")
async def create_rrweb_chunk(body: RrwebChunkIn) -> dict[str, Any]:
    ensure_session_dir(body.session_id)
    payload = {
        "kind": "rrweb",
        "session_id": body.session_id,
        "source": body.source,
        "timestamp": body.timestamp or now_iso(),
        "received_at": now_iso(),
        "context": body.context.model_dump(exclude_none=True),
        "events": body.events,
    }
    persist_session_metadata(body.session_id, {"updated_at": now_iso()})
    await push_to_queue(payload)
    return {"ok": True, "events_received": len(body.events)}


@app.post("/api/screen-recording")
async def create_screen_recording_chunk(body: ScreenRecordingChunkIn) -> dict[str, Any]:
    session_dir = ensure_session_dir(body.session_id)
    try:
        chunk_bytes = base64.b64decode(body.data_base64, validate=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid screen recording chunk") from exc

    extension = "webm" if "webm" in body.mime_type else "bin"
    chunk_name = f"screen_{body.chunk_index:06d}.{extension}"
    recording_name = f"screen_recording.{extension}"
    chunk_path = session_dir / chunk_name
    recording_path = session_dir / recording_name
    chunk_path.write_bytes(chunk_bytes)
    with recording_path.open("wb" if body.chunk_index == 0 else "ab") as handle:
        handle.write(chunk_bytes)

    row = {
        "timestamp": body.timestamp or now_iso(),
        "received_at": now_iso(),
        "source": body.source,
        "context": body.context.model_dump(exclude_none=True),
        "chunk_index": body.chunk_index,
        "mime_type": body.mime_type,
        "filename": chunk_name,
        "recording_filename": recording_name,
        "size_bytes": len(chunk_bytes),
        "final": body.final,
    }
    with (session_dir / SCREEN_RECORDING_FILE).open("a") as handle:
        handle.write(json.dumps(row, ensure_ascii=True) + "\n")

    persist_session_metadata(body.session_id, {"updated_at": now_iso()})
    return {"ok": True, "chunk_index": body.chunk_index, "size_bytes": len(chunk_bytes)}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    metadata = load_session_metadata(session_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Session not found")

    events = load_json_lines(session_path(session_id) / EVENTS_FILE)
    rrweb_rows = load_json_lines(session_path(session_id) / RRWEB_FILE)
    return {
        "session": metadata,
        "event_count": len(events),
        "rrweb_chunks": len(rrweb_rows),
    }


@app.get("/api/sessions")
async def list_sessions() -> dict[str, Any]:
    items = db_list_sessions()
    if not items:
        BASE_DIR.mkdir(parents=True, exist_ok=True)
        items = []
        for path in sorted(BASE_DIR.iterdir(), key=session_sort_key, reverse=True):
            if not path.is_dir():
                continue
            metadata_path = path / SESSION_FILE
            metadata = {"session_id": path.name}
            if metadata_path.exists():
                metadata = json.loads(metadata_path.read_text())
            items.append(metadata)
    return {"sessions": items}


@app.get("/api/sessions/{session_id}/metrics")
async def get_session_metrics(session_id: str) -> dict[str, Any]:
    metadata = load_session_metadata(session_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Session not found")

    events = load_json_lines(session_path(session_id) / EVENTS_FILE)
    rrweb_rows = load_json_lines(session_path(session_id) / RRWEB_FILE)

    counts = Counter(event.get("event_type", "unknown") for event in events)
    events.sort(key=lambda event: event.get("timestamp", ""))
    gaze_fixations = [event for event in events if event.get("event_type") == "gaze_fixation"]
    gaze_points = [event for event in events if event.get("event_type") == "gaze_point"]
    mouse_clicks = [event for event in events if event.get("event_type") == "mouse_click"]
    gaze_cursor_events = [
        event for event in events if event.get("event_type") == "gaze_cursor_distance"
    ]
    friction_markers = [event for event in events if event.get("event_type") == "friction_marker"]
    task_started = [event for event in events if event.get("event_type") == "task_started"]
    task_completed = [event for event in events if event.get("event_type") == "task_completed"]
    notes = [event for event in events if event.get("event_type") == "note_added"]
    calibration_started = [
        event for event in events if event.get("event_type") == "calibration_started"
    ]
    calibration_completed = [
        event for event in events if event.get("event_type") == "calibration_completed"
    ]
    fixation_durations = [
        event.get("payload", {}).get("duration_ms", 0)
        for event in gaze_fixations
        if isinstance(event.get("payload", {}).get("duration_ms"), (int, float))
    ]

    gaze_coordinates: list[tuple[datetime, float, float]] = []
    for event in gaze_points:
        payload = event.get("payload", {})
        timestamp = parse_timestamp(event.get("timestamp"))
        x = payload.get("screen_x")
        y = payload.get("screen_y")
        if timestamp and isinstance(x, (int, float)) and isinstance(y, (int, float)):
            gaze_coordinates.append((timestamp, float(x), float(y)))

    click_coordinates: list[tuple[datetime, float, float]] = []
    for event in mouse_clicks:
        payload = event.get("payload", {})
        timestamp = parse_timestamp(event.get("timestamp"))
        x = payload.get("x", payload.get("screen_x"))
        y = payload.get("y", payload.get("screen_y"))
        if timestamp and isinstance(x, (int, float)) and isinstance(y, (int, float)):
            click_coordinates.append((timestamp, float(x), float(y)))

    gaze_path_segments: list[float] = []
    gaze_point_intervals_ms: list[float] = []
    gaze_saccade_estimates = 0
    for index in range(1, len(gaze_coordinates)):
        previous_time, previous_x, previous_y = gaze_coordinates[index - 1]
        current_time, current_x, current_y = gaze_coordinates[index]
        step_distance = hypot(current_x - previous_x, current_y - previous_y)
        interval = duration_ms(previous_time, current_time)
        if interval is None:
            continue
        gaze_path_segments.append(step_distance)
        gaze_point_intervals_ms.append(interval)
        if interval <= 120 and step_distance >= 80:
            gaze_saccade_estimates += 1

    gaze_to_click_latencies_ms: list[float] = []
    gaze_to_click_distances_px: list[float] = []
    click_without_prior_gaze = 0
    gaze_index = 0
    for click_time, click_x, click_y in click_coordinates:
        while gaze_index + 1 < len(gaze_coordinates) and gaze_coordinates[gaze_index + 1][0] <= click_time:
            gaze_index += 1
        if not gaze_coordinates or gaze_coordinates[gaze_index][0] > click_time:
            click_without_prior_gaze += 1
            continue

        gaze_time, gaze_x, gaze_y = gaze_coordinates[gaze_index]
        latency = duration_ms(gaze_time, click_time)
        if latency is None or latency > 2000:
            click_without_prior_gaze += 1
            continue
        gaze_to_click_latencies_ms.append(latency)
        gaze_to_click_distances_px.append(hypot(click_x - gaze_x, click_y - gaze_y))

    fixation_targets: dict[str, float] = {}
    for fixation in gaze_fixations:
        payload = fixation.get("payload", {})
        duration = payload.get("duration_ms")
        if not isinstance(duration, (int, float)):
            continue
        target_key = payload.get("path") or payload.get("id") or payload.get("tag_name") or "unknown"
        fixation_targets[target_key] = fixation_targets.get(target_key, 0.0) + float(duration)

    first_event_time = parse_timestamp(events[0].get("timestamp")) if events else None
    last_event_time = parse_timestamp(events[-1].get("timestamp")) if events else None
    first_gaze_time = gaze_coordinates[0][0] if gaze_coordinates else None
    calibration_start_time = (
        parse_timestamp(calibration_started[0].get("timestamp")) if calibration_started else None
    )
    calibration_complete_time = (
        parse_timestamp(calibration_completed[0].get("timestamp"))
        if calibration_completed
        else None
    )

    first_fixation_latency_ms = None
    if gaze_fixations:
        first_fixation_latency_ms = duration_ms(
            first_event_time,
            parse_timestamp(gaze_fixations[0].get("timestamp")),
        )
    gaze_cursor_distances = [
        float(event.get("payload", {}).get("distance_px"))
        for event in gaze_cursor_events
        if isinstance(event.get("payload", {}).get("distance_px"), (int, float))
    ]
    gaze_cursor_db_metrics = get_gaze_cursor_metrics(session_id)
    friction_counts = Counter(
        event.get("payload", {}).get("marker_type", "unknown")
        for event in friction_markers
    )
    open_tasks: dict[str, list[tuple[datetime, str, str | None]]] = {}
    task_durations: list[dict[str, Any]] = []
    for event in events:
        event_type = event.get("event_type")
        if event_type not in {"task_started", "task_completed"}:
            continue
        timestamp = parse_timestamp(event.get("timestamp"))
        if not timestamp:
            continue
        payload = event.get("payload", {})
        label = str(payload.get("label") or "Task")
        task_id = str(payload.get("task_id") or label)
        if event_type == "task_started":
            open_tasks.setdefault(task_id, []).append((timestamp, label, payload.get("completion_rule")))
            continue
        starts = open_tasks.get(task_id) or []
        if not starts:
            continue
        start, started_label, completion_rule = starts.pop(0)
        task_durations.append(
            {
                "task_id": task_id,
                "label": label or started_label,
                "started_at": start.isoformat(),
                "completed_at": timestamp.isoformat(),
                "duration_ms": round(duration_ms(start, timestamp) or 0, 2),
                "completion_rule": completion_rule,
                "completion_source": payload.get("completion_source"),
            }
        )
    task_duration_values = [item["duration_ms"] for item in task_durations]

    return {
        "session_id": session_id,
        "event_counts": dict(counts),
        "rrweb_chunks": len(rrweb_rows),
        "gaze_fixation_count": len(gaze_fixations),
        "gaze_point_count": len(gaze_points),
        "mouse_click_count": len(mouse_clicks),
        "avg_gaze_fixation_ms": round(mean(fixation_durations), 2),
        "median_gaze_fixation_ms": round(median(fixation_durations), 2) if fixation_durations else 0,
        "max_gaze_fixation_ms": round(max(fixation_durations), 2) if fixation_durations else 0,
        "total_gaze_fixation_ms": round(sum(fixation_durations), 2),
        "gaze_path_length_px": round(sum(gaze_path_segments), 2),
        "avg_gaze_step_px": round(mean(gaze_path_segments), 2),
        "avg_gaze_sample_interval_ms": round(mean(gaze_point_intervals_ms), 2),
        "gaze_samples_per_second": round(
            len(gaze_points) / max((duration_ms(first_gaze_time, last_event_time) or 1) / 1000, 0.001),
            2,
        )
        if gaze_points and last_event_time
        else 0,
        "gaze_saccade_count_estimate": gaze_saccade_estimates,
        "avg_gaze_to_click_latency_ms": round(mean(gaze_to_click_latencies_ms), 2),
        "median_gaze_to_click_latency_ms": round(median(gaze_to_click_latencies_ms), 2)
        if gaze_to_click_latencies_ms
        else 0,
        "avg_gaze_to_click_distance_px": round(mean(gaze_to_click_distances_px), 2),
        "gaze_cursor_sample_count": len(gaze_cursor_distances),
        "avg_gaze_cursor_distance_px": round(mean(gaze_cursor_distances), 2),
        "max_gaze_cursor_distance_px": round(max(gaze_cursor_distances), 2)
        if gaze_cursor_distances
        else 0,
        "gaze_cursor_close_ratio": round(
            len(
                [
                    event
                    for event in gaze_cursor_events
                    if event.get("payload", {}).get("clarity_signal") == "close"
                ]
            )
            / len(gaze_cursor_events),
            4,
        )
        if gaze_cursor_events
        else 0,
        "gaze_cursor_db_metrics": gaze_cursor_db_metrics,
        "friction_marker_count": len(friction_markers),
        "friction_marker_counts": dict(friction_counts),
        "high_severity_friction_count": len(
            [
                event
                for event in friction_markers
                if event.get("payload", {}).get("severity") == "high"
            ]
        ),
        "task_started_count": len(task_started),
        "task_completed_count": len(task_completed),
        "note_count": len(notes),
        "completed_task_durations": task_durations,
        "avg_task_duration_ms": round(mean(task_duration_values), 2),
        "open_task_count": sum(len(starts) for starts in open_tasks.values()),
        "clicks_with_prior_gaze_count": len(gaze_to_click_latencies_ms),
        "click_without_prior_gaze_count": click_without_prior_gaze,
        "clicks_with_prior_gaze_ratio": round(
            len(gaze_to_click_latencies_ms) / len(mouse_clicks), 4
        )
        if mouse_clicks
        else 0,
        "time_to_first_gaze_ms": round(duration_ms(first_event_time, first_gaze_time) or 0, 2),
        "time_to_first_fixation_ms": round(first_fixation_latency_ms or 0, 2),
        "calibration_started_count": len(calibration_started),
        "calibration_completed_count": len(calibration_completed),
        "calibration_duration_ms": round(
            duration_ms(calibration_start_time, calibration_complete_time) or 0,
            2,
        ),
        "top_fixated_elements": [
            {"target": target, "total_duration_ms": round(total_duration, 2)}
            for target, total_duration in sorted(
                fixation_targets.items(), key=lambda item: item[1], reverse=True
            )[:5]
        ],
    }


@app.get("/api/sessions/{session_id}/replay")
async def get_session_replay(session_id: str) -> dict[str, Any]:
    metadata = load_session_metadata(session_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Session not found")

    events = load_json_lines(session_path(session_id) / EVENTS_FILE)
    rrweb_rows = load_json_lines(session_path(session_id) / RRWEB_FILE)

    rrweb_events: list[dict[str, Any]] = []
    for row in rrweb_rows:
        rrweb_events.extend(row.get("events", []))

    rrweb_events.sort(key=lambda item: item.get("timestamp", 0))
    events.sort(key=lambda item: item.get("timestamp", ""))

    return {
        "session": metadata,
        "events": events,
        "rrweb_events": rrweb_events,
    }


@app.get("/api/sessions/{session_id}/timeline")
async def get_session_timeline(session_id: str) -> dict[str, Any]:
    metadata = load_session_metadata(session_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Session not found")

    base_path = session_path(session_id)
    events = load_json_lines(base_path / EVENTS_FILE)
    rrweb_rows = load_json_lines(base_path / RRWEB_FILE)
    screen_rows = load_json_lines(base_path / SCREEN_RECORDING_FILE)

    first_timestamp = None
    all_timestamps = [
        *(event.get("timestamp") for event in events),
        *(row.get("timestamp") for row in rrweb_rows),
        *(row.get("timestamp") for row in screen_rows),
    ]
    parsed_timestamps = [
        parsed
        for parsed in (parse_timestamp(value) for value in all_timestamps)
        if parsed is not None
    ]
    if parsed_timestamps:
        first_timestamp = min(parsed_timestamps)

    timeline: list[dict[str, Any]] = []
    overlay_event_types = {
        "gaze_point",
        "cursor_position",
        "mouse_move",
        "mouse_click",
        "gaze_cursor_distance",
        "gaze_fixation",
    }
    marker_event_types = {
        "task_started",
        "task_completed",
        "note_added",
    }

    for event in events:
        event_type = event.get("event_type", "unknown")
        category = "overlay" if event_type in overlay_event_types else "event"
        if event_type == "friction_marker":
            category = "friction"
        elif event_type in marker_event_types:
            category = "marker"
        timeline.append(
            {
                "kind": category,
                "timestamp": event.get("timestamp"),
                "offset_ms": event_offset_ms(event.get("timestamp"), first_timestamp),
                "source": event.get("source"),
                "event_type": event_type,
                "context": event.get("context", {}),
                "payload": event.get("payload", {}),
            }
        )

    for row_index, row in enumerate(rrweb_rows):
        timeline.append(
            {
                "kind": "rrweb_chunk",
                "timestamp": row.get("timestamp"),
                "offset_ms": event_offset_ms(row.get("timestamp"), first_timestamp),
                "source": row.get("source"),
                "chunk_index": row_index,
                "event_count": len(row.get("events", [])),
                "context": row.get("context", {}),
            }
        )

    for row in screen_rows:
        timeline.append(
            {
                "kind": "screen_recording_chunk",
                "timestamp": row.get("timestamp"),
                "offset_ms": event_offset_ms(row.get("timestamp"), first_timestamp),
                "source": row.get("source"),
                "chunk_index": row.get("chunk_index"),
                "mime_type": row.get("mime_type"),
                "filename": row.get("filename"),
                "recording_filename": row.get("recording_filename"),
                "size_bytes": row.get("size_bytes"),
                "final": row.get("final", False),
                "context": row.get("context", {}),
            }
        )

    timeline.sort(key=lambda item: (timestamp_sort_value(item.get("timestamp")), item.get("kind", "")))
    overlay = [
        item
        for item in timeline
        if item["kind"] in {"overlay", "friction"}
    ]
    media_assets = {
        "screen_recording": [
            item
            for item in timeline
            if item["kind"] == "screen_recording_chunk"
        ],
        "rrweb_chunks": [
            item
            for item in timeline
            if item["kind"] == "rrweb_chunk"
        ],
    }

    return {
        "session": metadata,
        "start_timestamp": first_timestamp.isoformat() if first_timestamp else None,
        "counts": {
            "events": len(events),
            "rrweb_chunks": len(rrweb_rows),
            "screen_recording_chunks": len(screen_rows),
            "timeline_items": len(timeline),
            "overlay_items": len(overlay),
            "friction_markers": len([item for item in timeline if item["kind"] == "friction"]),
        },
        "media_assets": media_assets,
        "overlay": overlay,
        "timeline": timeline,
    }


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            ensure_session_dir(session_id)

            if data.get("kind") == "rrweb" or data.get("type") == "record":
                rrweb_chunk = RrwebChunkIn(
                    session_id=session_id,
                    source=data.get("source", "browser_extension"),
                    timestamp=data.get("timestamp", now_iso()),
                    context={"url": data.get("url")},
                    events=data.get("events") or data.get("payload") or [],
                )
                await push_to_queue(
                    {
                        "kind": "rrweb",
                        "session_id": rrweb_chunk.session_id,
                        "source": rrweb_chunk.source,
                        "timestamp": rrweb_chunk.timestamp,
                        "received_at": now_iso(),
                        "context": rrweb_chunk.context.model_dump(exclude_none=True),
                        "events": rrweb_chunk.events,
                    }
                )
                continue

            raw_payload = data.get("payload", {})
            raw_event_type = (
                raw_payload.get("type")
                or data.get("event_type")
                or data.get("type")
                or "unknown"
            )
            event_in = EventIn(
                session_id=session_id,
                source=data.get("source", "browser_extension"),
                event_type=raw_event_type,
                timestamp=data.get("timestamp", now_iso()),
                sequence=data.get("sequence"),
                context={"url": data.get("url")},
                payload=raw_payload.get("details", raw_payload),
            )
            event = normalize_event(
                event_in,
                allocate_sequences(session_id, [event_in])[0],
            )
            await push_to_queue({"kind": "event", "event": event})
    except WebSocketDisconnect:
        persist_session_metadata(session_id, {"updated_at": now_iso()})
