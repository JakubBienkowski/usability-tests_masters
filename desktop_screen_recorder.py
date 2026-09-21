from __future__ import annotations

import base64
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any

import requests


def resolve_media_binary(name: str) -> str | None:
    if os.name == "nt":
        chocolatey_binary = (
            Path(os.getenv("ChocolateyInstall", r"C:\ProgramData\chocolatey"))
            / "lib"
            / "ffmpeg"
            / "tools"
            / "ffmpeg"
            / "bin"
            / f"{name}.exe"
        )
        if chocolatey_binary.is_file():
            return str(chocolatey_binary)
    return shutil.which(name)


class DesktopScreenRecorder:
    def __init__(self, api_url: str, output_dir: Path) -> None:
        self.api_url = api_url.rstrip("/")
        self.output_dir = output_dir
        self.process: subprocess.Popen[bytes] | None = None
        self.session_id: str | None = None
        self.output_path: Path | None = None

    @property
    def active(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, session_id: str) -> dict[str, Any]:
        if self.active:
            raise RuntimeError("screen recorder is already active")
        ffmpeg = resolve_media_binary("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg is required for desktop screen recording")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id
        self.output_path = self.output_dir / f"{session_id}.mp4"
        command = [
            ffmpeg,
            "-y",
            "-nostats",
            "-loglevel",
            "error",
            "-f",
            "gdigrab",
            "-framerate",
            os.getenv("UX_SCREEN_RECORDING_FPS", "5"),
            "-draw_mouse",
            "1",
            "-i",
            "desktop",
            "-vf",
            "scale='min(1280,iw)':-2",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            os.getenv("UX_SCREEN_RECORDING_CRF", "28"),
            "-g",
            os.getenv("UX_SCREEN_RECORDING_GOP", "10"),
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+frag_keyframe+empty_moov+default_base_moof",
            str(self.output_path),
        ]
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=creation_flags,
        )
        time.sleep(0.5)
        if self.process.poll() is not None:
            error = (self.process.stderr.read() if self.process.stderr else b"").decode(
                errors="replace"
            )
            self.process = None
            raise RuntimeError(f"screen recorder failed to start: {error[-800:]}")
        return {"path": str(self.output_path), "mime_type": "video/mp4"}

    def stop_and_upload(self) -> dict[str, Any]:
        if not self.process or not self.session_id or not self.output_path:
            raise RuntimeError("screen recorder is not active")
        process = self.process
        if process.stdin:
            try:
                process.stdin.write(b"q\n")
                process.stdin.flush()
            except OSError:
                pass
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)
        self.process = None
        if not self.output_path.exists() or self.output_path.stat().st_size == 0:
            error = (process.stderr.read() if process.stderr else b"").decode(errors="replace")
            raise RuntimeError(f"screen recording failed: {error[-800:]}")
        ffprobe = resolve_media_binary("ffprobe")
        if not ffprobe:
            raise RuntimeError("ffprobe is required to validate desktop recordings")
        validation_deadline = time.monotonic() + 15
        last_size = -1
        stable_checks = 0
        while time.monotonic() < validation_deadline:
            size = self.output_path.stat().st_size
            probe = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=codec_name,width,height",
                    "-of",
                    "json",
                    str(self.output_path),
                ],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            stable_checks = stable_checks + 1 if size == last_size else 0
            if probe.returncode == 0 and stable_checks >= 1:
                break
            last_size = size
            time.sleep(0.5)
        else:
            raise RuntimeError("screen recording was not finalized into a playable video")
        data = self.output_path.read_bytes()
        if not data:
            raise RuntimeError("screen recording is empty")
        chunk_size = 2 * 1024 * 1024
        chunks = [data[offset : offset + chunk_size] for offset in range(0, len(data), chunk_size)]
        try:
            for index, chunk in enumerate(chunks):
                response = requests.post(
                    f"{self.api_url}/screen-recording",
                    json={
                        "session_id": self.session_id,
                        "source": "desktop_agent",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "chunk_index": index,
                        "mime_type": "video/mp4",
                        "data_base64": base64.b64encode(chunk).decode("ascii"),
                        "final": index == len(chunks) - 1,
                        "context": {},
                    },
                    timeout=30,
                )
                response.raise_for_status()
            return {
                "path": str(self.output_path),
                "size_bytes": len(data),
                "chunks": len(chunks),
                "mime_type": "video/mp4",
            }
        finally:
            self.session_id = None
            self.output_path = None
