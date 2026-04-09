import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aio_pika
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq/")
BASE_DIR = Path(os.getenv("RECORDED_SESSIONS_DIR", "recorded_sessions"))
EVENTS_FILE = "events.jsonl"
RRWEB_FILE = "dom_recording.jsonl"
SESSION_FILE = "session.json"

app = FastAPI(title="UX Tracking API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


class SessionCreate(BaseModel):
    session_id: str
    source: str = "frontend_tracker"
    started_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventIn(BaseModel):
    session_id: str
    source: str = "frontend_tracker"
    event_type: str
    timestamp: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)


class RrwebChunkIn(BaseModel):
    session_id: str
    source: str = "frontend_tracker"
    timestamp: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


def normalize_event(event: EventIn, sequence: int | None = None) -> dict[str, Any]:
    return {
        "session_id": event.session_id,
        "source": event.source,
        "event_type": event.event_type,
        "timestamp": event.timestamp or now_iso(),
        "received_at": now_iso(),
        "sequence": sequence,
        "context": event.context,
        "payload": event.payload,
    }


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok", "timestamp": now_iso()}


@app.post("/api/sessions")
async def create_session(body: SessionCreate) -> dict[str, Any]:
    metadata = write_session_metadata(
        body.session_id,
        {
            "session_id": body.session_id,
            "source": body.source,
            "started_at": body.started_at or now_iso(),
            "updated_at": now_iso(),
            "metadata": body.metadata,
        },
    )
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
async def create_event(body: EventIn) -> dict[str, Any]:
    ensure_session_dir(body.session_id)
    event = normalize_event(body)
    write_session_metadata(body.session_id, {"updated_at": now_iso()})
    await push_to_queue({"kind": "event", "event": event})
    return {"ok": True}


@app.post("/api/rrweb")
async def create_rrweb_chunk(body: RrwebChunkIn) -> dict[str, Any]:
    ensure_session_dir(body.session_id)
    payload = {
        "kind": "rrweb",
        "session_id": body.session_id,
        "source": body.source,
        "timestamp": body.timestamp or now_iso(),
        "received_at": now_iso(),
        "context": body.context,
        "events": body.events,
    }
    write_session_metadata(body.session_id, {"updated_at": now_iso()})
    await push_to_queue(payload)
    return {"ok": True, "events_received": len(body.events)}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    metadata_path = session_file_path(session_id)
    if not metadata_path.exists():
        raise HTTPException(status_code=404, detail="Session not found")

    metadata = json.loads(metadata_path.read_text())
    events = load_json_lines(session_path(session_id) / EVENTS_FILE)
    rrweb_rows = load_json_lines(session_path(session_id) / RRWEB_FILE)
    return {
        "session": metadata,
        "event_count": len(events),
        "rrweb_chunks": len(rrweb_rows),
    }


@app.get("/api/sessions")
async def list_sessions() -> dict[str, Any]:
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
    metadata_path = session_file_path(session_id)
    if not metadata_path.exists():
        raise HTTPException(status_code=404, detail="Session not found")

    events = load_json_lines(session_path(session_id) / EVENTS_FILE)
    rrweb_rows = load_json_lines(session_path(session_id) / RRWEB_FILE)

    counts = Counter(event.get("event_type", "unknown") for event in events)
    gaze_fixations = [event for event in events if event.get("event_type") == "gaze_fixation"]
    fixation_durations = [
        event.get("payload", {}).get("duration_ms", 0)
        for event in gaze_fixations
        if isinstance(event.get("payload", {}).get("duration_ms"), (int, float))
    ]

    avg_fixation = (
        sum(fixation_durations) / len(fixation_durations) if fixation_durations else 0
    )

    return {
        "session_id": session_id,
        "event_counts": dict(counts),
        "rrweb_chunks": len(rrweb_rows),
        "gaze_fixation_count": len(gaze_fixations),
        "avg_gaze_fixation_ms": round(avg_fixation, 2),
    }


@app.get("/api/sessions/{session_id}/replay")
async def get_session_replay(session_id: str) -> dict[str, Any]:
    metadata_path = session_file_path(session_id)
    if not metadata_path.exists():
        raise HTTPException(status_code=404, detail="Session not found")

    metadata = json.loads(metadata_path.read_text())
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


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            ensure_session_dir(session_id)

            if data.get("kind") == "rrweb" or data.get("type") == "record":
                await push_to_queue(
                    {
                        "kind": "rrweb",
                        "session_id": session_id,
                        "source": data.get("source", "browser_extension"),
                        "timestamp": data.get("timestamp", now_iso()),
                        "received_at": now_iso(),
                        "context": {"url": data.get("url")},
                        "events": data.get("events") or data.get("payload") or [],
                    }
                )
                continue

            raw_payload = data.get("payload", {})
            raw_event_type = raw_payload.get("type") or data.get("event_type") or data.get("type") or "unknown"
            event = {
                "session_id": session_id,
                "source": data.get("source", "browser_extension"),
                "event_type": raw_event_type,
                "timestamp": data.get("timestamp", now_iso()),
                "received_at": now_iso(),
                "sequence": data.get("sequence"),
                "context": {"url": data.get("url")},
                "payload": raw_payload.get("details", raw_payload),
            }
            await push_to_queue({"kind": "event", "event": event})
    except WebSocketDisconnect:
        write_session_metadata(session_id, {"updated_at": now_iso()})
