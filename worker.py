import asyncio
import json
import os
from datetime import datetime, timezone
from math import hypot
from pathlib import Path
from typing import Any

import aio_pika

from db import init_db, insert_gaze_cursor_sample


BASE_DIR = Path(os.getenv("RECORDED_SESSIONS_DIR", "recorded_sessions"))
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq/")
EVENTS_FILE = "events.jsonl"
RRWEB_FILE = "dom_recording.jsonl"
GAZE_CURSOR_MAX_PAIR_AGE_MS = float(os.getenv("UX_GAZE_CURSOR_MAX_PAIR_AGE_MS", "1000"))
GAZE_CURSOR_CLOSE_THRESHOLD_PX = float(os.getenv("UX_GAZE_CURSOR_CLOSE_THRESHOLD_PX", "140"))
GAZE_CURSOR_FAR_THRESHOLD_PX = float(os.getenv("UX_GAZE_CURSOR_FAR_THRESHOLD_PX", "360"))
RAGE_CLICK_WINDOW_MS = float(os.getenv("UX_RAGE_CLICK_WINDOW_MS", "1200"))
RAGE_CLICK_RADIUS_PX = float(os.getenv("UX_RAGE_CLICK_RADIUS_PX", "45"))
RAGE_CLICK_MIN_CLICKS = int(os.getenv("UX_RAGE_CLICK_MIN_CLICKS", "3"))
CLICK_WITHOUT_GAZE_MAX_AGE_MS = float(os.getenv("UX_CLICK_WITHOUT_GAZE_MAX_AGE_MS", "1500"))

latest_by_session: dict[str, dict[str, dict[str, Any]]] = {}
recent_clicks_by_session: dict[str, list[dict[str, Any]]] = {}
emitted_friction_keys: set[str] = set()


def ensure_session_dir(session_id: str) -> Path:
    path = BASE_DIR / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def parse_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def event_point(event: dict[str, Any]) -> tuple[float, float] | None:
    payload = event.get("payload", {})
    x = payload.get("screen_x", payload.get("x"))
    y = payload.get("screen_y", payload.get("y"))
    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
        return None
    return float(x), float(y)


def classify_distance(distance_px: float) -> str:
    if distance_px <= GAZE_CURSOR_CLOSE_THRESHOLD_PX:
        return "close"
    if distance_px >= GAZE_CURSOR_FAR_THRESHOLD_PX:
        return "far"
    return "medium"


def write_event(session_path: Path, event: dict[str, Any]) -> None:
    with (session_path / EVENTS_FILE).open("a") as handle:
        handle.write(json.dumps(event) + "\n")


