import asyncio
import base64
import csv
import io
import json
import os
import threading
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from math import hypot
from pathlib import Path
from statistics import median
from typing import Any

import aio_pika
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

from db import get_gaze_cursor_metrics
from db import get_session as db_get_session
from db import init_db, list_sessions as db_list_sessions, upsert_session
from event_models import EventBatchIn, EventIn, RrwebChunkIn, ScreenRecordingChunkIn, SessionCreate
from focus_evidence import calculate_focus_evidence
from reporting import (
    build_session_report,
    render_session_report_html,
    session_lifecycle,
)
from usability_analytics import (
    gaze_quality_summary,
    ivt_metrics,
    normalized_distance_px,
    normalized_gaze_series,
    sus_score,
)


RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq/")
BASE_DIR = Path(os.getenv("RECORDED_SESSIONS_DIR", "recorded_sessions"))
EVENTS_FILE = "events.jsonl"
RRWEB_FILE = "dom_recording.jsonl"
SCREEN_RECORDING_FILE = "screen_recording.jsonl"
SESSION_FILE = "session.json"

app = FastAPI(title="UX Tracking API")
_rabbit_lock = asyncio.Lock()
_sequence_locks_guard = threading.Lock()
_sequence_locks: dict[str, threading.Lock] = {}
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
    await get_rabbit_channel()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    connection = getattr(app.state, "rabbit_connection", None)
    if connection and not connection.is_closed:
        await connection.close()


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


def screen_recording_path(session_id: str) -> Path | None:
    base_path = session_path(session_id)
    for filename in ("screen_recording.webm", "screen_recording.mp4", "screen_recording.bin"):
        candidate = base_path / filename
        if candidate.is_file() and candidate.stat().st_size > 0:
            return candidate
    return None


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


def web_vital_rating(metric: str, value: float) -> str:
    thresholds = {
        "lcp_ms": (2500.0, 4000.0),
        "inp_ms": (200.0, 500.0),
        "cls": (0.1, 0.25),
    }
    good, poor = thresholds[metric]
    if value <= good:
        return "good"
    if value > poor:
        return "poor"
    return "needs_improvement"


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


async def get_rabbit_channel() -> aio_pika.abc.AbstractChannel:
    channel = getattr(app.state, "rabbit_channel", None)
    if channel and not channel.is_closed:
        return channel
    async with _rabbit_lock:
        channel = getattr(app.state, "rabbit_channel", None)
        if channel and not channel.is_closed:
            return channel
        connection = await aio_pika.connect_robust(RABBITMQ_URL)
        channel = await connection.channel()
        app.state.rabbit_connection = connection
        app.state.rabbit_channel = channel
        return channel


async def push_to_queue(data: dict[str, Any]) -> None:
    channel = await get_rabbit_channel()
    await channel.default_exchange.publish(
        aio_pika.Message(body=json.dumps(data).encode()),
        routing_key="ux_events",
    )


async def push_many_to_queue(items: list[dict[str, Any]]) -> None:
    if not items:
        return

    channel = await get_rabbit_channel()
    for item in items:
        await channel.default_exchange.publish(
            aio_pika.Message(body=json.dumps(item).encode()),
            routing_key="ux_events",
        )


def allocate_sequences(session_id: str, events: list[EventIn]) -> list[int]:
    with _sequence_locks_guard:
        lock = _sequence_locks.setdefault(session_id, threading.Lock())
    with lock:
        metadata = load_session_metadata(session_id)
        next_sequence = int(metadata.get("next_sequence", 1))
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
            {"updated_at": now_iso(), "next_sequence": next_sequence},
        )
        return assigned_sequences


