import json
import os
import queue
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from pynput import keyboard, mouse


API_URL = os.getenv("UX_API_URL", "http://localhost:8000/api")
STATE_FILE = Path(os.getenv("UX_AGENT_STATE_FILE", ".desktop_agent_state.json"))
SOURCE = "desktop_agent"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_or_create_session_id() -> str:
    forced_session_id = os.getenv("UX_SESSION_ID")
    if forced_session_id:
        STATE_FILE.write_text(json.dumps({"session_id": forced_session_id}))
        return forced_session_id

    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            if data.get("session_id"):
                return data["session_id"]
        except json.JSONDecodeError:
            pass

    session_id = f"sess_desktop_{int(time.time() * 1000)}"
    STATE_FILE.write_text(json.dumps({"session_id": session_id}))
    return session_id


def run_command(command: list[str]) -> str | None:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
        )
        value = result.stdout.strip()
        return value or None
    except Exception:
        return None


def active_context() -> dict[str, Any]:
    if os.name != "posix":
        return {"app_name": None, "window_title": None}

    app_name = run_command(
        [
            "osascript",
            "-e",
            'tell application "System Events" to get name of first application process whose frontmost is true',
        ]
    )
    window_title = run_command(
        [
            "osascript",
            "-e",
            'tell application "System Events" to tell (first application process whose frontmost is true) to get name of front window',
        ]
    )
    return {
        "app_name": app_name,
        "window_title": window_title,
    }


class GazeProvider:
    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError


class NullGazeProvider(GazeProvider):
    def start(self) -> None:
        return

    def stop(self) -> None:
        return


class PyGazeProvider(GazeProvider):
    def __init__(self, emit_event):
        self.emit_event = emit_event
        self.thread = None
        self.stop_event = threading.Event()

    def start(self) -> None:
        try:
            from pygaze import libtime  # type: ignore
        except Exception as error:
            self.emit_event(
                "gaze_provider_unavailable",
                {
                    "provider": "pygaze",
                    "message": str(error),
                },
            )
            return

        def run() -> None:
            while not self.stop_event.is_set():
                self.emit_event(
                    "gaze_provider_heartbeat",
                    {
                        "provider": "pygaze",
                        "clock_ms": libtime.get_time(),
                    },
                )
                time.sleep(1.0)

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        self.emit_event("gaze_provider_started", {"provider": "pygaze"})

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)


@dataclass
class DesktopAgent:
    session_id: str

    def __post_init__(self) -> None:
        self.event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.stop_event = threading.Event()
        self.last_mouse_move_at = 0.0
        self.last_active_context: dict[str, Any] | None = None
        self.mouse_listener = None
        self.keyboard_listener = None
        self.uploader_thread = threading.Thread(target=self.upload_loop, daemon=True)
        self.context_thread = threading.Thread(target=self.context_loop, daemon=True)
        self.gaze_provider = self.build_gaze_provider()

    def build_gaze_provider(self) -> GazeProvider:
        provider_name = os.getenv("UX_GAZE_PROVIDER", "pygaze").lower()
        if provider_name == "pygaze":
            return PyGazeProvider(self.emit_event)
        return NullGazeProvider()

    def post_json(self, path: str, payload: dict[str, Any]) -> None:
        response = requests.post(
            f"{API_URL}{path}",
            json=payload,
            timeout=5,
        )
        response.raise_for_status()

    def create_session(self) -> None:
        self.post_json(
            "/sessions",
            {
                "session_id": self.session_id,
                "source": SOURCE,
                "metadata": {
                    "platform": os.uname().sysname if hasattr(os, "uname") else os.name,
                    "started_from": "desktop_agent",
                    "gaze_provider": os.getenv("UX_GAZE_PROVIDER", "pygaze"),
                },
            },
        )

    def emit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        context = active_context()
        self.event_queue.put(
            {
                "session_id": self.session_id,
                "source": SOURCE,
                "event_type": event_type,
                "timestamp": now_iso(),
                "context": context,
                "payload": payload,
            }
        )

    def upload_loop(self) -> None:
        while not self.stop_event.is_set() or not self.event_queue.empty():
            try:
                item = self.event_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            try:
                self.post_json("/events", item)
            except Exception as error:
                print(f"[desktop-agent] upload failed: {error}")
                time.sleep(1.0)
                self.event_queue.put(item)

    def context_loop(self) -> None:
        while not self.stop_event.is_set():
            current = active_context()
            if current != self.last_active_context:
                self.last_active_context = current
                self.emit_event("active_window_changed", current)
            time.sleep(1.0)

    def handle_move(self, x: int, y: int) -> None:
        now = time.time()
        if now - self.last_mouse_move_at < 0.2:
            return
        self.last_mouse_move_at = now
        self.emit_event(
            "mouse_move",
            {
                "screen_x": x,
                "screen_y": y,
            },
        )

    def handle_click(self, x: int, y: int, button: Any, pressed: bool) -> None:
        self.emit_event(
            "mouse_click" if pressed else "mouse_up",
            {
                "screen_x": x,
                "screen_y": y,
                "button": str(button),
                "pressed": pressed,
            },
        )

    def handle_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        self.emit_event(
            "scroll",
            {
                "screen_x": x,
                "screen_y": y,
                "delta_x": dx,
                "delta_y": dy,
            },
        )

    def handle_key_press(self, key: Any) -> None:
        try:
            key_name = key.char if key.char else str(key)
        except AttributeError:
            key_name = str(key)

        self.emit_event(
            "key_input",
            {
                "key": key_name,
            },
        )

    def start_listeners(self) -> None:
        self.mouse_listener = mouse.Listener(
            on_move=self.handle_move,
            on_click=self.handle_click,
            on_scroll=self.handle_scroll,
        )
        self.keyboard_listener = keyboard.Listener(on_press=self.handle_key_press)
        self.mouse_listener.start()
        self.keyboard_listener.start()

    def stop_listeners(self) -> None:
        if self.mouse_listener:
            self.mouse_listener.stop()
        if self.keyboard_listener:
            self.keyboard_listener.stop()

    def start(self) -> None:
        self.create_session()
        self.emit_event("session_started", {"source": SOURCE})
        self.uploader_thread.start()
        self.context_thread.start()
        self.start_listeners()
        self.gaze_provider.start()

    def stop(self) -> None:
        self.gaze_provider.stop()
        self.emit_event("session_stopped", {"source": SOURCE})
        self.stop_listeners()
        time.sleep(0.2)
        self.stop_event.set()
        self.uploader_thread.join(timeout=1.0)
        self.context_thread.join(timeout=1.0)


def main() -> None:
    session_id = load_or_create_session_id()
    agent = DesktopAgent(session_id=session_id)

    def shutdown(*_args: Any) -> None:
        agent.stop()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    agent.start()
    print(f"[desktop-agent] running with session_id={session_id}")

    while True:
        time.sleep(1.0)


if __name__ == "__main__":
    main()
