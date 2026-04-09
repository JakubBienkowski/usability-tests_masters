import asyncio
import json
import os
from pathlib import Path

import aio_pika


BASE_DIR = Path(os.getenv("RECORDED_SESSIONS_DIR", "recorded_sessions"))
RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq/")
EVENTS_FILE = "events.jsonl"
RRWEB_FILE = "dom_recording.jsonl"


def ensure_session_dir(session_id: str) -> Path:
    path = BASE_DIR / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path


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
        with (session_path / EVENTS_FILE).open("a") as handle:
            handle.write(json.dumps(event) + "\n")
        print(
            f"[x] Stored event type={event.get('event_type', 'unknown')} session={session_id}"
        )


async def main() -> None:
    connection = await aio_pika.connect_robust(RABBITMQ_URL)
    channel = await connection.channel()
    queue = await channel.declare_queue("ux_events", durable=True)
    await queue.consume(on_message)
    await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