def emit_derived_event(
    session_id: str,
    session_path: Path,
    *,
    event_type: str,
    timestamp: datetime,
    context: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    write_event(
        session_path,
        {
            "session_id": session_id,
            "source": "rabbit_live_detector",
            "event_type": event_type,
            "timestamp": timestamp.isoformat(),
            "received_at": datetime.now(timezone.utc).isoformat(),
            "sequence": None,
            "context": context,
            "payload": payload,
        },
    )


def maybe_store_gaze_cursor_distance(
    session_id: str,
    session_path: Path,
    event: dict[str, Any],
) -> None:
    event_type = event.get("event_type")
    if event_type == "gaze_cursor_distance":
        store_gaze_cursor_distance_payload(session_id, event)
        return
    if event.get("source") == "desktop_agent":
        return
    if event_type not in {"gaze_point", "cursor_position", "mouse_move"}:
        return

    point = event_point(event)
    if not point:
        return

    timestamp = parse_timestamp(event.get("timestamp"))
    session_state = latest_by_session.setdefault(session_id, {})
    if event_type == "gaze_point":
        session_state["gaze"] = {"timestamp": timestamp, "point": point, "event": event}
    else:
        session_state["cursor"] = {"timestamp": timestamp, "point": point, "event": event}

    gaze = session_state.get("gaze")
    cursor = session_state.get("cursor")
    if not gaze or not cursor:
        return

    gaze_age_ms = abs((timestamp - gaze["timestamp"]).total_seconds() * 1000)
    cursor_age_ms = abs((timestamp - cursor["timestamp"]).total_seconds() * 1000)
    if max(gaze_age_ms, cursor_age_ms) > GAZE_CURSOR_MAX_PAIR_AGE_MS:
        return

    gaze_x, gaze_y = gaze["point"]
    cursor_x, cursor_y = cursor["point"]
    distance_px = hypot(gaze_x - cursor_x, gaze_y - cursor_y)
    clarity_signal = classify_distance(distance_px)
    payload = {
        "gaze_x": round(gaze_x, 2),
        "gaze_y": round(gaze_y, 2),
        "cursor_x": round(cursor_x, 2),
        "cursor_y": round(cursor_y, 2),
        "distance_px": round(distance_px, 2),
        "gaze_age_ms": round(gaze_age_ms, 2),
        "cursor_age_ms": round(cursor_age_ms, 2),
        "clarity_signal": clarity_signal,
        "close_threshold_px": GAZE_CURSOR_CLOSE_THRESHOLD_PX,
        "far_threshold_px": GAZE_CURSOR_FAR_THRESHOLD_PX,
    }
    emit_derived_event(
        session_id,
        session_path,
        event_type="gaze_cursor_distance",
        timestamp=timestamp,
        context=event.get("context", {}),
        payload=payload,
    )

    try:
        insert_gaze_cursor_sample(
            session_id=session_id,
            timestamp=timestamp,
            source_event_type=str(event_type),
            gaze_x=gaze_x,
            gaze_y=gaze_y,
            cursor_x=cursor_x,
            cursor_y=cursor_y,
            gaze_age_ms=gaze_age_ms,
            cursor_age_ms=cursor_age_ms,
            clarity_signal=clarity_signal,
            context=event.get("context", {}),
        )
    except Exception as error:
        print(f"[!] Failed to store gaze/cursor metric session={session_id}: {error}")


def store_gaze_cursor_distance_payload(session_id: str, event: dict[str, Any]) -> None:
    payload = event.get("payload", {})
    required_fields = ("gaze_x", "gaze_y", "cursor_x", "cursor_y")
    if not all(isinstance(payload.get(field), (int, float)) for field in required_fields):
        return

    timestamp = parse_timestamp(event.get("timestamp"))
    try:
        insert_gaze_cursor_sample(
            session_id=session_id,
            timestamp=timestamp,
            source_event_type="gaze_cursor_distance",
            gaze_x=float(payload["gaze_x"]),
            gaze_y=float(payload["gaze_y"]),
            cursor_x=float(payload["cursor_x"]),
            cursor_y=float(payload["cursor_y"]),
            gaze_age_ms=float(payload.get("gaze_age_ms", 0)),
            cursor_age_ms=float(payload.get("cursor_age_ms", 0)),
            clarity_signal=str(payload.get("clarity_signal", "unknown")),
            context=event.get("context", {}),
        )
    except Exception as error:
        print(f"[!] Failed to store emitted gaze/cursor metric session={session_id}: {error}")


def point_distance(first: tuple[float, float], second: tuple[float, float]) -> float:
    return hypot(first[0] - second[0], first[1] - second[1])


def friction_key(session_id: str, marker_type: str, timestamp: datetime, point: tuple[float, float]) -> str:
    bucket = int(timestamp.timestamp() * 1000 // 1000)
    return f"{session_id}:{marker_type}:{bucket}:{round(point[0] / 20)}:{round(point[1] / 20)}"


def maybe_emit_click_friction(
    session_id: str,
    session_path: Path,
    event: dict[str, Any],
) -> None:
    if event.get("source") == "desktop_agent":
        return
    if event.get("event_type") != "mouse_click":
        return

    point = event_point(event)
    if not point:
        return

    timestamp = parse_timestamp(event.get("timestamp"))
    context = event.get("context", {})
    clicks = recent_clicks_by_session.setdefault(session_id, [])
    clicks.append({"timestamp": timestamp, "point": point, "event": event})
    clicks[:] = [
        click
        for click in clicks
        if (timestamp - click["timestamp"]).total_seconds() * 1000 <= RAGE_CLICK_WINDOW_MS
    ]

    nearby_clicks = [
        click
        for click in clicks
        if point_distance(point, click["point"]) <= RAGE_CLICK_RADIUS_PX
    ]
    if len(nearby_clicks) >= RAGE_CLICK_MIN_CLICKS:
        key = friction_key(session_id, "rage_click", timestamp, point)
        if key not in emitted_friction_keys:
            emitted_friction_keys.add(key)
            emit_derived_event(
                session_id,
                session_path,
                event_type="friction_marker",
                timestamp=timestamp,
                context=context,
                payload={
                    "marker_type": "rage_click",
                    "severity": "high",
                    "click_count": len(nearby_clicks),
                    "window_ms": RAGE_CLICK_WINDOW_MS,
                    "radius_px": RAGE_CLICK_RADIUS_PX,
                    "screen_x": round(point[0], 2),
                    "screen_y": round(point[1], 2),
                    "reason": "Repeated clicks in a small area.",
                },
            )

    gaze = latest_by_session.get(session_id, {}).get("gaze")
    if not gaze:
        return

    gaze_age_ms = abs((timestamp - gaze["timestamp"]).total_seconds() * 1000)
    gaze_distance_px = point_distance(point, gaze["point"])
    if gaze_age_ms > CLICK_WITHOUT_GAZE_MAX_AGE_MS or gaze_distance_px <= GAZE_CURSOR_FAR_THRESHOLD_PX:
        return

    key = friction_key(session_id, "click_without_recent_gaze", timestamp, point)
    if key in emitted_friction_keys:
        return
    emitted_friction_keys.add(key)
    emit_derived_event(
        session_id,
        session_path,
        event_type="friction_marker",
        timestamp=timestamp,
        context=context,
        payload={
            "marker_type": "click_without_recent_gaze",
            "severity": "medium",
            "screen_x": round(point[0], 2),
            "screen_y": round(point[1], 2),
            "gaze_x": round(gaze["point"][0], 2),
            "gaze_y": round(gaze["point"][1], 2),
            "gaze_age_ms": round(gaze_age_ms, 2),
            "gaze_distance_px": round(gaze_distance_px, 2),
            "reason": "Click was far from the latest gaze point.",
        },
    )


async def on_message(message: aio_pika.IncomingMessage) -> None:
    async with message.process():
        data = json.loads(message.body)
        session_id = data.get("session_id") or data.get("event", {}).get("session_id") or "unknown"
        session_path = ensure_session_dir(session_id)
        kind = data.get("kind", "event")

        if kind == "rrweb":
            row = {
                "timestamp": data.get("timestamp"),
                "received_at": data.get("received_at"),
                "source": data.get("source"),
                "context": data.get("context", {}),
                "events": data.get("events", []),
            }
            with (session_path / RRWEB_FILE).open("a") as handle:
                handle.write(json.dumps(row) + "\n")
            print(f"[x] Stored rrweb chunk for session={session_id} size={len(row['events'])}")
            return

        event = data.get("event", data)
        write_event(session_path, event)
        maybe_store_gaze_cursor_distance(session_id, session_path, event)
        maybe_emit_click_friction(session_id, session_path, event)
        print(
            f"[x] Stored event type={event.get('event_type', 'unknown')} session={session_id}"
        )


async def main() -> None:
    init_db()
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()
    queue = await channel.declare_queue("ux_events", durable=True)
    await queue.consume(on_message)
    await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
