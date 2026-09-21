from __future__ import annotations

import json
import math
import os
import socket
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from display_geometry import primary_screen_geometry


LEFT_IRIS = (474, 475, 476, 477)
RIGHT_IRIS = (469, 470, 471, 472)
LEFT_EYE_H = (33, 133)
RIGHT_EYE_H = (362, 263)
LEFT_EYE_V = (159, 145)
RIGHT_EYE_V = (386, 374)
FACE_LEFT = 234
FACE_RIGHT = 454
FACE_TOP = 10
FACE_BOTTOM = 152
NOSE_TIP = 1

DEFAULT_CAMERA_INDEX = int(os.getenv("UX_GAZE_CAMERA_INDEX", "0"))
DEFAULT_FRAME_WIDTH = int(os.getenv("UX_GAZE_FRAME_WIDTH", "1280"))
DEFAULT_FRAME_HEIGHT = int(os.getenv("UX_GAZE_FRAME_HEIGHT", "720"))
DEFAULT_SCREEN_WIDTH = int(os.getenv("UX_SCREEN_WIDTH", "1920"))
DEFAULT_SCREEN_HEIGHT = int(os.getenv("UX_SCREEN_HEIGHT", "1080"))
DEFAULT_SMOOTHING = float(os.getenv("UX_GAZE_SMOOTHING", "0.55"))
DEFAULT_ETH_XGAZE_HEAD_YAW_COMP = float(os.getenv("UX_ETH_XGAZE_HEAD_YAW_COMP", "0.85"))
DEFAULT_ETH_XGAZE_HEAD_PITCH_COMP = float(os.getenv("UX_ETH_XGAZE_HEAD_PITCH_COMP", "0.65"))
DEFAULT_ETH_XGAZE_YAW_SCALE = float(os.getenv("UX_ETH_XGAZE_YAW_SCALE", "40.0"))
DEFAULT_ETH_XGAZE_PITCH_SCALE = float(os.getenv("UX_ETH_XGAZE_PITCH_SCALE", "28.0"))
DEFAULT_INVERT_X = os.getenv("UX_GAZE_INVERT_X", "1") != "0"
DEFAULT_INVERT_Y = os.getenv("UX_GAZE_INVERT_Y", "1") != "0"
DEFAULT_X_GAIN = float(os.getenv("UX_GAZE_X_GAIN", "1.12"))
DEFAULT_Y_GAIN = float(os.getenv("UX_GAZE_Y_GAIN", "1.75"))
DEFAULT_X_OFFSET = float(os.getenv("UX_GAZE_X_OFFSET", "0.0"))
DEFAULT_Y_OFFSET = float(os.getenv("UX_GAZE_Y_OFFSET", "-0.28"))
DEFAULT_X_MIN = float(os.getenv("UX_GAZE_X_MIN", "0.32"))
DEFAULT_X_MAX = float(os.getenv("UX_GAZE_X_MAX", "0.68"))
DEFAULT_Y_MIN = float(os.getenv("UX_GAZE_Y_MIN", "0.25"))
DEFAULT_Y_MAX = float(os.getenv("UX_GAZE_Y_MAX", "0.75"))
DEFAULT_MIN_CONFIDENCE = float(os.getenv("UX_GAZE_MIN_CONFIDENCE", "0.45"))
DEFAULT_OPENNESS_MIN = float(os.getenv("UX_GAZE_OPENNESS_MIN", "0.012"))
DEFAULT_BLINK_THRESHOLD = float(os.getenv("UX_GAZE_BLINK_THRESHOLD", "0.55"))
DEFAULT_BLINK_GUARD_MS = int(os.getenv("UX_GAZE_BLINK_GUARD_MS", "180"))
DEFAULT_BLINK_EAR_THRESHOLD = float(os.getenv("UX_GAZE_BLINK_EAR_THRESHOLD", "0.16"))
DEFAULT_CALIBRATION_SAMPLES_PER_TARGET = int(os.getenv("UX_GAZE_CALIBRATION_SAMPLES_PER_TARGET", "3"))
DEFAULT_CALIBRATION_RIDGE = float(os.getenv("UX_GAZE_CALIBRATION_RIDGE", "0.08"))
DEFAULT_CALIBRATION_MAX_RMSE = float(os.getenv("UX_GAZE_CALIBRATION_MAX_RMSE", "0.18"))
DEFAULT_MAX_HEAD_YAW_DEG = float(os.getenv("UX_GAZE_MAX_HEAD_YAW_DEG", "35"))
DEFAULT_MAX_HEAD_PITCH_DEG = float(os.getenv("UX_GAZE_MAX_HEAD_PITCH_DEG", "30"))
DEFAULT_MAX_HEAD_ROLL_DEG = float(os.getenv("UX_GAZE_MAX_HEAD_ROLL_DEG", "25"))
DEFAULT_MAX_NORMALIZED_JUMP = float(os.getenv("UX_GAZE_MAX_NORMALIZED_JUMP", "0.35"))
DEFAULT_CALIBRATION_MAX_STD = float(os.getenv("UX_GAZE_CALIBRATION_MAX_STD", "0.12"))
DEFAULT_TELEMETRY_INTERVAL_S = float(os.getenv("UX_GAZE_TELEMETRY_INTERVAL_S", "5"))
CALIBRATION_PROFILE_VERSION = 3
_calibration_file_value = Path(os.getenv("UX_GAZE_CALIBRATION_FILE", ".desktop_gaze_calibration.json"))
DEFAULT_CALIBRATION_FILE = (
    _calibration_file_value
    if _calibration_file_value.is_absolute()
    else Path(__file__).resolve().parent / _calibration_file_value
)
DEFAULT_FACE_LANDMARKER_MODEL = os.getenv(
    "UX_FACE_LANDMARKER_MODEL",
    "models/face_landmarker_v2.task",
)
DEFAULT_ETH_XGAZE_MODEL_DIR = os.getenv(
    "UX_ETH_XGAZE_MODEL_DIR",
    "models/eth-xgaze",
)
DEFAULT_CALIBRATION_LOG_FILE = Path(
    os.getenv(
        "UX_GAZE_CALIBRATION_LOG_FILE",
        str(Path(__file__).resolve().parent / "logs" / "gaze_calibration.jsonl"),
    )
)
DEFAULT_GAZE_MODEL_BACKEND = os.getenv("UX_GAZE_MODEL_BACKEND", "eth_xgaze").lower()
DEFAULT_L2CS_MODEL = os.getenv(
    "UX_L2CS_MODEL",
    "models/l2cs/L2CSNet_gaze360.pkl",
)
DEFAULT_L2CS_DEVICE = os.getenv("UX_L2CS_DEVICE", "auto").lower()
CALIBRATION_TARGETS = (
    {"x": 0.08, "y": 0.08},
    {"x": 0.5, "y": 0.08},
    {"x": 0.92, "y": 0.08},
    {"x": 0.08, "y": 0.5},
    {"x": 0.5, "y": 0.5},
    {"x": 0.92, "y": 0.5},
    {"x": 0.08, "y": 0.92},
    {"x": 0.5, "y": 0.92},
    {"x": 0.92, "y": 0.92},
)


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


