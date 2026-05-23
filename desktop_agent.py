import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from math import hypot
from pathlib import Path
from typing import Any

import requests
from desktop_bridge import LocalGazeBridge
from desktop_cv_gaze import OpenCvMediaPipeGazeProvider
from gaze_contract import (
    DEFAULT_GAZE_SAMPLE_INTERVAL_MS,
    GAZE_CONTRACT_VERSION,
    gaze_lost_payload,
    gaze_point_payload,
    provider_details,
    status_payload,
)
from pynput import keyboard, mouse


API_URL = os.getenv("UX_API_URL", "http://localhost:8000/api")
STATE_FILE = Path(os.getenv("UX_AGENT_STATE_FILE", ".desktop_agent_state.json"))
SOURCE = "desktop_agent"
EVENT_BATCH_SIZE = 20
EVENT_FLUSH_INTERVAL_MS = 1.0
LOG_WINDOW_ENABLED = os.getenv("UX_AGENT_LOG_WINDOW", "1") != "0"
DEFAULT_GAZE_DOT_ENABLED = os.getenv("UX_AGENT_GAZE_DOT_ENABLED", "1") != "0"
DEFAULT_GAZE_DOT_SIZE = max(12, int(os.getenv("UX_AGENT_GAZE_DOT_SIZE", "28")))
DEFAULT_GAZE_DOT_COLOR = os.getenv("UX_AGENT_GAZE_DOT_COLOR", "#ff2d55")
DEFAULT_GAZE_UI_POLL_MS = max(8, int(os.getenv("UX_AGENT_GAZE_UI_POLL_MS", "16")))
DEFAULT_DESKTOP_GAZE_SAMPLE_INTERVAL_MS = max(
    16, int(os.getenv("UX_DESKTOP_GAZE_SAMPLE_INTERVAL_MS", "75"))
)
DEFAULT_CURSOR_SAMPLE_INTERVAL_MS = max(
    25, int(os.getenv("UX_CURSOR_SAMPLE_INTERVAL_MS", "100"))
)
GAZE_CURSOR_MAX_PAIR_AGE_MS = float(os.getenv("UX_GAZE_CURSOR_MAX_PAIR_AGE_MS", "1000"))
GAZE_CURSOR_CLOSE_THRESHOLD_PX = float(os.getenv("UX_GAZE_CURSOR_CLOSE_THRESHOLD_PX", "140"))
GAZE_CURSOR_FAR_THRESHOLD_PX = float(os.getenv("UX_GAZE_CURSOR_FAR_THRESHOLD_PX", "360"))
RAGE_CLICK_WINDOW_MS = float(os.getenv("UX_RAGE_CLICK_WINDOW_MS", "1200"))
RAGE_CLICK_RADIUS_PX = float(os.getenv("UX_RAGE_CLICK_RADIUS_PX", "45"))
RAGE_CLICK_MIN_CLICKS = int(os.getenv("UX_RAGE_CLICK_MIN_CLICKS", "3"))
CLICK_WITHOUT_GAZE_MAX_AGE_MS = float(os.getenv("UX_CLICK_WITHOUT_GAZE_MAX_AGE_MS", "1500"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def classify_gaze_cursor_distance(distance_px: float) -> str:
    if distance_px <= GAZE_CURSOR_CLOSE_THRESHOLD_PX:
        return "close"
    if distance_px >= GAZE_CURSOR_FAR_THRESHOLD_PX:
        return "far"
    return "medium"


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


def screen_size() -> tuple[int, int]:
    width = int(os.getenv("UX_SCREEN_WIDTH", "1920"))
    height = int(os.getenv("UX_SCREEN_HEIGHT", "1080"))
    return width, height


class LogWindow:
    def __init__(self, enabled: bool = True, max_lines: int = 250) -> None:
        self.enabled = enabled
        self.max_lines = max_lines
        self.queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.stop_event = threading.Event()
        self.root = None
        self.calibration_start_callback = None
        self.calibration_sample_callback = None
        self.calibration_overlay = None
        self.calibration_targets: list[dict[str, Any]] = []
        self.calibration_target_index = 0
        self.calibration_error_var = None
        self.calibration_status_var = None
        self.calibration_in_progress = False
        self.calibration_target_button = None
        self.tk = None
        self.gaze_dot_enabled = DEFAULT_GAZE_DOT_ENABLED
        self.gaze_dot_size = DEFAULT_GAZE_DOT_SIZE
        self.gaze_dot_color = DEFAULT_GAZE_DOT_COLOR
        self.gaze_dot_position: tuple[int, int] | None = None
        self.gaze_dot_window = None
        self.gaze_dot_canvas = None
        self.gaze_dot_item = None
        self.gaze_dot_visibility_var = None
        self.gaze_dot_size_var = None
        self.gaze_dot_color_var = None

    def start(self) -> None:
        return

    def stop(self) -> None:
        self.stop_event.set()
        if self.root is not None:
            try:
                self.root.after(0, self.root.destroy)
            except Exception:
                pass

    def write(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}"
        print(f"[desktop-agent] {message}", flush=True)
        if self.enabled:
            self.queue.put({"kind": "log", "line": line})

    def set_calibration_hooks(self, start_callback, sample_callback) -> None:
        self.calibration_start_callback = start_callback
        self.calibration_sample_callback = sample_callback

    def request_calibration(self) -> None:
        if self.enabled:
            self.queue.put({"kind": "calibration_request"})

    def update_gaze_dot(self, x: float, y: float, confidence: float | None = None) -> None:
        if not self.enabled:
            return
        self.queue.put(
            {
                "kind": "gaze_dot_position",
                "x": int(round(x)),
                "y": int(round(y)),
                "confidence": confidence,
            }
        )

    def hide_gaze_dot(self) -> None:
        if self.enabled:
            self.queue.put({"kind": "gaze_dot_hide"})

    def run_forever(self) -> None:
        if not self.enabled:
            while not self.stop_event.is_set():
                time.sleep(0.2)
            return
        try:
            import tkinter as tk
            from tkinter.scrolledtext import ScrolledText
        except Exception as error:
            self.enabled = False
            print(f"[desktop-agent] log window unavailable: {error}", flush=True)
            return

        self.tk = tk

        root = tk.Tk()
        self.root = root
        root.title("UX Tracker Logs")
        root.geometry("820x420")
        text = ScrolledText(root, wrap="word", font=("Menlo", 11))
        text.pack(fill="both", expand=True)
        text.configure(state="disabled")

        controls = tk.Frame(root)
        controls.pack(fill="x")
        tk.Button(
            controls,
            text="Start Desktop Calibration",
            command=self._start_calibration_overlay,
        ).pack(side="left", padx=8, pady=8)
        self.gaze_dot_visibility_var = tk.BooleanVar(value=self.gaze_dot_enabled)
        tk.Checkbutton(
            controls,
            text="Show gaze dot",
            variable=self.gaze_dot_visibility_var,
            command=self._toggle_gaze_dot,
        ).pack(side="left", padx=(8, 0))
        tk.Label(controls, text="Size").pack(side="left", padx=(14, 4))
        self.gaze_dot_size_var = tk.IntVar(value=self.gaze_dot_size)
        tk.Scale(
            controls,
            from_=12,
            to=80,
            orient="horizontal",
            variable=self.gaze_dot_size_var,
            showvalue=True,
            length=180,
            command=self._change_gaze_dot_size,
        ).pack(side="left", padx=(0, 8))
        tk.Label(controls, text="Color").pack(side="left", padx=(8, 4))
        self.gaze_dot_color_var = tk.StringVar(value=self.gaze_dot_color)
        color_entry = tk.Entry(controls, textvariable=self.gaze_dot_color_var, width=10)
        color_entry.pack(side="left", padx=(0, 4))
        color_entry.bind("<Return>", self._apply_gaze_dot_color)
        tk.Button(
            controls,
            text="Apply",
            command=self._apply_gaze_dot_color,
        ).pack(side="left")
        self._ensure_gaze_dot_window()
        self._render_gaze_dot()

        def append_line(line: str) -> None:
            text.configure(state="normal")
            text.insert("end", line + "\n")
            total_lines = int(text.index("end-1c").split(".")[0])
            if total_lines > self.max_lines:
                trim_to = total_lines - self.max_lines
                text.delete("1.0", f"{trim_to + 1}.0")
            text.see("end")
            text.configure(state="disabled")

        def consume_message(message: dict[str, Any]) -> None:
            kind = message.get("kind")
            if kind == "log":
                append_line(message["line"])
                return
            if kind == "calibration_request":
                self._start_calibration_overlay()
                return
            if kind == "gaze_dot_position":
                self.gaze_dot_position = (message["x"], message["y"])
                self._render_gaze_dot()
                return
            if kind == "gaze_dot_hide":
                self.gaze_dot_position = None
                self._render_gaze_dot()
                return

        def poll_queue() -> None:
            while not self.queue.empty():
                consume_message(self.queue.get())
            if self.stop_event.is_set():
                root.destroy()
                return
            root.after(DEFAULT_GAZE_UI_POLL_MS, poll_queue)

        root.after(DEFAULT_GAZE_UI_POLL_MS, poll_queue)
        root.mainloop()

    def _ensure_gaze_dot_window(self) -> None:
        if self.tk is None or self.root is None or self.gaze_dot_window is not None:
            return
        window = self.tk.Toplevel(self.root)
        window.withdraw()
        window.overrideredirect(True)
        window.attributes("-topmost", True)
        try:
            window.attributes("-alpha", 0.9)
        except Exception:
            pass
        try:
            window.attributes("-transparentcolor", "white")
        except Exception:
            pass
        window.configure(bg="white")
        canvas = self.tk.Canvas(
            window,
            width=self.gaze_dot_size,
            height=self.gaze_dot_size,
            bg="white",
            highlightthickness=0,
            bd=0,
        )
        canvas.pack(fill="both", expand=True)
        self.gaze_dot_window = window
        self.gaze_dot_canvas = canvas
        self.gaze_dot_item = None

    def _toggle_gaze_dot(self) -> None:
        if self.gaze_dot_visibility_var is not None:
            self.gaze_dot_enabled = bool(self.gaze_dot_visibility_var.get())
        self._render_gaze_dot()

    def _change_gaze_dot_size(self, _value: Any = None) -> None:
        if self.gaze_dot_size_var is not None:
            self.gaze_dot_size = max(12, int(self.gaze_dot_size_var.get()))
        self._render_gaze_dot()

    def _apply_gaze_dot_color(self, _event: Any = None) -> None:
        if self.gaze_dot_color_var is None:
            return
        color = self.gaze_dot_color_var.get().strip() or DEFAULT_GAZE_DOT_COLOR
        if not color.startswith("#"):
            color = f"#{color}"
        if len(color) != 7:
            self.write(f"invalid gaze dot color: {color}")
            if self.gaze_dot_color_var is not None:
                self.gaze_dot_color_var.set(self.gaze_dot_color)
            return
        self.gaze_dot_color = color
        self._render_gaze_dot()

    def _render_gaze_dot(self) -> None:
        if self.gaze_dot_window is None or self.gaze_dot_canvas is None:
            return
        if not self.gaze_dot_enabled or self.gaze_dot_position is None or self.calibration_in_progress:
            self.gaze_dot_window.withdraw()
            return

        size = self.gaze_dot_size
        x, y = self.gaze_dot_position
        self.gaze_dot_window.geometry(f"{size}x{size}+{x - size // 2}+{y - size // 2}")
        self.gaze_dot_canvas.configure(width=size, height=size)
        self.gaze_dot_canvas.delete("all")
        inset = 3
        self.gaze_dot_canvas.create_oval(
            inset,
            inset,
            size - inset,
            size - inset,
            fill=self.gaze_dot_color,
            outline="white",
            width=2,
        )
        self.gaze_dot_window.deiconify()

    def _start_calibration_overlay(self) -> None:
        if self.tk is None:
            self.write("desktop calibration unavailable: tkinter not initialized")
            return
        if not self.root or self.calibration_in_progress:
            return
        if not self.calibration_start_callback or not self.calibration_sample_callback:
            self.write("desktop calibration unavailable: missing callbacks")
            return

        try:
            status = self.calibration_start_callback()
        except Exception as error:
            self.write(f"desktop calibration failed to start: {error}")
            return

        self.calibration_in_progress = True
        self.calibration_targets = list(status.get("targets") or [])
        if not self.calibration_targets:
            self.calibration_targets = [
                {"x": 0.08, "y": 0.08},
                {"x": 0.92, "y": 0.08},
                {"x": 0.5, "y": 0.5},
                {"x": 0.08, "y": 0.92},
                {"x": 0.92, "y": 0.92},
            ]
        self.calibration_target_index = 0
        self.write("desktop calibration started")
        self._render_gaze_dot()

        overlay = self.tk.Toplevel(self.root)
        self.calibration_overlay = overlay
        overlay.title("Desktop Calibration")
        overlay.configure(bg="black")
        overlay.attributes("-fullscreen", True)
        overlay.attributes("-topmost", True)
        overlay.protocol("WM_DELETE_WINDOW", self._close_calibration_overlay)

        title = self.tk.Label(
            overlay,
            text="Desktop Calibration",
            fg="white",
            bg="black",
            font=("Helvetica", 28, "bold"),
        )
        title.pack(pady=(36, 10))

        subtitle = self.tk.Label(
            overlay,
            text="Look at the green point, then click it once.",
            fg="white",
            bg="black",
            font=("Helvetica", 18),
        )
        subtitle.pack()

        self.calibration_status_var = self.tk.StringVar()
        self.calibration_error_var = self.tk.StringVar()
        status_label = self.tk.Label(
            overlay,
            textvariable=self.calibration_status_var,
            fg="white",
            bg="black",
            font=("Helvetica", 16),
        )
        status_label.pack(pady=(16, 8))
        error_label = self.tk.Label(
            overlay,
            textvariable=self.calibration_error_var,
            fg="#ff8a80",
            bg="black",
            font=("Helvetica", 14),
        )
        error_label.pack()

        self._render_calibration_target()

    def _close_calibration_overlay(self) -> None:
        self.calibration_in_progress = False
        if self.calibration_overlay is not None:
            try:
                self.calibration_overlay.destroy()
            except Exception:
                pass
        self.calibration_overlay = None
        self.calibration_target_button = None
        self._render_gaze_dot()

    def _render_calibration_target(self) -> None:
        if not self.calibration_overlay:
            return
        if self.calibration_target_button is not None:
            try:
                self.calibration_target_button.destroy()
            except Exception:
                pass
            self.calibration_target_button = None

        if self.calibration_target_index >= len(self.calibration_targets):
            self.write("desktop calibration completed")
            self._close_calibration_overlay()
            return

        target = self.calibration_targets[self.calibration_target_index]
        width = self.calibration_overlay.winfo_screenwidth()
        height = self.calibration_overlay.winfo_screenheight()
        x = int(width * float(target.get("x", 0.5)))
        y = int(height * float(target.get("y", 0.5)))
        if self.calibration_status_var is not None:
            self.calibration_status_var.set(
                f"Point {self.calibration_target_index + 1}/{len(self.calibration_targets)}"
            )
        if self.calibration_error_var is not None:
            self.calibration_error_var.set("")

        button = self.tk.Button(
            self.calibration_overlay,
            text="",
            bg="#00c853",
            activebackground="#00c853",
            relief="flat",
            bd=0,
            highlightthickness=2,
            highlightbackground="white",
            command=lambda: self._submit_calibration_point(target, x, y),
        )
        button.place(x=x - 18, y=y - 18, width=36, height=36)
        self.calibration_target_button = button

    def _submit_calibration_point(self, target: dict[str, Any], x: int, y: int) -> None:
        if not self.calibration_sample_callback:
            return
        try:
            status = self.calibration_sample_callback(
                float(target.get("x", 0.5)),
                float(target.get("y", 0.5)),
                float(x),
                float(y),
            )
        except Exception as error:
            if self.calibration_error_var is not None:
                self.calibration_error_var.set(str(error))
            self.write(f"desktop calibration sample failed: {error}")
            return

        self.write(
            f"desktop calibration sample saved: {self.calibration_target_index + 1}/{len(self.calibration_targets)}"
        )
        self.calibration_target_index += 1
        if self.calibration_target_index >= len(self.calibration_targets):
            self.write("desktop calibration saved to local profile")
        self._render_calibration_target()


class GazeProvider:
    provider_name = "none"
    provider_type = "disabled"
    sample_interval_ms = DEFAULT_DESKTOP_GAZE_SAMPLE_INTERVAL_MS

    def __init__(self, emit_event):
        self.emit_event = emit_event

    def emit_status(self, status: str, **extra: Any) -> None:
        self.emit_event(
            "gaze_provider_status",
            status_payload(
                self.provider_name,
                self.provider_type,
                status,
                sample_interval_ms=self.sample_interval_ms,
                **extra,
            ),
        )

    def emit_lost(self, reason: str, **extra: Any) -> None:
        self.emit_event(
            "gaze_lost",
            gaze_lost_payload(
                self.provider_name,
                self.provider_type,
                reason,
                sample_interval_ms=self.sample_interval_ms,
                **extra,
            ),
        )

    def emit_point(
        self,
        screen_x: float,
        screen_y: float,
        confidence: float | None,
        **extra: Any,
    ) -> None:
        width, height = screen_size()
        self.emit_event(
            "gaze_point",
            gaze_point_payload(
                self.provider_name,
                self.provider_type,
                screen_x,
                screen_y,
                confidence,
                viewport_width=width,
                viewport_height=height,
                sample_interval_ms=self.sample_interval_ms,
                **extra,
            ),
        )

    def start(self) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError


class NullGazeProvider(GazeProvider):
    provider_name = "none"
    provider_type = "disabled"

    def start(self) -> None:
        self.emit_status("disabled")
        self.emit_lost("provider_disabled")

    def stop(self) -> None:
        self.emit_status("stopped")


class PyGazeProvider(GazeProvider):
    provider_name = "pygaze"
    provider_type = "native"

    def __init__(self, emit_event):
        super().__init__(emit_event)
        self.thread = None
        self.stop_event = threading.Event()

    def start(self) -> None:
        self.emit_status("starting")
        try:
            from pygaze import libtime  # type: ignore
        except Exception as error:
            self.emit_status("unavailable", message=str(error))
            self.emit_lost("provider_unavailable", message=str(error))
            return

        def run() -> None:
            while not self.stop_event.is_set():
                self.emit_status("running", clock_ms=libtime.get_time())
                time.sleep(1.0)

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        self.emit_status("running")

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        self.emit_status("stopped")


class MouseProxyGazeProvider(GazeProvider):
    provider_name = "mouse_proxy"
    provider_type = "proxy"
    sample_interval_ms = DEFAULT_DESKTOP_GAZE_SAMPLE_INTERVAL_MS

    def __init__(self, emit_event):
        super().__init__(emit_event)
        self.thread = None
        self.stop_event = threading.Event()
        self.mouse_controller = mouse.Controller()
        self.last_position: tuple[float, float] | None = None

    def start(self) -> None:
        self.emit_status("starting")

        def run() -> None:
            while not self.stop_event.is_set():
                try:
                    position = self.mouse_controller.position
                except Exception as error:
                    self.emit_status("unavailable", message=str(error))
                    self.emit_lost("mouse_position_unavailable", message=str(error))
                    time.sleep(self.sample_interval_ms / 1000)
                    continue

                screen_x = float(position[0])
                screen_y = float(position[1])
                confidence = 0.2 if self.last_position == position else 0.35
                self.emit_point(
                    screen_x,
                    screen_y,
                    confidence,
                    mode="proxy",
                )
                self.last_position = position
                time.sleep(self.sample_interval_ms / 1000)

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        self.emit_status("running", mode="proxy")

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
        self.emit_status("stopped")


class OpenCvGazeProvider(GazeProvider):
    provider_name = "opencv_mediapipe"
    provider_type = "native_cv"

    def __init__(self, emit_event):
        super().__init__(emit_event)
        self.runtime = OpenCvMediaPipeGazeProvider(
            emit_point=self.emit_point,
            emit_status=self.emit_status,
            emit_lost=self.emit_lost,
            sample_interval_ms=self.sample_interval_ms,
        )

    def start(self) -> None:
        self.runtime.start()

    def stop(self) -> None:
        self.runtime.stop()


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
        self.cursor_thread = threading.Thread(target=self.cursor_loop, daemon=True)
        self.cursor_controller = mouse.Controller()
        self.latest_gaze_point: dict[str, Any] | None = None
        self.latest_cursor_point: dict[str, Any] | None = None
        self.recent_clicks: list[dict[str, Any]] = []
        self.emitted_friction_keys: set[str] = set()
        self.metrics_lock = threading.RLock()
        self.log_window = LogWindow(enabled=LOG_WINDOW_ENABLED)
        self.bridge = LocalGazeBridge(self.session_id)
        self.gaze_provider = self.build_gaze_provider()
        self.gaze_point_log_count = 0
        self.last_logged_gaze_at = 0.0
        self.last_logged_gaze_cursor_at = 0.0
        self.log_window.set_calibration_hooks(
            self.start_calibration,
            self.submit_calibration_sample,
        )
        self.bridge.set_machine_profile(self.describe_machine())
        self.bridge.set_calibration_status(self.get_calibration_status())
        self.bridge.set_calibration_handlers(
            self.start_calibration,
            self.submit_calibration_sample,
        )

    def log(self, message: str) -> None:
        self.log_window.write(message)

    def build_gaze_provider(self) -> GazeProvider:
        provider_name = os.getenv("UX_GAZE_PROVIDER", "opencv_mediapipe").lower()
        if provider_name == "opencv_mediapipe":
            return OpenCvGazeProvider(self.emit_event)
        if provider_name == "mouse_proxy":
            return MouseProxyGazeProvider(self.emit_event)
        if provider_name == "pygaze":
            return PyGazeProvider(self.emit_event)
        return NullGazeProvider(self.emit_event)

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
                    "gaze_provider": os.getenv("UX_GAZE_PROVIDER", "opencv_mediapipe"),
                    "gaze_contract_version": GAZE_CONTRACT_VERSION,
                    "gaze_provider_details": provider_details(
                        self.gaze_provider.provider_name,
                        self.gaze_provider.provider_type,
                        self.gaze_provider.sample_interval_ms,
                    ),
                    "machine_profile": self.describe_machine(),
                },
            },
        )
        self.log(f"session created: {self.session_id}")

    def emit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        timestamp = now_iso()
        if event_type not in {"gaze_cursor_distance", "friction_marker"}:
            self.bridge.update(event_type, payload, timestamp)
        context = self.last_active_context or active_context()
        event = {
            "session_id": self.session_id,
            "source": SOURCE,
            "event_type": event_type,
            "timestamp": timestamp,
            "context": context,
            "payload": payload,
        }
        self.event_queue.put(event)
        self.log_event(event_type, payload)
        self.update_live_desktop_metrics(event)

    def event_point(self, event: dict[str, Any]) -> tuple[float, float] | None:
        payload = event.get("payload", {})
        x = payload.get("screen_x", payload.get("x"))
        y = payload.get("screen_y", payload.get("y"))
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return None
        return float(x), float(y)

    def friction_key(self, marker_type: str, timestamp: datetime, point: tuple[float, float]) -> str:
        bucket = int(timestamp.timestamp() * 1000 // 1000)
        return f"{marker_type}:{bucket}:{round(point[0] / 20)}:{round(point[1] / 20)}"

    def update_live_desktop_metrics(self, event: dict[str, Any]) -> None:
        event_type = event.get("event_type")
        if event_type not in {"gaze_point", "cursor_position", "mouse_move", "mouse_click"}:
            return

        point = self.event_point(event)
        if not point:
            return

        timestamp = parse_iso(event["timestamp"])
        with self.metrics_lock:
            if event_type == "gaze_point":
                self.latest_gaze_point = {"timestamp": timestamp, "point": point}
            if event_type in {"cursor_position", "mouse_move"}:
                self.latest_cursor_point = {"timestamp": timestamp, "point": point}

            if event_type in {"gaze_point", "cursor_position", "mouse_move"}:
                self.emit_live_gaze_cursor_metric(timestamp, event.get("context", {}))
            if event_type == "mouse_click":
                self.emit_live_click_friction(timestamp, point, event.get("context", {}))

    def emit_live_gaze_cursor_metric(self, timestamp: datetime, context: dict[str, Any]) -> None:
        if not self.latest_gaze_point or not self.latest_cursor_point:
            return

        gaze_timestamp = self.latest_gaze_point["timestamp"]
        cursor_timestamp = self.latest_cursor_point["timestamp"]
        gaze_age_ms = abs((timestamp - gaze_timestamp).total_seconds() * 1000)
        cursor_age_ms = abs((timestamp - cursor_timestamp).total_seconds() * 1000)
        if max(gaze_age_ms, cursor_age_ms) > GAZE_CURSOR_MAX_PAIR_AGE_MS:
            return

        gaze_x, gaze_y = self.latest_gaze_point["point"]
        cursor_x, cursor_y = self.latest_cursor_point["point"]
        distance_px = hypot(gaze_x - cursor_x, gaze_y - cursor_y)
        self.emit_event(
            "gaze_cursor_distance",
            {
                "gaze_x": round(gaze_x, 2),
                "gaze_y": round(gaze_y, 2),
                "cursor_x": round(cursor_x, 2),
                "cursor_y": round(cursor_y, 2),
                "distance_px": round(distance_px, 2),
                "gaze_age_ms": round(gaze_age_ms, 2),
                "cursor_age_ms": round(cursor_age_ms, 2),
                "clarity_signal": classify_gaze_cursor_distance(distance_px),
                "close_threshold_px": GAZE_CURSOR_CLOSE_THRESHOLD_PX,
                "far_threshold_px": GAZE_CURSOR_FAR_THRESHOLD_PX,
                "detector_source": "desktop_agent_live",
                "context_app_name": context.get("app_name"),
                "context_window_title": context.get("window_title"),
            },
        )

    def emit_live_click_friction(
        self,
        timestamp: datetime,
        point: tuple[float, float],
        context: dict[str, Any],
    ) -> None:
        self.recent_clicks.append({"timestamp": timestamp, "point": point})
        self.recent_clicks = [
            click
            for click in self.recent_clicks
            if (timestamp - click["timestamp"]).total_seconds() * 1000 <= RAGE_CLICK_WINDOW_MS
        ]
        nearby_clicks = [
            click
            for click in self.recent_clicks
            if hypot(point[0] - click["point"][0], point[1] - click["point"][1]) <= RAGE_CLICK_RADIUS_PX
        ]
        if len(nearby_clicks) >= RAGE_CLICK_MIN_CLICKS:
            key = self.friction_key("rage_click", timestamp, point)
            if key not in self.emitted_friction_keys:
                self.emitted_friction_keys.add(key)
                self.emit_event(
                    "friction_marker",
                    {
                        "marker_type": "rage_click",
                        "severity": "high",
                        "click_count": len(nearby_clicks),
                        "window_ms": RAGE_CLICK_WINDOW_MS,
                        "radius_px": RAGE_CLICK_RADIUS_PX,
                        "screen_x": round(point[0], 2),
                        "screen_y": round(point[1], 2),
                        "reason": "Repeated clicks in a small area.",
                        "detector_source": "desktop_agent_live",
                        "context_app_name": context.get("app_name"),
                        "context_window_title": context.get("window_title"),
                    },
                )

        if not self.latest_gaze_point:
            return

        gaze_timestamp = self.latest_gaze_point["timestamp"]
        gaze_x, gaze_y = self.latest_gaze_point["point"]
        gaze_age_ms = abs((timestamp - gaze_timestamp).total_seconds() * 1000)
        gaze_distance_px = hypot(point[0] - gaze_x, point[1] - gaze_y)
        if gaze_age_ms > CLICK_WITHOUT_GAZE_MAX_AGE_MS or gaze_distance_px <= GAZE_CURSOR_FAR_THRESHOLD_PX:
            return

        key = self.friction_key("click_without_recent_gaze", timestamp, point)
        if key in self.emitted_friction_keys:
            return
        self.emitted_friction_keys.add(key)
        self.emit_event(
            "friction_marker",
            {
                "marker_type": "click_without_recent_gaze",
                "severity": "medium",
                "screen_x": round(point[0], 2),
                "screen_y": round(point[1], 2),
                "gaze_x": round(gaze_x, 2),
                "gaze_y": round(gaze_y, 2),
                "gaze_age_ms": round(gaze_age_ms, 2),
                "gaze_distance_px": round(gaze_distance_px, 2),
                "reason": "Click was far from the latest gaze point.",
                "detector_source": "desktop_agent_live",
                "context_app_name": context.get("app_name"),
                "context_window_title": context.get("window_title"),
            },
        )

    def log_event(self, event_type: str, payload: dict[str, Any]) -> None:
        if event_type == "gaze_provider_status":
            status = payload.get("status", "unknown")
            message = payload.get("message")
            phase = payload.get("phase")
            model_path = payload.get("model_path")
            calibration_required = payload.get("calibration_required")
            suffix = f", calibration_required={calibration_required}" if calibration_required is not None else ""
            if phase:
                suffix += f", phase={phase}"
            if model_path:
                suffix += f", model={model_path}"
            extra = f", message={message}" if message else ""
            self.log(f"gaze provider status: {status}{suffix}{extra}")
            if status == "running" and calibration_required:
                self.log_window.request_calibration()
            return
        if event_type == "gaze_lost":
            self.log_window.hide_gaze_dot()
            self.log(
                f"gaze lost: reason={payload.get('reason', 'unknown')}, confidence={payload.get('confidence')}"
            )
            return
        if event_type == "active_window_changed":
            self.log(
                f"active window: app={payload.get('app_name') or 'unknown'}, title={payload.get('window_title') or 'unknown'}"
            )
            return
        if event_type == "session_started":
            self.log("tracking started")
            return
        if event_type == "session_stopped":
            self.log("tracking stopped")
            return
        if event_type == "gaze_cursor_distance":
            now = time.time()
            if now - self.last_logged_gaze_cursor_at >= 2.0:
                self.last_logged_gaze_cursor_at = now
                self.log(
                    f"gaze/cursor distance: {payload.get('distance_px')}px, "
                    f"signal={payload.get('clarity_signal')}"
                )
            return
        if event_type == "friction_marker":
            self.log(
                f"friction marker: {payload.get('marker_type')}, "
                f"severity={payload.get('severity')}, reason={payload.get('reason')}"
            )
            return
        if event_type == "gaze_point":
            screen_x = float(payload.get("screen_x", 0.0))
            screen_y = float(payload.get("screen_y", 0.0))
            self.log_window.update_gaze_dot(
                screen_x,
                screen_y,
                payload.get("confidence"),
            )
            self.gaze_point_log_count += 1
            now = time.time()
            if self.gaze_point_log_count <= 3 or now - self.last_logged_gaze_at >= 2.0:
                self.last_logged_gaze_at = now
                self.log(
                    "gaze sample ok: "
                    f"x={round(screen_x, 1)}, "
                    f"y={round(screen_y, 1)}, "
                    f"confidence={payload.get('confidence')}, "
                    f"calibration={payload.get('calibration_source')}, "
                    f"raw_x={payload.get('raw_eye_ratio_x')}, "
                    f"raw_y={payload.get('raw_eye_ratio_y')}, "
                    f"left_x={payload.get('left_eye_ratio_x')}, "
                    f"right_x={payload.get('right_eye_ratio_x')}, "
                    f"gaze_yaw={payload.get('gaze_yaw_deg')}, "
                    f"gaze_pitch={payload.get('gaze_pitch_deg')}, "
                    f"head_yaw={payload.get('head_yaw_deg')}, "
                    f"norm_x={payload.get('projected_normalized_x')}, "
                    f"norm_y={payload.get('projected_normalized_y')}"
                )

    def describe_machine(self) -> dict[str, Any]:
        if hasattr(self.gaze_provider, "get_machine_profile"):
            return self.gaze_provider.get_machine_profile()
        return {
            "hostname": os.uname().nodename if hasattr(os, "uname") else os.name,
        }

    def get_calibration_status(self) -> dict[str, Any]:
        if hasattr(self.gaze_provider, "get_calibration_status"):
            return self.gaze_provider.get_calibration_status()
        return {
            "active": False,
            "required": False,
            "targets": [],
            "samples_collected": 0,
        }

    def start_calibration(self) -> dict[str, Any]:
        if hasattr(self.gaze_provider, "start_calibration"):
            status = self.gaze_provider.start_calibration()
            self.bridge.set_calibration_status(status)
            return status
        return self.get_calibration_status()

    def submit_calibration_sample(
        self, target_x: float, target_y: float, screen_x: float, screen_y: float
    ) -> dict[str, Any]:
        if hasattr(self.gaze_provider, "submit_calibration_sample"):
            status = self.gaze_provider.submit_calibration_sample(
                target_x,
                target_y,
                screen_x,
                screen_y,
            )
            self.bridge.set_calibration_status(status)
            return status
        return self.get_calibration_status()

    def upload_loop(self) -> None:
        pending_batch: list[dict[str, Any]] = []
        last_flush_at = time.time()

        while not self.stop_event.is_set() or not self.event_queue.empty() or pending_batch:
            try:
                item = self.event_queue.get(timeout=0.5)
                pending_batch.append(item)
            except queue.Empty:
                item = None

            should_flush = bool(pending_batch) and (
                len(pending_batch) >= EVENT_BATCH_SIZE
                or self.stop_event.is_set()
                or time.time() - last_flush_at >= EVENT_FLUSH_INTERVAL_MS
                or item is None
            )
            if not should_flush:
                continue

            try:
                self.post_json("/events", {"events": pending_batch})
                self.log(f"uploaded {len(pending_batch)} events")
                pending_batch = []
                last_flush_at = time.time()
            except Exception as error:
                self.log(f"upload failed: {error}")
                time.sleep(1.0)
                for queued_event in pending_batch:
                    self.event_queue.put(queued_event)
                pending_batch = []

    def context_loop(self) -> None:
        while not self.stop_event.is_set():
            current = active_context()
            if current != self.last_active_context:
                self.last_active_context = current
                self.emit_event("active_window_changed", current)
            time.sleep(1.0)

    def cursor_loop(self) -> None:
        sample_interval_seconds = DEFAULT_CURSOR_SAMPLE_INTERVAL_MS / 1000
        while not self.stop_event.is_set():
            try:
                position = self.cursor_controller.position
                self.emit_event(
                    "cursor_position",
                    {
                        "screen_x": int(position[0]),
                        "screen_y": int(position[1]),
                        "sample_interval_ms": DEFAULT_CURSOR_SAMPLE_INTERVAL_MS,
                        "active_sample": True,
                    },
                )
            except Exception as error:
                self.log(f"cursor sample failed: {error}")
            time.sleep(sample_interval_seconds)

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
        self.log_window.start()
        self.log(f"starting desktop agent with gaze provider={self.gaze_provider.provider_name}")
        self.create_session()
        self.bridge.start()
        self.log(f"local gaze bridge at http://{self.bridge.host}:{self.bridge.port}")
        self.emit_event("session_started", {"source": SOURCE})
        self.uploader_thread.start()
        self.context_thread.start()
        self.cursor_thread.start()
        self.start_listeners()
        self.gaze_provider.start()

    def stop(self) -> None:
        self.gaze_provider.stop()
        self.emit_event("session_stopped", {"source": SOURCE})
        self.stop_listeners()
        time.sleep(0.2)
        self.stop_event.set()
        self.uploader_thread.join(timeout=2.0)
        self.context_thread.join(timeout=1.0)
        self.cursor_thread.join(timeout=1.0)
        self.bridge.stop()
        self.log_window.stop()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(line_buffering=True)

    session_id = load_or_create_session_id()
    agent = DesktopAgent(session_id=session_id)

    def shutdown(*_args: Any) -> None:
        agent.stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    agent.start()
    agent.log(f"running with session_id={session_id}")

    agent.log_window.run_forever()


if __name__ == "__main__":
    main()