def normalize_event(event: EventIn, sequence: int | None = None) -> dict[str, Any]:
    captured_at = event.captured_at or event.timestamp or now_iso()
    return {
        "event_id": str(event.event_id or uuid.uuid4()),
        "schema_version": event.schema_version,
        "session_id": event.session_id,
        "run_id": event.run_id,
        "producer_id": event.producer_id or event.source,
        "producer_sequence": event.producer_sequence,
        "source": event.source,
        "event_type": event.event_type,
        "captured_at": captured_at,
        "timestamp": captured_at,
        "monotonic_ns": event.monotonic_ns,
        "received_at": now_iso(),
        "sequence": sequence,
        "coordinate_space": event.coordinate_space,
        "quality": event.quality,
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
                "status": "recording",
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
    stopped_events = [
        event for event in normalized_events if event["event_type"] == "session_stopped"
    ]
    if stopped_events:
        latest_stop = max(
            stopped_events,
            key=lambda event: timestamp_sort_value(event.get("timestamp")),
        )
        current = load_session_metadata(session_id)
        nested = current.get("metadata", {})
        payload = latest_stop.get("payload", {})
        persist_session_metadata(
            session_id,
            {
                "updated_at": now_iso(),
                "metadata": {
                    **nested,
                    "status": "completed",
                    "ended_at": latest_stop.get("timestamp") or now_iso(),
                    **(
                        {"mode": payload["mode"]}
                        if payload.get("mode") in {"desktop_only", "web_desktop"}
                        else {}
                    ),
                },
            },
        )
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

    extension = (
        "webm"
        if "webm" in body.mime_type
        else "mp4"
        if "mp4" in body.mime_type
        else "bin"
    )
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
    enriched = []
    for item in items:
        session_id = item.get("session_id")
        # Session creation and stop handling persist lifecycle state in metadata.
        # Loading every event file here made the frequently-polled listing
        # endpoint O(total captured events) and blocked live ingestion.
        lifecycle = session_lifecycle(item, [])
        enriched.append(
            {
                **item,
                "lifecycle": lifecycle,
                "report_available": lifecycle["completed"],
                "screen_recording_available": bool(
                    screen_recording_path(session_id)
                )
                if session_id
                else False,
            }
        )
    return {"sessions": enriched}


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
    gaze_lost_events = [event for event in events if event.get("event_type") == "gaze_lost"]
    mouse_clicks = [event for event in events if event.get("event_type") == "mouse_click"]
    gaze_cursor_events = [
        event for event in events if event.get("event_type") == "gaze_cursor_distance"
    ]
    friction_markers = [event for event in events if event.get("event_type") == "friction_marker"]
    task_started = [event for event in events if event.get("event_type") == "task_started"]
    task_completed = [event for event in events if event.get("event_type") == "task_completed"]
    task_assessed = [event for event in events if event.get("event_type") == "task_assessed"]
    notes = [event for event in events if event.get("event_type") == "note_added"]
    scroll_events = [event for event in events if event.get("event_type") == "scroll"]
    route_events = [
        event
        for event in events
        if event.get("event_type") in {"route_changed", "page_navigation_completed"}
    ]
    input_events = [event for event in events if event.get("event_type") == "text_input_metadata"]
    input_corrections = [event for event in events if event.get("event_type") == "input_correction"]
    field_interactions = [event for event in events if event.get("event_type") == "field_interaction"]
    client_errors = [event for event in events if event.get("event_type") == "client_error"]
    web_vital_events = [event for event in events if event.get("event_type") == "web_vitals_snapshot"]
    page_performance_events = [
        event for event in events if event.get("event_type") == "page_performance"
    ]
    questionnaire_events = [
        event
        for event in events
        if event.get("event_type") == "session_questionnaire_response"
    ]
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

    gaze_coordinates: list[tuple[datetime, float, float, dict[str, Any]]] = []
    for event in gaze_points:
        payload = event.get("payload", {})
        timestamp = parse_timestamp(event.get("timestamp"))
        x = payload.get("screen_x")
        y = payload.get("screen_y")
        if timestamp and isinstance(x, (int, float)) and isinstance(y, (int, float)):
            gaze_coordinates.append((timestamp, float(x), float(y), event))

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
        previous_time, previous_x, previous_y, _ = gaze_coordinates[index - 1]
        current_time, current_x, current_y, _ = gaze_coordinates[index]
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

        gaze_time, gaze_x, gaze_y, gaze_event = gaze_coordinates[gaze_index]
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
    last_gaze_time = gaze_coordinates[-1][0] if gaze_coordinates else None
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
        first_fixation_end = parse_timestamp(gaze_fixations[0].get("timestamp"))
        first_fixation_duration = gaze_fixations[0].get("payload", {}).get("duration_ms", 0)
        first_fixation_start = (
            first_fixation_end - timedelta(milliseconds=float(first_fixation_duration))
            if first_fixation_end and isinstance(first_fixation_duration, (int, float))
            else first_fixation_end
        )
        first_fixation_latency_ms = duration_ms(
            first_event_time,
            first_fixation_start,
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
                "outcome": payload.get("outcome") or "success",
                "seq_rating": payload.get("seq_rating"),
                "assessment_note": payload.get("assessment_note"),
            }
        )

    assessments_by_task_id: dict[str, dict[str, Any]] = {}
    for event in task_assessed:
        payload = event.get("payload", {})
        task_id = payload.get("task_id")
        if task_id:
            assessments_by_task_id[str(task_id)] = payload
    for item in task_durations:
        assessment = assessments_by_task_id.get(item["task_id"])
        if not assessment:
            assessment = {}
        item["outcome"] = assessment.get("outcome") or item["outcome"]
        item["seq_rating"] = assessment.get("seq_rating", item.get("seq_rating"))
        item["assessment_note"] = assessment.get(
            "assessment_note", item.get("assessment_note")
        )
        task_start = parse_timestamp(item["started_at"])
        task_end = parse_timestamp(item["completed_at"])
        task_events = [
            event
            for event in events
            if task_start
            and task_end
            and (event_time := parse_timestamp(event.get("timestamp")))
            and task_start <= event_time <= task_end
        ]
        per_type = Counter(event.get("event_type", "unknown") for event in task_events)
        item["event_count"] = len(task_events)
        item["click_count"] = per_type["mouse_click"]
        item["scroll_count"] = per_type["scroll"]
        item["route_change_count"] = (
            per_type["route_changed"] + per_type["page_navigation_completed"]
        )
        item["input_correction_count"] = per_type["input_correction"]
        item["client_error_count"] = per_type["client_error"]
        item["friction_marker_count"] = per_type["friction_marker"]
        item["gaze_lost_count"] = per_type["gaze_lost"]

    task_duration_values = [item["duration_ms"] for item in task_durations]
    task_outcome_counts = Counter(item["outcome"] for item in task_durations)
    successful_task_count = task_outcome_counts["success"]
    partial_task_count = task_outcome_counts["partial_success"]
    seq_ratings = [
        float(item["seq_rating"])
        for item in task_durations
        if isinstance(item.get("seq_rating"), (int, float))
        and 1 <= float(item["seq_rating"]) <= 7
    ]
    confidence_values = [
        float(event.get("payload", {}).get("confidence"))
        for event in gaze_points
        if isinstance(event.get("payload", {}).get("confidence"), (int, float))
    ]
    low_confidence_count = sum(
        1
        for event in gaze_points
        if isinstance(event.get("payload", {}).get("confidence"), (int, float))
        and float(event["payload"]["confidence"])
        < float(event["payload"].get("confidence_threshold", 0.35))
    )
    gaze_duration_seconds = (
        max((duration_ms(first_gaze_time, last_gaze_time) or 0) / 1000, 0.001)
        if first_gaze_time and last_gaze_time
        else 0
    )
    gaze_sample_rate = (
        len(gaze_points) / gaze_duration_seconds
        if gaze_points and gaze_duration_seconds
        else 0.0
    )
    low_confidence_ratio = (
        low_confidence_count / len(confidence_values) if confidence_values else 0.0
    )
    gaze_quality = gaze_quality_summary(
        gaze_points,
        gaze_lost_events,
        gaze_sample_rate,
        low_confidence_ratio,
    )
    normalized_series = normalized_gaze_series(gaze_coordinates)
    ivt = ivt_metrics(normalized_series)
    normalized_path_segments = [
        hypot(current[1] - previous[1], current[2] - previous[2])
        for previous, current in zip(normalized_series, normalized_series[1:])
    ]
    normalized_gaze_cursor_distances = [
        normalized
        for event in gaze_cursor_events
        if isinstance(event.get("payload", {}).get("distance_px"), (int, float))
        and (
            normalized := normalized_distance_px(
                float(event["payload"]["distance_px"]), event
            )
        )
        is not None
    ]
    sus_responses = []
    for event in questionnaire_events:
        payload = event.get("payload", {})
        answers = payload.get("sus_answers")
        if isinstance(answers, list):
            score = sus_score(answers)
            if score is not None:
                sus_responses.append(score)
    coordinate_spaces = Counter(
        event.get("coordinate_space")
        or event.get("payload", {}).get("coordinate_space")
        or "unknown"
        for event in gaze_points
    )
    session_duration_ms = duration_ms(first_event_time, last_event_time) or 0

    max_scroll_depth_ratio = 0.0
    scroll_direction_changes = 0
    previous_direction = 0
    for event in scroll_events:
        payload = event.get("payload", {})
        scroll_y = payload.get("scroll_y")
        document_height = payload.get("document_height")
        viewport_height = payload.get("viewport_height")
        if all(isinstance(value, (int, float)) for value in (scroll_y, document_height, viewport_height)):
            scrollable = max(float(document_height) - float(viewport_height), 0.0)
            depth = min(max(float(scroll_y) / scrollable, 0.0), 1.0) if scrollable else 1.0
            max_scroll_depth_ratio = max(max_scroll_depth_ratio, depth)
        delta_y = payload.get("delta_y")
        if not isinstance(delta_y, (int, float)) or abs(float(delta_y)) < 40:
            continue
        direction = 1 if delta_y > 0 else -1
        if previous_direction and direction != previous_direction:
            scroll_direction_changes += 1
        previous_direction = direction

    visited_routes: list[str] = []
    for event in route_events:
        payload = event.get("payload", {})
        destination = payload.get("to") or payload.get("url")
        if isinstance(destination, str) and destination:
            visited_routes.append(destination)
    route_revisit_count = len(visited_routes) - len(set(visited_routes))

    field_durations = [
        float(event.get("payload", {}).get("duration_ms"))
        for event in field_interactions
        if isinstance(event.get("payload", {}).get("duration_ms"), (int, float))
    ]
    field_correction_counts = [
        int(event.get("payload", {}).get("correction_count"))
        for event in field_interactions
        if isinstance(event.get("payload", {}).get("correction_count"), (int, float))
    ]

    web_vitals = {"lcp_ms": 0.0, "inp_ms": 0.0, "cls": 0.0}
    for event in web_vital_events:
        payload = event.get("payload", {})
        for metric in web_vitals:
            value = payload.get(metric)
            if isinstance(value, (int, float)):
                web_vitals[metric] = max(web_vitals[metric], float(value))
    web_vital_ratings = {
        metric: web_vital_rating(metric, value)
        for metric, value in web_vitals.items()
        if value > 0
    }

    page_load_values = [
        float(event.get("payload", {}).get("load_event_ms"))
        for event in page_performance_events
        if isinstance(event.get("payload", {}).get("load_event_ms"), (int, float))
        and float(event.get("payload", {}).get("load_event_ms")) > 0
    ]
    completed_task_count = len(task_durations)
    task_success_rate = successful_task_count / len(task_started) if task_started else 0.0
    weighted_task_effectiveness = (
        (successful_task_count + partial_task_count * 0.5) / len(task_started)
        if task_started
        else 0.0
    )
    active_task_minutes = sum(task_duration_values) / 60000
    task_efficiency_per_minute = (
        successful_task_count / active_task_minutes if active_task_minutes > 0 else 0.0
    )

    return {
        "session_id": session_id,
        "multimodal_focus_evidence": calculate_focus_evidence(events),
        "gaze_quality": gaze_quality,
        "event_counts": dict(counts),
        "rrweb_chunks": len(rrweb_rows),
        "gaze_fixation_count": len(gaze_fixations) or ivt["fixation_segment_count"],
        "gaze_fixation_source": "dom" if gaze_fixations else "normalized_ivt_v1",
        "gaze_point_count": len(gaze_points),
        "mouse_click_count": len(mouse_clicks),
        "avg_gaze_fixation_ms": round(mean(fixation_durations), 2),
        "median_gaze_fixation_ms": round(median(fixation_durations), 2) if fixation_durations else 0,
        "max_gaze_fixation_ms": round(max(fixation_durations), 2) if fixation_durations else 0,
        "total_gaze_fixation_ms": round(sum(fixation_durations), 2),
        "gaze_path_length_px": round(sum(gaze_path_segments), 2),
        "avg_gaze_step_px": round(mean(gaze_path_segments), 2),
        "avg_gaze_sample_interval_ms": round(mean(gaze_point_intervals_ms), 2),
        "gaze_samples_per_second": round(gaze_sample_rate, 2),
        "gaze_lost_count": len(gaze_lost_events),
        "avg_gaze_confidence": round(mean(confidence_values), 4),
        "low_confidence_sample_count": low_confidence_count,
        "low_confidence_sample_ratio": round(low_confidence_ratio, 4),
        "gaze_coordinate_spaces": dict(coordinate_spaces),
        "gaze_saccade_count_estimate": gaze_saccade_estimates,
        "gaze_ivt": ivt,
        "gaze_path_length_normalized": round(sum(normalized_path_segments), 4),
        "avg_gaze_to_click_latency_ms": round(mean(gaze_to_click_latencies_ms), 2),
        "median_gaze_to_click_latency_ms": round(median(gaze_to_click_latencies_ms), 2)
        if gaze_to_click_latencies_ms
        else 0,
        "avg_gaze_to_click_distance_px": round(mean(gaze_to_click_distances_px), 2),
        "gaze_cursor_sample_count": len(gaze_cursor_distances),
        "avg_gaze_cursor_distance_px": round(mean(gaze_cursor_distances), 2),
        "avg_gaze_cursor_distance_screen_diagonal_ratio": round(
            mean(normalized_gaze_cursor_distances), 6
        ),
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
        "task_assessed_count": len(task_assessed),
        "paired_task_completion_count": completed_task_count,
        "successful_task_count": successful_task_count,
        "partial_success_task_count": partial_task_count,
        "failed_task_count": task_outcome_counts["failure"],
        "abandoned_task_count": task_outcome_counts["abandoned"],
        "task_outcome_counts": dict(task_outcome_counts),
        "task_success_rate": round(task_success_rate, 4),
        "weighted_task_effectiveness": round(weighted_task_effectiveness, 4),
        "task_efficiency_completed_per_minute": round(task_efficiency_per_minute, 4),
        "errors_per_completed_task": round(len(client_errors) / completed_task_count, 4)
        if completed_task_count
        else 0,
        "note_count": len(notes),
        "completed_task_durations": task_durations,
        "avg_task_duration_ms": round(mean(task_duration_values), 2),
        "seq_response_count": len(seq_ratings),
        "seq_response_rate": round(len(seq_ratings) / completed_task_count, 4)
        if completed_task_count
        else 0,
        "avg_seq_rating": round(mean(seq_ratings), 2),
        "median_seq_rating": round(median(seq_ratings), 2) if seq_ratings else 0,
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
        "session_duration_ms": round(session_duration_ms, 2),
        "scroll_event_count": len(scroll_events),
        "max_scroll_depth_ratio": round(max_scroll_depth_ratio, 4),
        "scroll_direction_change_count": scroll_direction_changes,
        "route_change_count": len(route_events),
        "unique_route_count": len(set(visited_routes)),
        "route_revisit_count": route_revisit_count,
        "route_revisit_ratio": round(route_revisit_count / len(visited_routes), 4)
        if visited_routes
        else 0,
        "text_input_event_count": len(input_events),
        "input_correction_count": len(input_corrections),
        "input_correction_ratio": round(len(input_corrections) / len(input_events), 4)
        if input_events
        else 0,
        "field_interaction_count": len(field_interactions),
        "avg_field_interaction_ms": round(mean(field_durations), 2),
        "avg_field_corrections": round(mean(field_correction_counts), 2),
        "client_error_count": len(client_errors),
        "client_error_counts": dict(
            Counter(
                event.get("payload", {}).get("error_type", "unknown")
                for event in client_errors
            )
        ),
        "web_vitals": {metric: round(value, 4) for metric, value in web_vitals.items()},
        "web_vital_ratings": web_vital_ratings,
        "page_performance_sample_count": len(page_performance_events),
        "avg_page_load_ms": round(mean(page_load_values), 2),
        "sus_response_count": len(sus_responses),
        "avg_sus_score": round(mean(sus_responses), 2),
    }