@dataclass
class CalibrationProfile:
    x_min: float = DEFAULT_X_MIN
    x_max: float = DEFAULT_X_MAX
    y_min: float = DEFAULT_Y_MIN
    y_max: float = DEFAULT_Y_MAX
    source: str = "defaults"
    machine_profile: dict[str, Any] | None = None
    x_weights: list[float] | None = None
    y_weights: list[float] | None = None
    profile_version: int = CALIBRATION_PROFILE_VERSION
    rmse_normalized: float | None = None
    point_errors: list[float] | None = None
    correction_x_weights: list[float] | None = None
    correction_y_weights: list[float] | None = None

    @classmethod
    def load(cls, path: Path = DEFAULT_CALIBRATION_FILE) -> "CalibrationProfile":
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            return cls()
        return cls(
            x_min=float(data.get("x_min", DEFAULT_X_MIN)),
            x_max=float(data.get("x_max", DEFAULT_X_MAX)),
            y_min=float(data.get("y_min", DEFAULT_Y_MIN)),
            y_max=float(data.get("y_max", DEFAULT_Y_MAX)),
            source=str(data.get("source", "file")),
            machine_profile=data.get("machine_profile"),
            x_weights=data.get("x_weights"),
            y_weights=data.get("y_weights"),
            profile_version=int(data.get("profile_version", 1)),
            rmse_normalized=data.get("rmse_normalized"),
            point_errors=data.get("point_errors"),
            correction_x_weights=data.get("correction_x_weights"),
            correction_y_weights=data.get("correction_y_weights"),
        )

    def map_to_screen(
        self,
        x_ratio: float,
        y_ratio: float,
        feature_vector: list[float] | None = None,
    ) -> tuple[float, float]:
        if (
            self.x_weights
            and self.y_weights
            and feature_vector
            and len(self.x_weights) == len(feature_vector)
            and len(self.y_weights) == len(feature_vector)
        ):
            normalized_x = clamp(float(np.dot(np.array(self.x_weights), np.array(feature_vector))), 0.0, 1.0)
            normalized_y = clamp(float(np.dot(np.array(self.y_weights), np.array(feature_vector))), 0.0, 1.0)
            return self.apply_residual_correction(normalized_x, normalized_y)
        if self.source == "defaults":
            # ETH-XGaze already produces normalized coarse gaze estimates.
            # Running them through the narrow hand-tuned min/max window collapses
            # large parts of the range to the screen edges before calibration.
            return clamp(x_ratio, 0.0, 1.0), clamp(y_ratio, 0.0, 1.0)
        normalized_x = clamp((x_ratio - self.x_min) / max(self.x_max - self.x_min, 0.001), 0.0, 1.0)
        normalized_y = clamp((y_ratio - self.y_min) / max(self.y_max - self.y_min, 0.001), 0.0, 1.0)
        return self.apply_residual_correction(normalized_x, normalized_y)

    def apply_residual_correction(self, x: float, y: float) -> tuple[float, float]:
        if (
            self.correction_x_weights
            and self.correction_y_weights
            and len(self.correction_x_weights) == 3
            and len(self.correction_y_weights) == 3
        ):
            correction_features = np.array([x, y, 1.0], dtype=float)
            x = float(np.dot(np.array(self.correction_x_weights), correction_features))
            y = float(np.dot(np.array(self.correction_y_weights), correction_features))
        return clamp(x, 0.0, 1.0), clamp(y, 0.0, 1.0)

    def is_compatible(self, machine_profile: dict[str, Any]) -> bool:
        return bool(self.machine_profile) and self.machine_profile == machine_profile

    def save(self, path: Path = DEFAULT_CALIBRATION_FILE) -> None:
        path.write_text(
            json.dumps(
                {
                    "x_min": self.x_min,
                    "x_max": self.x_max,
                    "y_min": self.y_min,
                    "y_max": self.y_max,
                    "source": self.source,
                    "machine_profile": self.machine_profile,
                    "x_weights": self.x_weights,
                    "y_weights": self.y_weights,
                    "profile_version": self.profile_version,
                    "rmse_normalized": self.rmse_normalized,
                    "point_errors": self.point_errors,
                    "correction_x_weights": self.correction_x_weights,
                    "correction_y_weights": self.correction_y_weights,
                },
                ensure_ascii=True,
                indent=2,
            )
        )


def detect_screen_geometry() -> dict[str, int]:
    geometry = primary_screen_geometry()
    return {"width": int(geometry["width"]), "height": int(geometry["height"])}


def build_machine_profile(camera_index: int, gaze_model: str = DEFAULT_GAZE_MODEL_BACKEND) -> dict[str, Any]:
    geometry = detect_screen_geometry()
    display = primary_screen_geometry()
    return {
        "hostname": socket.gethostname(),
        "camera_index": camera_index,
        "camera_width": DEFAULT_FRAME_WIDTH,
        "camera_height": DEFAULT_FRAME_HEIGHT,
        "screen_width": geometry["width"],
        "screen_height": geometry["height"],
        "screen_geometry_source": display["source"],
        "dpi_awareness": display["dpi_awareness"],
        "gaze_model": gaze_model,
        "calibration_profile_version": CALIBRATION_PROFILE_VERSION,
    }


def candidate_model_paths() -> list[Path]:
    configured = Path(DEFAULT_FACE_LANDMARKER_MODEL).expanduser()
    base_dir = Path(__file__).resolve().parent
    candidates = [configured]
    if not configured.is_absolute():
        candidates.append((base_dir / configured).resolve())
        candidates.append((base_dir / ".models" / configured.name).resolve())

    unique_paths: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique_paths.append(path)
    return unique_paths


def resolve_model_path() -> Path | None:
    for path in candidate_model_paths():
        if path.exists() and path.is_file():
            return path
    return None


def landmark_xy(point: Any) -> tuple[float, float]:
    return float(point.x), float(point.y)


def average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def fit_axis(raw_values: list[float], targets: list[float], fallback_min: float, fallback_max: float) -> tuple[float, float]:
    if len(raw_values) < 2:
        return fallback_min, fallback_max

    raw_mean = average(raw_values)
    target_mean = average(targets)
    variance = sum((value - raw_mean) ** 2 for value in raw_values)
    if variance <= 1e-9:
        return fallback_min, fallback_max

    covariance = sum(
        (raw_value - raw_mean) * (target_value - target_mean)
        for raw_value, target_value in zip(raw_values, targets, strict=False)
    )
    slope = covariance / variance
    if abs(slope) <= 1e-9:
        return fallback_min, fallback_max
    intercept = target_mean - slope * raw_mean
    axis_min = (-intercept) / slope
    axis_max = (1.0 - intercept) / slope
    if axis_min > axis_max:
        axis_min, axis_max = axis_max, axis_min
    return axis_min, axis_max


