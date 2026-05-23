from __future__ import annotations

import asyncio
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


class GazeBridgeState:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.lock = threading.Lock()
        self.sequence = 0
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

    def update(self, event_type: str, payload: dict[str, Any], timestamp: str) -> None:
        with self.lock:
            self.sequence += 1
            event = {
                "sequence": self.sequence,
                "session_id": self.session_id,
                "event_type": event_type,
                "timestamp": timestamp,
                "payload": payload,
            }
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
                "provider_status": dict(self.provider_status),
                "last_event": dict(self.last_event) if self.last_event else None,
                "machine_profile": dict(self.machine_profile),
                "calibration_status": dict(self.calibration_status),
            }

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


def create_bridge_app(state: GazeBridgeState) -> FastAPI:
    app = FastAPI(title="UX Desktop Agent Local Gaze Bridge")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
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
        await websocket.accept()
        last_sequence = -1
        try:
            while True:
                snapshot = state.snapshot()
                if snapshot["sequence"] != last_sequence:
                    last_sequence = snapshot["sequence"]
                    await websocket.send_json(snapshot)
                await asyncio.sleep(0.1)
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