@app.get("/api/sessions/{session_id}/mfem.csv")
async def export_mfem_csv(session_id: str) -> StreamingResponse:
    metrics = await get_session_metrics(session_id)
    mfem = metrics["multimodal_focus_evidence"]
    probes = [
        (parse_timestamp(item.get("timestamp")), item)
        for item in mfem.get("probes", [])
    ]
    output = io.StringIO()
    fields = [
        "session_id",
        "model_version",
        "window_start",
        "window_end",
        "status",
        "quality",
        "focus_evidence",
        "visual_engagement",
        "interaction_engagement",
        "cognitive_effort_evidence",
        "gaze_samples",
        "gaze_lost",
        "on_screen_ratio",
        "avg_gaze_confidence",
        "head_deviation_deg",
        "eye_narrowing_from_baseline",
        "interaction_count",
        "app_switch_count",
        "nearest_probe_rating",
        "nearest_probe_mind_wandering",
        "nearest_probe_distance_s",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for window in mfem.get("windows", []):
        evidence = window.get("evidence", {})
        window_end = parse_timestamp(window.get("end"))
        nearest = min(
            (
                (abs((timestamp - window_end).total_seconds()), probe)
                for timestamp, probe in probes
                if timestamp and window_end
            ),
            default=(None, {}),
            key=lambda item: item[0] if item[0] is not None else float("inf"),
        )
        probe_distance, probe = nearest
        writer.writerow(
            {
                "session_id": session_id,
                "model_version": mfem.get("model_version"),
                "window_start": window.get("start"),
                "window_end": window.get("end"),
                "status": window.get("status"),
                "quality": window.get("quality"),
                "focus_evidence": window.get("focus_evidence"),
                "visual_engagement": window.get("visual_engagement"),
                "interaction_engagement": window.get("interaction_engagement"),
                "cognitive_effort_evidence": window.get("cognitive_effort_evidence"),
                **{field: evidence.get(field) for field in fields if field in evidence},
                "nearest_probe_rating": probe.get("rating"),
                "nearest_probe_mind_wandering": probe.get("mind_wandering"),
                "nearest_probe_distance_s": round(probe_distance, 3)
                if probe_distance is not None
                else None,
            }
        )
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{session_id}-mfem.csv"'
        },
    )