def fit_ridge(feature_matrix: np.ndarray, targets: np.ndarray, ridge: float) -> list[float]:
    regularizer = np.eye(feature_matrix.shape[1]) * ridge
    regularizer[-1, -1] = 0.0
    weights = np.linalg.solve(
        feature_matrix.T @ feature_matrix + regularizer,
        feature_matrix.T @ targets,
    )
    return weights.tolist()


class LatestFrameCapture:
    """Continuously capture frames while exposing only the newest one."""

    def __init__(self, camera: Any) -> None:
        self.camera = camera
        self.condition = threading.Condition()
        self.frame: Any = None
        self.sequence = 0
        self.failed_reads = 0
        self.stopped = False
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        while not self.stopped:
            ok, frame = self.camera.read()
            with self.condition:
                if ok and frame is not None:
                    self.frame = frame
                    self.sequence += 1
                else:
                    self.failed_reads += 1
                self.condition.notify_all()
            if not ok:
                time.sleep(0.01)

    def read_latest(self, after_sequence: int, timeout: float) -> tuple[int, Any]:
        with self.condition:
            self.condition.wait_for(
                lambda: self.sequence > after_sequence or self.stopped,
                timeout=timeout,
            )
            return self.sequence, self.frame

    def stop(self) -> None:
        self.stopped = True
        with self.condition:
            self.condition.notify_all()
        if self.thread.is_alive():
            self.thread.join(timeout=1.0)


