from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
import os
import threading
import time
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


BRIDGE_HOST = os.getenv("UX_AGENT_BRIDGE_HOST", "127.0.0.1")
BRIDGE_PORT = int(os.getenv("UX_AGENT_BRIDGE_PORT", "8790"))
BRIDGE_BUFFER_SIZE = max(128, int(os.getenv("UX_AGENT_BRIDGE_BUFFER_SIZE", "4096")))


class GazeBridgeState:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.lock = threading.Lock()
        self.sequence = 0
        self.events: deque[dict[str, Any]] = deque(maxlen=BRIDGE_BUFFER_SIZE)
        self.dropped_events = 0
        self.last_event: dict[str, Any] | None = None
        self.provider_status: dict[str, Any] = {
            "status": "idle",
        }
        self.machine_profile: dict[str, Any] = {}
        self.calibration_status: dict[str, Any] = {
            "active": False,
            "required": False,
            "targets": [],
            "samples_collected": 0,
        }
        self.calibration_start = None
        self.calibration_submit = None
        self.session_change = None
        self.desktop_session_start = None
        self.desktop_session_stop = None

    def update(self, event_type: str, payload: dict[str, Any], timestamp: str) -> None:
        with self.lock:
            self.sequence += 1
            event = {
                "bridge_sequence": self.sequence,
                "session_id": self.session_id,
                "event_type": event_type,
                "timestamp": timestamp,
                "payload": payload,
            }
            if len(self.events) == self.events.maxlen:
                self.dropped_events += 1
            self.events.append(event)
            self.last_event = event
            if event_type == "gaze_provider_status":
                self.provider_status = payload
                if payload.get("machine_profile"):
                    self.machine_profile = payload["machine_profile"]
                if "calibration_required" in payload:
                    self.calibration_status["required"] = bool(payload["calibration_required"])

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "sequence": self.sequence,
                "session_id": self.session_id,
                "oldest_sequence": self.events[0]["bridge_sequence"] if self.events else None,
                "dropped_events": self.dropped_events,
                "provider_status": dict(self.provider_status),
                "last_event": dict(self.last_event) if self.last_event else None,
                "machine_profile": dict(self.machine_profile),
                "calibration_status": dict(self.calibration_status),
                "bridge_wall_time": datetime.now(timezone.utc).isoformat(),
                "bridge_monotonic_ns": time.monotonic_ns(),
            }

    def events_after(self, sequence: int) -> dict[str, Any]:
        with self.lock:
            events = [
                dict(event)
                for event in self.events
                if int(event["bridge_sequence"]) > sequence
            ]
            oldest = self.events[0]["bridge_sequence"] if self.events else self.sequence + 1
            return {
                "session_id": self.session_id,
                "events": events,
                "last_event": dict(events[-1]) if events else None,
                "latest_sequence": self.sequence,
                "oldest_sequence": oldest,
                "gap": bool(self.events and sequence + 1 < oldest),
                "dropped_events": self.dropped_events,
            }

    def join_session(self, session_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            self.session_id = session_id
            self.sequence = 0
            self.events.clear()
            self.last_event = None
            self.dropped_events = 0
        if self.session_change:
            self.session_change(session_id, metadata)
        return self.snapshot()

    def leave_session(self) -> dict[str, Any]:
        if self.session_change:
            self.session_change(None, {})
        with self.lock:
            self.session_id = None
            self.events.clear()
            self.last_event = None
        return self.snapshot()

    def set_machine_profile(self, machine_profile: dict[str, Any]) -> None:
        with self.lock:
            self.machine_profile = dict(machine_profile)

    def set_calibration_status(self, status: dict[str, Any]) -> None:
        with self.lock:
            self.calibration_status = dict(status)


class CalibrationSampleIn(BaseModel):
    target_x: float
    target_y: float
    screen_x: float
    screen_y: float


class SessionJoinIn(BaseModel):
    session_id: str
    run_id: str | None = None
    study_id: str | None = None
    participant_id: str | None = None
    mode: str = "web_desktop"


class DesktopSessionStartIn(BaseModel):
    study_id: str | None = None
    participant_id: str | None = None
    label: str | None = None


def create_bridge_app(state: GazeBridgeState) -> FastAPI:
    app = FastAPI(title="UX Desktop Agent Local Gaze Bridge")
    app.add_middleware(
        CORSMiddleware,
        # Content scripts inherit the instrumented page's Origin header. The
        # service is bound to loopback only and exposes no credentials, so all
        # page origins must be accepted for cross-site usability journeys.
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        snapshot = state.snapshot()
        return {
            "status": "ok",
            "session_id": snapshot["session_id"],
            "provider_status": snapshot["provider_status"],
            "bridge_host": BRIDGE_HOST,
            "bridge_port": BRIDGE_PORT,
            "has_event": snapshot["last_event"] is not None,
        }

    @app.get("/gaze/latest")
    async def latest_gaze() -> dict[str, Any]:
        return state.snapshot()

    @app.post("/session/join")
    async def session_join(body: SessionJoinIn) -> dict[str, Any]:
        return state.join_session(
            body.session_id,
            body.model_dump(exclude_none=True),
        )

    @app.get("/session/status")
    async def session_status() -> dict[str, Any]:
        snapshot = state.snapshot()
        return {
            "session_id": snapshot["session_id"],
            "latest_sequence": snapshot["sequence"],
            "oldest_sequence": snapshot["oldest_sequence"],
            "dropped_events": snapshot["dropped_events"],
        }

    @app.post("/session/leave")
    async def session_leave() -> dict[str, Any]:
        return state.leave_session()

    @app.post("/session/start-desktop")
    async def session_start_desktop(body: DesktopSessionStartIn) -> dict[str, Any]:
        if not state.desktop_session_start:
            raise HTTPException(status_code=503, detail="Desktop session controller unavailable")
        return state.desktop_session_start(body.model_dump(exclude_none=True))

    @app.post("/session/stop-desktop")
    async def session_stop_desktop() -> dict[str, Any]:
        if not state.desktop_session_stop:
            raise HTTPException(status_code=503, detail="Desktop session controller unavailable")
        return state.desktop_session_stop()

    @app.get("/machine-profile")
    async def machine_profile() -> dict[str, Any]:
        snapshot = state.snapshot()
        return {
            "session_id": snapshot["session_id"],
            "machine_profile": snapshot["machine_profile"],
        }

    @app.get("/calibration/status")
    async def calibration_status() -> dict[str, Any]:
        snapshot = state.snapshot()
        return snapshot["calibration_status"]

    @app.post("/calibration/start")
    async def calibration_start() -> dict[str, Any]:
        if not state.calibration_start:
            raise HTTPException(status_code=503, detail="Calibration controller unavailable")
        status = state.calibration_start()
        state.set_calibration_status(status)
        return status

    @app.post("/calibration/sample")
    async def calibration_sample(body: CalibrationSampleIn) -> dict[str, Any]:
        if not state.calibration_submit:
            raise HTTPException(status_code=503, detail="Calibration controller unavailable")
        try:
            status = state.calibration_submit(
                body.target_x,
                body.target_y,
                body.screen_x,
                body.screen_y,
            )
        except RuntimeError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        state.set_calibration_status(status)
        return status

    @app.websocket("/ws/gaze")
    async def gaze_socket(websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin", "")
        allowed_origin = (
            origin.startswith("chrome-extension://")
            or origin.startswith("http://localhost:")
            or origin.startswith("http://127.0.0.1:")
        )
        if not allowed_origin:
            await websocket.close(code=1008, reason="Origin not allowed")
            return
        await websocket.accept()
        try:
            last_sequence = int(websocket.query_params.get("after", "0"))
        except ValueError:
            last_sequence = 0
        try:
            while True:
                batch = state.events_after(last_sequence)
                if batch["events"] or batch["gap"]:
                    last_sequence = batch["latest_sequence"]
                    await websocket.send_json(batch)
                await asyncio.sleep(0.02)
        except WebSocketDisconnect:
            return

    return app


class LocalGazeBridge:
    def __init__(self, session_id: str) -> None:
        self.state = GazeBridgeState(session_id)
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None

    @property
    def host(self) -> str:
        return BRIDGE_HOST

    @property
    def port(self) -> int:
        return BRIDGE_PORT

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return

        app = create_bridge_app(self.state)
        config = uvicorn.Config(
            app,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()

        started_at = time.time()
        while time.time() - started_at < 3.0:
            if self.server.started:
                return
            time.sleep(0.05)

    def stop(self) -> None:
        if not self.server:
            return
        self.server.should_exit = True
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)

    def update(self, event_type: str, payload: dict[str, Any], timestamp: str) -> None:
        self.state.update(event_type, payload, timestamp)

    def set_machine_profile(self, machine_profile: dict[str, Any]) -> None:
        self.state.set_machine_profile(machine_profile)

    def set_calibration_status(self, status: dict[str, Any]) -> None:
        self.state.set_calibration_status(status)

    def set_calibration_handlers(self, start_callback, submit_callback) -> None:
        self.state.calibration_start = start_callback
        self.state.calibration_submit = submit_callback

    def set_session_handler(self, callback) -> None:
        self.state.session_change = callback

    def set_desktop_session_handlers(self, start_callback, stop_callback) -> None:
        self.state.desktop_session_start = start_callback
        self.state.desktop_session_stop = stop_callback