async def get_session_report_data(session_id: str) -> dict[str, Any]:
    metadata = load_session_metadata(session_id)
    if not metadata:
        raise HTTPException(status_code=404, detail="Session not found")
    events = load_json_lines(session_path(session_id) / EVENTS_FILE)
    metrics = await get_session_metrics(session_id)
    timeline = await get_session_timeline(session_id)
    return build_session_report(
        session_id=session_id,
        metadata=metadata,
        events=events,
        metrics=metrics,
        timeline=timeline,
        recording_available=screen_recording_path(session_id) is not None,
    )


@app.get("/api/sessions/{session_id}/report.json")
async def get_session_report_json(session_id: str) -> dict[str, Any]:
    return await get_session_report_data(session_id)


@app.get("/api/sessions/{session_id}/report", response_class=HTMLResponse)
async def get_session_report(session_id: str) -> HTMLResponse:
    report = await get_session_report_data(session_id)
    return HTMLResponse(render_session_report_html(report))


@app.get("/api/sessions/{session_id}/screen-recording")
async def get_screen_recording(session_id: str) -> FileResponse:
    if not load_session_metadata(session_id):
        raise HTTPException(status_code=404, detail="Session not found")
    recording = screen_recording_path(session_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Screen recording not found for this session")
    media_type = (
        "video/webm"
        if recording.suffix.lower() == ".webm"
        else "video/mp4"
        if recording.suffix.lower() == ".mp4"
        else "application/octet-stream"
    )
    return FileResponse(
        recording,
        media_type=media_type,
        filename=recording.name,
        content_disposition_type="inline",
    )


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
        "task_assessed",
        "note_added",
        "attention_probe_response",
        "session_questionnaire_response",
        "client_error",
        "web_vitals_snapshot",
        "gaze_lost",
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