class OpenCvMediaPipeGazeProvider:
    provider_type = "native_cv"

    def __init__(self, emit_point, emit_status, emit_lost, sample_interval_ms: int) -> None:
        self.emit_point = emit_point
        self.emit_status = emit_status
        self.emit_lost = emit_lost
        self.sample_interval_ms = sample_interval_ms
        self.model_backend = DEFAULT_GAZE_MODEL_BACKEND
        self.provider_name = (
            "l2cs_gaze360_webcam"
            if self.model_backend == "l2cs"
            else "eth_xgaze_webcam"
        )
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_emitted_at = 0.0
        self.last_face_seen_at = 0.0
        self.smoothing = DEFAULT_SMOOTHING
        self.calibration = CalibrationProfile.load()
        self.machine_profile = build_machine_profile(
            DEFAULT_CAMERA_INDEX, self.model_backend
        )
        self.screen_width = int(self.machine_profile.get("screen_width", DEFAULT_SCREEN_WIDTH))
        self.screen_height = int(self.machine_profile.get("screen_height", DEFAULT_SCREEN_HEIGHT))
        self.smoothed_point: tuple[float, float] | None = None
        self.last_smoothing_at: float | None = None
        self.latest_raw_point: tuple[float, float] | None = None
        self.latest_feature_vector: list[float] | None = None
        self.latest_confidence = 0.0
        self.latest_sample_valid = False
        self.recent_feature_samples: list[dict[str, Any]] = []
        self.runtime_lock = threading.Lock()
        self.calibration_lock = threading.Lock()
        self.calibration_samples: list[dict[str, Any]] = []
        self.calibration_active = False
        self.calibration_started_at: float | None = None
        self.calibration_error: str | None = None
        self.calibration_id: str | None = None
        self.metrics = {
            "frames_captured": 0,
            "frames_failed": 0,
            "frames_with_face": 0,
            "frames_quality_valid": 0,
            "frames_emitted": 0,
            "frames_invalid": 0,
            "multiple_faces": 0,
            "inference_ms": [],
        }
        self.metrics_started_at = time.monotonic()
        self.last_metrics_at = self.metrics_started_at
        self.previous_raw_point: tuple[float, float] | None = None

    @property
    def calibration_frames_per_target(self) -> int:
        return 5 if self.model_backend == "l2cs" else DEFAULT_CALIBRATION_SAMPLES_PER_TARGET

    def _log_calibration(self, event: str, **payload: Any) -> None:
        record = {
            "timestamp": time.time(),
            "event": event,
            "calibration_id": self.calibration_id,
            "provider": self.provider_name,
            "model_backend": self.model_backend,
            "machine_profile": self.machine_profile,
            **payload,
        }
        try:
            DEFAULT_CALIBRATION_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with DEFAULT_CALIBRATION_LOG_FILE.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=True) + "\n")
        except OSError as error:
            self.emit_status(
                "debug",
                phase="calibration_log_failed",
                message=str(error),
            )

    def _eye_ratio(
        self,
        landmarks: Any,
        iris_indices: tuple[int, ...],
        horizontal_indices: tuple[int, int],
        vertical_indices: tuple[int, int],
    ) -> tuple[float, float, float]:
        iris_points = [landmarks[index] for index in iris_indices]
        iris_x = sum(point.x for point in iris_points) / len(iris_points)
        iris_y = sum(point.y for point in iris_points) / len(iris_points)

        h0 = landmarks[horizontal_indices[0]]
        h1 = landmarks[horizontal_indices[1]]
        v0 = landmarks[vertical_indices[0]]
        v1 = landmarks[vertical_indices[1]]

        # Keep horizontal direction instead of collapsing to min/max.
        # For one eye, corner order is outer->inner; for the mirrored eye it is inner->outer.
        # Using signed span preserves left/right movement without forcing it to center or extremes.
        horizontal_span = h1.x - h0.x
        if abs(horizontal_span) <= 1e-6:
            horizontal_ratio = 0.5
        else:
            horizontal_ratio = clamp((iris_x - h0.x) / horizontal_span, 0.0, 1.0)

        min_y = min(v0.y, v1.y)
        max_y = max(v0.y, v1.y)
        vertical_ratio = clamp((iris_y - min_y) / max(max_y - min_y, 1e-6), 0.0, 1.0)
        openness = abs(v0.y - v1.y)
        return horizontal_ratio, vertical_ratio, openness

    def _feature_vector(self, landmarks: Any) -> tuple[list[float], dict[str, float]]:
        left_x, left_y, left_open = self._eye_ratio(
            landmarks, LEFT_IRIS, LEFT_EYE_H, LEFT_EYE_V
        )
        right_x, right_y, right_open = self._eye_ratio(
            landmarks, RIGHT_IRIS, RIGHT_EYE_H, RIGHT_EYE_V
        )

        left_iris_points = [landmarks[index] for index in LEFT_IRIS]
        right_iris_points = [landmarks[index] for index in RIGHT_IRIS]
        left_iris_x = average([point.x for point in left_iris_points])
        left_iris_y = average([point.y for point in left_iris_points])
        right_iris_x = average([point.x for point in right_iris_points])
        right_iris_y = average([point.y for point in right_iris_points])

        face_left_x, _ = landmark_xy(landmarks[FACE_LEFT])
        face_right_x, _ = landmark_xy(landmarks[FACE_RIGHT])
        _, face_top_y = landmark_xy(landmarks[FACE_TOP])
        _, face_bottom_y = landmark_xy(landmarks[FACE_BOTTOM])
        nose_x, nose_y = landmark_xy(landmarks[NOSE_TIP])

        face_width = max(face_right_x - face_left_x, 1e-6)
        face_height = max(face_bottom_y - face_top_y, 1e-6)
        openness = (left_open + right_open) / 2.0

        left_iris_x_face = clamp((left_iris_x - face_left_x) / face_width, 0.0, 1.0)
        right_iris_x_face = clamp((right_iris_x - face_left_x) / face_width, 0.0, 1.0)
        left_iris_y_face = clamp((left_iris_y - face_top_y) / face_height, 0.0, 1.0)
        right_iris_y_face = clamp((right_iris_y - face_top_y) / face_height, 0.0, 1.0)
        nose_x_face = clamp((nose_x - face_left_x) / face_width, 0.0, 1.0)
        nose_y_face = clamp((nose_y - face_top_y) / face_height, 0.0, 1.0)

        feature_vector = [
            left_x,
            right_x,
            left_y,
            right_y,
            left_iris_x_face,
            right_iris_x_face,
            left_iris_y_face,
            right_iris_y_face,
            nose_x_face,
            nose_y_face,
            left_open,
            right_open,
            openness,
            1.0,
        ]
        raw = {
            "raw_x": round((left_iris_x_face + right_iris_x_face) / 2.0, 6),
            "raw_y": round((left_iris_y_face + right_iris_y_face) / 2.0, 6),
            "left_x": round(left_x, 6),
            "right_x": round(right_x, 6),
            "left_y": round(left_y, 6),
            "right_y": round(right_y, 6),
            "left_iris_x_face": round(left_iris_x_face, 6),
            "right_iris_x_face": round(right_iris_x_face, 6),
            "left_iris_y_face": round(left_iris_y_face, 6),
            "right_iris_y_face": round(right_iris_y_face, 6),
            "nose_x_face": round(nose_x_face, 6),
            "nose_y_face": round(nose_y_face, 6),
            "openness": round(openness, 6),
        }
        return feature_vector, raw

    def _eth_xgaze_features(self, face: Any, frame_width: int, frame_height: int) -> tuple[list[float], dict[str, float]]:
        gaze_pitch_deg, gaze_yaw_deg = face.get_gaze_angles()
        head_pitch_deg, head_yaw_deg, head_roll_deg = face.get_head_angles()

        bbox = np.array(face.bbox, dtype=float)
        bbox_center_x = float((bbox[0][0] + bbox[1][0]) / 2.0)
        bbox_center_y = float((bbox[0][1] + bbox[1][1]) / 2.0)
        bbox_width = float(max(bbox[1][0] - bbox[0][0], 1.0))
        bbox_height = float(max(bbox[1][1] - bbox[0][1], 1.0))

        bbox_center_x_norm = clamp(bbox_center_x / max(frame_width, 1), 0.0, 1.0)
        bbox_center_y_norm = clamp(bbox_center_y / max(frame_height, 1), 0.0, 1.0)
        bbox_width_norm = clamp(bbox_width / max(frame_width, 1), 0.0, 1.0)
        bbox_height_norm = clamp(bbox_height / max(frame_height, 1), 0.0, 1.0)
        landmarks = np.asarray(face.landmarks, dtype=float)

        def eye_aspect_ratio(horizontal: tuple[int, int], vertical: tuple[int, int]) -> float:
            horizontal_distance = float(
                np.linalg.norm(landmarks[horizontal[0]][:2] - landmarks[horizontal[1]][:2])
            )
            vertical_distance = float(
                np.linalg.norm(landmarks[vertical[0]][:2] - landmarks[vertical[1]][:2])
            )
            return vertical_distance / max(horizontal_distance, 1e-6)

        eye_openness = (
            eye_aspect_ratio(LEFT_EYE_H, LEFT_EYE_V)
            + eye_aspect_ratio(RIGHT_EYE_H, RIGHT_EYE_V)
        ) / 2.0

        # ETH-XGaze angles drift badly if we treat gaze direction as absolute.
        # A simple head-pose compensation gives a much saner fallback before
        # user-specific calibration has been collected.
        relative_yaw_deg = gaze_yaw_deg - (head_yaw_deg * DEFAULT_ETH_XGAZE_HEAD_YAW_COMP)
        relative_pitch_deg = gaze_pitch_deg - (head_pitch_deg * DEFAULT_ETH_XGAZE_HEAD_PITCH_COMP)
        raw_x = clamp(0.5 - (relative_yaw_deg / DEFAULT_ETH_XGAZE_YAW_SCALE), 0.0, 1.0)
        raw_y = clamp(0.5 + (relative_pitch_deg / DEFAULT_ETH_XGAZE_PITCH_SCALE), 0.0, 1.0)

        gaze_vector = np.array(face.gaze_vector, dtype=float).reshape(3)
        feature_vector = [
            float(gaze_vector[0]),
            float(gaze_vector[1]),
            float(gaze_vector[2]),
            float(gaze_pitch_deg / 45.0),
            float(gaze_yaw_deg / 60.0),
            float(head_pitch_deg / 45.0),
            float(head_yaw_deg / 60.0),
            float(head_roll_deg / 45.0),
            bbox_center_x_norm,
            bbox_center_y_norm,
            bbox_width_norm,
            bbox_height_norm,
            1.0,
        ]
        raw = {
            "raw_x": round(raw_x, 6),
            "raw_y": round(raw_y, 6),
            # ETH-XGaze does not expose per-eye iris ratios; keep these empty so
            # logs do not imply a broken iris tracker when this provider is active.
            "left_x": None,
            "right_x": None,
            "left_y": None,
            "right_y": None,
            "left_iris_x_face": bbox_center_x_norm,
            "right_iris_x_face": bbox_center_x_norm,
            "left_iris_y_face": bbox_center_y_norm,
            "right_iris_y_face": bbox_center_y_norm,
            "nose_x_face": bbox_center_x_norm,
            "nose_y_face": bbox_center_y_norm,
            "openness": round(eye_openness, 6),
            "gaze_pitch_deg": round(float(gaze_pitch_deg), 6),
            "gaze_yaw_deg": round(float(gaze_yaw_deg), 6),
            "head_pitch_deg": round(float(head_pitch_deg), 6),
            "head_yaw_deg": round(float(head_yaw_deg), 6),
            "head_roll_deg": round(float(head_roll_deg), 6),
            "relative_pitch_deg": round(float(relative_pitch_deg), 6),
            "relative_yaw_deg": round(float(relative_yaw_deg), 6),
        }
        return feature_vector, raw

    def _l2cs_features(
        self, results: Any, index: int, frame_width: int, frame_height: int
    ) -> tuple[list[float], dict[str, Any]]:
        gaze_pitch_deg = math.degrees(float(results.pitch[index]))
        gaze_yaw_deg = math.degrees(float(results.yaw[index]))
        bbox = np.array(results.bboxes[index], dtype=float).reshape(-1)
        x0, y0, x1, y1 = bbox[:4]
        center_x = clamp(((x0 + x1) / 2.0) / max(frame_width, 1), 0.0, 1.0)
        center_y = clamp(((y0 + y1) / 2.0) / max(frame_height, 1), 0.0, 1.0)
        width = clamp((x1 - x0) / max(frame_width, 1), 0.0, 1.0)
        height = clamp((y1 - y0) / max(frame_height, 1), 0.0, 1.0)
        detection_score = float(results.scores[index])
        raw_x = clamp(0.5 - gaze_yaw_deg / DEFAULT_ETH_XGAZE_YAW_SCALE, 0.0, 1.0)
        raw_y = clamp(0.5 + gaze_pitch_deg / DEFAULT_ETH_XGAZE_PITCH_SCALE, 0.0, 1.0)
        feature_vector = [
            gaze_yaw_deg / 90.0,
            gaze_pitch_deg / 90.0,
            center_x,
            center_y,
            1.0,
        ]
        return feature_vector, {
            "raw_x": raw_x,
            "raw_y": raw_y,
            "left_x": None,
            "right_x": None,
            "left_y": None,
            "right_y": None,
            "left_iris_x_face": center_x,
            "right_iris_x_face": center_x,
            "left_iris_y_face": center_y,
            "right_iris_y_face": center_y,
            "nose_x_face": center_x,
            "nose_y_face": center_y,
            "openness": None,
            "gaze_pitch_deg": gaze_pitch_deg,
            "gaze_yaw_deg": gaze_yaw_deg,
            "head_pitch_deg": 0.0,
            "head_yaw_deg": 0.0,
            "head_roll_deg": 0.0,
            "relative_pitch_deg": gaze_pitch_deg,
            "relative_yaw_deg": gaze_yaw_deg,
            "detection_score": detection_score,
        }

    def _assess_sample_quality(
        self, raw: dict[str, Any], face_count: int
    ) -> tuple[bool, float, str | None]:
        if face_count != 1:
            return False, 0.0, "multiple_faces" if face_count > 1 else "face_not_detected"

        yaw = abs(float(raw["head_yaw_deg"]))
        pitch = abs(float(raw["head_pitch_deg"]))
        roll = abs(float(raw["head_roll_deg"]))
        pose_score = min(
            max(0.0, 1.0 - yaw / DEFAULT_MAX_HEAD_YAW_DEG),
            max(0.0, 1.0 - pitch / DEFAULT_MAX_HEAD_PITCH_DEG),
            max(0.0, 1.0 - roll / DEFAULT_MAX_HEAD_ROLL_DEG),
        )
        if yaw > DEFAULT_MAX_HEAD_YAW_DEG:
            return False, pose_score, "head_yaw_out_of_range"
        if pitch > DEFAULT_MAX_HEAD_PITCH_DEG:
            return False, pose_score, "head_pitch_out_of_range"
        if roll > DEFAULT_MAX_HEAD_ROLL_DEG:
            return False, pose_score, "head_roll_out_of_range"

        point = (float(raw["raw_x"]), float(raw["raw_y"]))
        temporal_score = 1.0
        if self.previous_raw_point is not None:
            jump = math.dist(point, self.previous_raw_point)
            temporal_score = max(0.0, 1.0 - jump / DEFAULT_MAX_NORMALIZED_JUMP)
            if jump > DEFAULT_MAX_NORMALIZED_JUMP:
                self.previous_raw_point = point
                return False, min(pose_score, temporal_score), "temporal_outlier"
        self.previous_raw_point = point
        # ETH-XGaze exposes no calibrated per-frame probability. This is an
        # explicit quality heuristic, not model confidence.
        detection_score = float(raw.get("detection_score", 1.0))
        return True, round(
            0.45 * pose_score + 0.35 * temporal_score + 0.2 * detection_score,
            4,
        ), None

    def _emit_metrics(self, now: float) -> None:
        monotonic_now = time.monotonic()
        if monotonic_now - self.last_metrics_at < DEFAULT_TELEMETRY_INTERVAL_S:
            return
        elapsed = max(monotonic_now - self.metrics_started_at, 1e-6)
        inference = list(self.metrics["inference_ms"])
        inference.sort()
        percentile = lambda q: inference[min(int((len(inference) - 1) * q), len(inference) - 1)] if inference else None
        captured = int(self.metrics["frames_captured"])
        self.emit_status(
            "telemetry",
            measured_at=now,
            capture_fps=round(captured / elapsed, 2),
            output_fps=round(int(self.metrics["frames_emitted"]) / elapsed, 2),
            face_detection_ratio=round(int(self.metrics["frames_with_face"]) / max(captured, 1), 4),
            valid_sample_ratio=round(int(self.metrics["frames_quality_valid"]) / max(captured, 1), 4),
            invalid_samples=int(self.metrics["frames_invalid"]),
            failed_frames=int(self.metrics["frames_failed"]),
            skipped_stale_frames=int(self.metrics.get("frames_skipped", 0)),
            multiple_faces=int(self.metrics["multiple_faces"]),
            inference_latency_ms_p50=round(percentile(0.5), 2) if inference else None,
            inference_latency_ms_p95=round(percentile(0.95), 2) if inference else None,
        )
        self.last_metrics_at = monotonic_now

    def _smooth(self, x: float, y: float) -> tuple[float, float]:
        now = time.monotonic()
        if self.smoothed_point is None:
            self.smoothed_point = (x, y)
            self.last_smoothing_at = now
            return self.smoothed_point
        previous_x, previous_y = self.smoothed_point
        elapsed = max(now - (self.last_smoothing_at or now), 1e-3)
        distance = math.dist((x, y), self.smoothed_point)
        if self.model_backend == "l2cs":
            # L2CS noise commonly spans a few percent of the screen. Suppress
            # that jitter but keep deliberate larger gaze transitions responsive.
            adaptive_alpha = 0.12 if distance < 0.04 else 0.28 if distance < 0.10 else 0.62
        else:
            speed = distance / elapsed
            adaptive_alpha = clamp(self.smoothing * 0.55 + speed * 0.08, 0.2, 0.85)
        next_x = previous_x + adaptive_alpha * (x - previous_x)
        next_y = previous_y + adaptive_alpha * (y - previous_y)
        self.smoothed_point = (next_x, next_y)
        self.last_smoothing_at = now
        return self.smoothed_point

    def _apply_axis_orientation(self, x: float, y: float) -> tuple[float, float]:
        if DEFAULT_INVERT_X:
            x = 1.0 - x
        if DEFAULT_INVERT_Y:
            y = 1.0 - y
        return clamp(x, 0.0, 1.0), clamp(y, 0.0, 1.0)

    def _apply_default_range(self, x: float, y: float) -> tuple[float, float]:
        if self.calibration.source != "defaults":
            return x, y
        x = 0.5 + ((x - 0.5) * DEFAULT_X_GAIN) + DEFAULT_X_OFFSET
        y = 0.5 + ((y - 0.5) * DEFAULT_Y_GAIN) + DEFAULT_Y_OFFSET
        return clamp(x, 0.0, 1.0), clamp(y, 0.0, 1.0)

    def _emit_debug(self, phase: str, **extra: Any) -> None:
        self.emit_status("debug", phase=phase, **extra)

    def start(self) -> None:
        if not self.calibration.is_compatible(self.machine_profile):
            self.calibration.source = "defaults"
            self.calibration.machine_profile = self.machine_profile

        self.emit_status(
            "starting",
            calibration={
                "x_min": self.calibration.x_min,
                "x_max": self.calibration.x_max,
                "y_min": self.calibration.y_min,
                "y_max": self.calibration.y_max,
                "source": self.calibration.source,
            },
            calibration_required=self.calibration.source == "defaults",
            machine_profile=self.machine_profile,
            invert_x=DEFAULT_INVERT_X,
            invert_y=DEFAULT_INVERT_Y,
            x_gain=DEFAULT_X_GAIN,
            y_gain=DEFAULT_Y_GAIN,
            x_offset=DEFAULT_X_OFFSET,
            y_offset=DEFAULT_Y_OFFSET,
        )

        try:
            import cv2  # type: ignore
            if self.model_backend == "l2cs":
                import torch  # type: ignore
                from l2cs import Pipeline  # type: ignore
            else:
                from pygaze import PyGaze  # type: ignore
        except Exception as error:
            self.emit_status("unavailable", message=str(error))
            self.emit_lost("provider_import_failed", message=str(error))
            return

        def run() -> None:
            camera = None
            capture = None
            estimator = None
            blink_guard_until = 0.0
            try:
                self._emit_debug(
                    "runtime_resolved",
                    model=self.model_backend,
                    python_version=f"{sys.version_info.major}.{sys.version_info.minor}",
                )
                self._emit_debug(
                    "camera_open_begin",
                    camera_index=DEFAULT_CAMERA_INDEX,
                    frame_width=DEFAULT_FRAME_WIDTH,
                    frame_height=DEFAULT_FRAME_HEIGHT,
                )
                backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
                camera = cv2.VideoCapture(DEFAULT_CAMERA_INDEX, backend)
                self._emit_debug("camera_open_returned")
                camera.set(cv2.CAP_PROP_FRAME_WIDTH, DEFAULT_FRAME_WIDTH)
                camera.set(cv2.CAP_PROP_FRAME_HEIGHT, DEFAULT_FRAME_HEIGHT)
                camera.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                if not camera.isOpened():
                    self.emit_status("unavailable", message="camera_open_failed")
                    self.emit_lost("camera_open_failed")
                    return

                self._emit_debug("camera_opened")
                if self.model_backend == "l2cs":
                    l2cs_path = Path(DEFAULT_L2CS_MODEL).expanduser().resolve()
                    l2cs_device = torch.device(
                        "cuda"
                        if DEFAULT_L2CS_DEVICE == "auto" and torch.cuda.is_available()
                        else DEFAULT_L2CS_DEVICE
                        if DEFAULT_L2CS_DEVICE != "auto"
                        else "cpu"
                    )
                    self._emit_debug(
                        "l2cs_init_begin",
                        checkpoint=str(l2cs_path),
                        device=str(l2cs_device),
                    )
                    estimator = Pipeline(
                        weights=l2cs_path,
                        arch="ResNet50",
                        device=l2cs_device,
                        confidence_threshold=0.6,
                    )
                    self._emit_debug("l2cs_init_ok")
                else:
                    self._emit_debug(
                        "eth_xgaze_init_begin",
                        checkpoint_dir=str(Path(DEFAULT_ETH_XGAZE_MODEL_DIR).expanduser()),
                    )
                    estimator = PyGaze(device="cpu", model_path=DEFAULT_ETH_XGAZE_MODEL_DIR)
                    self._emit_debug("eth_xgaze_init_ok")
                capture = LatestFrameCapture(camera)
                capture.start()
                self.emit_status(
                    "running",
                    calibration_source=self.calibration.source,
                    calibration_required=self.calibration.source == "defaults",
                    invert_x=DEFAULT_INVERT_X,
                    invert_y=DEFAULT_INVERT_Y,
                    x_gain=DEFAULT_X_GAIN,
                    y_gain=DEFAULT_Y_GAIN,
                    x_offset=DEFAULT_X_OFFSET,
                    y_offset=DEFAULT_Y_OFFSET,
                    machine_profile=self.machine_profile,
                )

                first_frame_logged = False
                first_face_logged = False
                last_capture_sequence = 0
                while not self.stop_event.is_set():
                    capture_sequence, frame = capture.read_latest(
                        last_capture_sequence,
                        timeout=max(self.sample_interval_ms / 1000.0, 0.1),
                    )
                    ok = capture_sequence > last_capture_sequence and frame is not None
                    if ok:
                        skipped = max(0, capture_sequence - last_capture_sequence - 1)
                        self.metrics["frames_captured"] += 1 + skipped
                        self.metrics["frames_skipped"] = (
                            int(self.metrics.get("frames_skipped", 0)) + skipped
                        )
                        last_capture_sequence = capture_sequence
                    if not first_frame_logged:
                        self._emit_debug(
                            "first_frame_result",
                            ok=bool(ok),
                            frame_is_none=frame is None,
                        )
                        first_frame_logged = True
                    if not ok or frame is None:
                        self.metrics["frames_failed"] += 1
                        self.emit_lost("camera_frame_unavailable")
                        time.sleep(self.sample_interval_ms / 1000)
                        continue

                    inference_started = time.perf_counter()
                    if self.model_backend == "l2cs":
                        try:
                            prediction = estimator.step(frame)
                            faces = list(range(len(prediction.pitch)))
                        except ValueError:
                            prediction = None
                            faces = []
                    else:
                        faces = estimator.predict(frame)
                    self.metrics["inference_ms"].append(
                        (time.perf_counter() - inference_started) * 1000.0
                    )
                    self.metrics["inference_ms"] = self.metrics["inference_ms"][-600:]
                    now = time.time()

                    if not faces:
                        self.metrics["frames_invalid"] += 1
                        if self.last_face_seen_at and (now - self.last_face_seen_at) >= 1.0:
                            self.emit_lost("face_not_detected")
                        self._emit_metrics(now)
                        time.sleep(self.sample_interval_ms / 1000)
                        continue
                    if len(faces) != 1:
                        self.metrics["multiple_faces"] += 1
                        self.metrics["frames_invalid"] += 1
                        self.emit_lost("multiple_faces", face_count=len(faces))
                        self._emit_metrics(now)
                        time.sleep(self.sample_interval_ms / 1000)
                        continue

                    self.last_face_seen_at = now
                    self.metrics["frames_with_face"] += 1
                    if not first_face_logged:
                        self._emit_debug("first_face_detected")
                        first_face_logged = True

                    if self.model_backend == "l2cs":
                        feature_vector, raw = self._l2cs_features(
                            prediction,
                            faces[0],
                            frame_width=frame.shape[1],
                            frame_height=frame.shape[0],
                        )
                    else:
                        feature_vector, raw = self._eth_xgaze_features(
                            faces[0],
                            frame_width=frame.shape[1],
                            frame_height=frame.shape[0],
                        )
                    eye_openness = raw.get("openness")
                    is_blink = (
                        eye_openness is not None
                        and float(eye_openness) <= DEFAULT_BLINK_EAR_THRESHOLD
                    )
                    if is_blink:
                        blink_guard_until = now + DEFAULT_BLINK_GUARD_MS / 1000.0
                    if now < blink_guard_until:
                        self.metrics["frames_invalid"] += 1
                        self.emit_lost(
                            "blink",
                            eye_openness=eye_openness,
                            blink_guard_ms=DEFAULT_BLINK_GUARD_MS,
                            sample_valid=False,
                        )
                        self._emit_metrics(now)
                        continue
                    raw_x = raw["raw_x"]
                    raw_y = raw["raw_y"]
                    sample_valid, quality_score, invalid_reason = self._assess_sample_quality(
                        raw, len(faces)
                    )
                    with self.runtime_lock:
                        self.latest_raw_point = (raw_x, raw_y)
                        self.latest_feature_vector = feature_vector
                        self.latest_confidence = quality_score
                        self.latest_sample_valid = sample_valid

                    oriented_x, oriented_y = self._apply_axis_orientation(raw_x, raw_y)
                    normalized_x, normalized_y = self.calibration.map_to_screen(
                        oriented_x,
                        oriented_y,
                        feature_vector=feature_vector,
                    )
                    normalized_x, normalized_y = self._apply_default_range(
                        normalized_x,
                        normalized_y,
                    )
                    normalized_x, normalized_y = self._smooth(normalized_x, normalized_y)
                    screen_x = normalized_x * self.screen_width
                    screen_y = normalized_y * self.screen_height
                    with self.runtime_lock:
                        self.recent_feature_samples.append(
                            {
                                "raw_x": oriented_x,
                                "raw_y": oriented_y,
                                "feature_vector": feature_vector,
                                "confidence": quality_score,
                                "sample_valid": sample_valid,
                                "captured_at": now,
                            }
                        )
                        self.recent_feature_samples = self.recent_feature_samples[-12:]

                    if not sample_valid or quality_score < DEFAULT_MIN_CONFIDENCE:
                        self.metrics["frames_invalid"] += 1
                        self.emit_lost(
                            invalid_reason or "low_sample_quality",
                            confidence=quality_score,
                            quality_score=quality_score,
                            sample_valid=False,
                        )
                        self._emit_metrics(now)
                        time.sleep(self.sample_interval_ms / 1000)
                        continue
                    self.metrics["frames_quality_valid"] += 1

                    if now - self.last_emitted_at < self.sample_interval_ms / 1000:
                        time.sleep(0.001)
                        continue
                    self.last_emitted_at = now
                    self.metrics["frames_emitted"] += 1

                    self.emit_point(
                        screen_x,
                        screen_y,
                        quality_score,
                        sample_valid=True,
                        quality_score=quality_score,
                        quality_method=(
                            "face_detection_temporal_v1"
                            if self.model_backend == "l2cs"
                            else "head_pose_temporal_v1"
                        ),
                        model_backend=self.model_backend,
                        invalid_reason=None,
                        raw_normalized_x=round(oriented_x, 6),
                        raw_normalized_y=round(oriented_y, 6),
                        raw_eye_ratio_x=raw["raw_x"],
                        raw_eye_ratio_y=raw["raw_y"],
                        left_eye_ratio_x=raw["left_x"],
                        right_eye_ratio_x=raw["right_x"],
                        left_eye_ratio_y=raw["left_y"],
                        right_eye_ratio_y=raw["right_y"],
                        left_iris_x_face=raw["left_iris_x_face"],
                        right_iris_x_face=raw["right_iris_x_face"],
                        left_iris_y_face=raw["left_iris_y_face"],
                        right_iris_y_face=raw["right_iris_y_face"],
                        nose_x_face=raw["nose_x_face"],
                        nose_y_face=raw["nose_y_face"],
                        gaze_pitch_deg=raw["gaze_pitch_deg"],
                        gaze_yaw_deg=raw["gaze_yaw_deg"],
                        head_pitch_deg=raw["head_pitch_deg"],
                        head_yaw_deg=raw["head_yaw_deg"],
                        head_roll_deg=raw["head_roll_deg"],
                        projected_normalized_x=round(normalized_x, 6),
                        projected_normalized_y=round(normalized_y, 6),
                        eye_openness=eye_openness,
                        blink_score=None,
                        calibration_source=self.calibration.source,
                        calibration_required=self.calibration.source == "defaults",
                        calibration_rmse_normalized=self.calibration.rmse_normalized,
                    )
                    self._emit_metrics(now)
            except Exception as error:
                print(f"[gaze-provider] runtime_error: {error}", file=sys.stderr, flush=True)
                self.emit_status("unavailable", message=f"runtime_error: {error}")
                self.emit_lost("runtime_error", message=str(error))
            finally:
                if capture is not None:
                    capture.stop()
                if camera is not None:
                    camera.release()
                self.emit_status("stopped")

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)

    def get_machine_profile(self) -> dict[str, Any]:
        return self.machine_profile

    def get_calibration_status(self) -> dict[str, Any]:
        with self.calibration_lock:
            return {
                "active": self.calibration_active,
                "required": self.calibration.source == "defaults",
                "source": self.calibration.source,
                "samples_collected": len(self.calibration_samples),
                "targets": list(CALIBRATION_TARGETS),
                # One UI submission per target; the provider aggregates this
                # many recent inference frames inside that submission.
                "samples_per_target": 1,
                "frames_per_target": self.calibration_frames_per_target,
                "started_at": self.calibration_started_at,
                "machine_profile": self.machine_profile,
                "rmse_normalized": self.calibration.rmse_normalized,
                "max_rmse_normalized": DEFAULT_CALIBRATION_MAX_RMSE,
                "error": self.calibration_error,
                "calibration_id": self.calibration_id,
                "log_file": str(DEFAULT_CALIBRATION_LOG_FILE),
            }

    def start_calibration(self) -> dict[str, Any]:
        with self.calibration_lock:
            self.calibration_active = True
            self.calibration_started_at = time.time()
            self.calibration_samples = []
            self.calibration_error = None
            self.calibration_id = str(uuid.uuid4())
        self._log_calibration(
            "started",
            targets=list(CALIBRATION_TARGETS),
            frames_per_target=self.calibration_frames_per_target,
            max_rmse_normalized=DEFAULT_CALIBRATION_MAX_RMSE,
        )
        self.emit_status(
            "calibrating",
            calibration_required=True,
            machine_profile=self.machine_profile,
        )
        return self.get_calibration_status()

    def submit_calibration_sample(
        self, target_x: float, target_y: float, screen_x: float, screen_y: float
    ) -> dict[str, Any]:
        with self.runtime_lock:
            raw_point = self.latest_raw_point
            feature_vector = self.latest_feature_vector
            confidence = self.latest_confidence
            recent_samples = [
                sample
                for sample in self.recent_feature_samples
                if sample["sample_valid"] and sample["confidence"] >= DEFAULT_MIN_CONFIDENCE
            ][-self.calibration_frames_per_target:]
        if not raw_point:
            raise RuntimeError("No gaze sample available yet")
        if not feature_vector:
            raise RuntimeError("No gaze feature vector available yet")
        if confidence < DEFAULT_MIN_CONFIDENCE:
            raise RuntimeError("Current gaze confidence too low for calibration")
        if len(recent_samples) < self.calibration_frames_per_target:
            raise RuntimeError(
                "Not enough stable gaze frames; keep looking at the target and retry"
            )
        raw_x_std = float(np.std([sample["raw_x"] for sample in recent_samples]))
        raw_y_std = float(np.std([sample["raw_y"] for sample in recent_samples]))
        if max(raw_x_std, raw_y_std) > DEFAULT_CALIBRATION_MAX_STD:
            raise RuntimeError(
                "Gaze is not stable enough for calibration; keep still and retry"
            )

        feature_samples = np.array(
            [sample["feature_vector"] for sample in recent_samples],
            dtype=float,
        )
        averaged_feature = np.median(feature_samples, axis=0).tolist()
        averaged_sample = {
            "target_x": target_x,
            "target_y": target_y,
            "screen_x": screen_x,
            "screen_y": screen_y,
            "raw_x": float(np.median([sample["raw_x"] for sample in recent_samples])),
            "raw_y": float(np.median([sample["raw_y"] for sample in recent_samples])),
            "feature_vector": averaged_feature,
            "confidence": average([sample["confidence"] for sample in recent_samples]),
            "captured_at": time.time(),
        }
        if not self.calibration_active:
            self.start_calibration()
        with self.calibration_lock:
            self.calibration_samples.append(averaged_sample)
            samples = list(self.calibration_samples)
        self._log_calibration(
            "target_sampled",
            target_index=len(samples) - 1,
            target={"x": target_x, "y": target_y},
            click_screen={"x": screen_x, "y": screen_y},
            aggregate={
                "raw_x": averaged_sample["raw_x"],
                "raw_y": averaged_sample["raw_y"],
                "confidence": averaged_sample["confidence"],
            },
            frame_count=len(recent_samples),
            raw_x_values=[sample["raw_x"] for sample in recent_samples],
            raw_y_values=[sample["raw_y"] for sample in recent_samples],
            confidence_values=[sample["confidence"] for sample in recent_samples],
            raw_x_std=raw_x_std,
            raw_y_std=raw_y_std,
        )

        # Each UI target submission already aggregates the configured number of
        # recent frames, so one stored observation per target is sufficient.
        if len(samples) >= len(CALIBRATION_TARGETS):
            self._finalize_calibration(samples)
        return self.get_calibration_status()

    def _finalize_calibration(self, samples: list[dict[str, Any]]) -> None:
        feature_matrix = np.array([sample["feature_vector"] for sample in samples], dtype=float)
        target_x = np.array([sample["target_x"] for sample in samples], dtype=float)
        target_y = np.array([sample["target_y"] for sample in samples], dtype=float)
        ridge = 0.001 if self.model_backend == "l2cs" else DEFAULT_CALIBRATION_RIDGE
        x_weights = fit_ridge(feature_matrix, target_x, ridge)
        y_weights = fit_ridge(feature_matrix, target_y, ridge)
        predicted_x = np.clip(feature_matrix @ np.array(x_weights), 0.0, 1.0)
        predicted_y = np.clip(feature_matrix @ np.array(y_weights), 0.0, 1.0)
        correction_x_weights = None
        correction_y_weights = None
        if self.model_backend == "l2cs":
            correction_matrix = np.column_stack(
                [predicted_x, predicted_y, np.ones(len(predicted_x))]
            )
            correction_x_weights = fit_ridge(correction_matrix, target_x, 0.001)
            correction_y_weights = fit_ridge(correction_matrix, target_y, 0.001)
            predicted_x = np.clip(
                correction_matrix @ np.array(correction_x_weights), 0.0, 1.0
            )
            predicted_y = np.clip(
                correction_matrix @ np.array(correction_y_weights), 0.0, 1.0
            )
        point_errors = np.sqrt((predicted_x - target_x) ** 2 + (predicted_y - target_y) ** 2)
        rmse = float(np.sqrt(np.mean(point_errors**2)))
        if rmse > DEFAULT_CALIBRATION_MAX_RMSE:
            self._log_calibration(
                "rejected",
                rmse_normalized=rmse,
                max_rmse_normalized=DEFAULT_CALIBRATION_MAX_RMSE,
                point_errors=[float(error) for error in point_errors],
                predicted_points=[
                    {"x": float(x), "y": float(y)}
                    for x, y in zip(predicted_x, predicted_y, strict=False)
                ],
                target_points=[
                    {"x": float(x), "y": float(y)}
                    for x, y in zip(target_x, target_y, strict=False)
                ],
            )
            with self.calibration_lock:
                self.calibration_error = (
                    f"calibration_rmse_too_high:{rmse:.4f}>"
                    f"{DEFAULT_CALIBRATION_MAX_RMSE:.4f}"
                )
                self.calibration_active = False
                self.calibration_started_at = None
            self.emit_status(
                "calibration_failed",
                calibration_required=True,
                rmse_normalized=round(rmse, 6),
                max_rmse_normalized=DEFAULT_CALIBRATION_MAX_RMSE,
            )
            return
        x_min, x_max = fit_axis(
            [sample["raw_x"] for sample in samples],
            [sample["target_x"] for sample in samples],
            DEFAULT_X_MIN,
            DEFAULT_X_MAX,
        )
        y_min, y_max = fit_axis(
            [sample["raw_y"] for sample in samples],
            [sample["target_y"] for sample in samples],
            DEFAULT_Y_MIN,
            DEFAULT_Y_MAX,
        )
        self.calibration = CalibrationProfile(
            x_min=x_min,
            x_max=x_max,
            y_min=y_min,
            y_max=y_max,
            source="guided_calibration",
            machine_profile=self.machine_profile,
            x_weights=x_weights,
            y_weights=y_weights,
            profile_version=CALIBRATION_PROFILE_VERSION,
            rmse_normalized=round(rmse, 6),
            point_errors=[round(float(error), 6) for error in point_errors],
            correction_x_weights=correction_x_weights,
            correction_y_weights=correction_y_weights,
        )
        self.calibration.save()
        self._log_calibration(
            "accepted",
            rmse_normalized=rmse,
            point_errors=[float(error) for error in point_errors],
            predicted_points=[
                {"x": float(x), "y": float(y)}
                for x, y in zip(predicted_x, predicted_y, strict=False)
            ],
            target_points=[
                {"x": float(x), "y": float(y)}
                for x, y in zip(target_x, target_y, strict=False)
            ],
        )
        self.smoothed_point = None
        self.last_smoothing_at = None
        with self.calibration_lock:
            self.calibration_active = False
            self.calibration_started_at = None
            self.calibration_error = None
        self.emit_status(
            "running",
            calibration_required=False,
            calibration_source=self.calibration.source,
            calibration={
                "x_min": self.calibration.x_min,
                "x_max": self.calibration.x_max,
                "y_min": self.calibration.y_min,
                "y_max": self.calibration.y_max,
                "source": self.calibration.source,
                "rmse_normalized": self.calibration.rmse_normalized,
                "point_errors": self.calibration.point_errors,
            },
            machine_profile=self.machine_profile,
        )
