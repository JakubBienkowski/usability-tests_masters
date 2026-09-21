from __future__ import annotations

from datetime import datetime, timezone
from math import hypot
from statistics import median
from typing import Any


MODEL_VERSION = "mfem_interpretable_v1"
WINDOW_SECONDS = 10
INTERACTION_TYPES = {
    "mouse_click",
    "mouse_move",
    "scroll",
    "key_input",
    "text_input_metadata",
    "route_changed",
}


def _timestamp(event: dict[str, Any]) -> datetime | None:
    value = event.get("timestamp") or event.get("captured_at")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


def _mean(values: list[float], default: float = 0.0) -> float:
    return sum(values) / len(values) if values else default


def _gaze_xy(payload: dict[str, Any]) -> tuple[float, float] | None:
    x = payload.get("normalized_x")
    y = payload.get("normalized_y")
    if isinstance(x, (int, float)) and isinstance(y, (int, float)):
        return float(x), float(y)
    viewport = payload.get("viewport") or {}
    sx, sy = payload.get("screen_x"), payload.get("screen_y")
    width, height = viewport.get("width"), viewport.get("height")
    if all(isinstance(value, (int, float)) for value in (sx, sy, width, height)):
        return float(sx) / max(float(width), 1), float(sy) / max(float(height), 1)
    return None


def calculate_focus_evidence(events: list[dict[str, Any]]) -> dict[str, Any]:
    timed = [(timestamp, event) for event in events if (timestamp := _timestamp(event))]
    timed.sort(key=lambda item: item[0])
    if not timed:
        return {
            "model_version": MODEL_VERSION,
            "status": "insufficient_signal",
            "quality": 0.0,
            "windows": [],
            "probes": [],
        }

    start, end = timed[0][0], timed[-1][0]
    gaze_events = [event for _, event in timed if event.get("event_type") == "gaze_point"]
    baseline_gaze = gaze_events[: max(5, min(len(gaze_events), 120))]
    baseline_yaw = median(
        [
            float(event["payload"]["head_yaw_deg"])
            for event in baseline_gaze
            if isinstance(event.get("payload", {}).get("head_yaw_deg"), (int, float))
        ]
        or [0.0]
    )
    baseline_pitch = median(
        [
            float(event["payload"]["head_pitch_deg"])
            for event in baseline_gaze
            if isinstance(event.get("payload", {}).get("head_pitch_deg"), (int, float))
        ]
        or [0.0]
    )
    baseline_openness = median(
        [
            float(event["payload"]["eye_openness"])
            for event in baseline_gaze
            if isinstance(event.get("payload", {}).get("eye_openness"), (int, float))
        ]
        or [0.0]
    )

    windows: list[dict[str, Any]] = []
    window_start = start
    while window_start <= end:
        window_end = window_start.fromtimestamp(
            window_start.timestamp() + WINDOW_SECONDS, tz=window_start.tzinfo
        )
        current = [
            event
            for timestamp, event in timed
            if window_start <= timestamp < window_end
        ]
        gazes = [event for event in current if event.get("event_type") == "gaze_point"]
        lost = [event for event in current if event.get("event_type") == "gaze_lost"]
        interactions = [
            event for event in current if event.get("event_type") in INTERACTION_TYPES
        ]
        app_switches = sum(
            event.get("event_type") == "active_window_changed" for event in current
        )
        points = [
            point
            for event in gazes
            if (point := _gaze_xy(event.get("payload", {}))) is not None
        ]
        on_screen_ratio = (
            _mean([1.0 if 0 <= x <= 1 and 0 <= y <= 1 else 0.0 for x, y in points])
            if points
            else 0.0
        )
        confidences = [
            float(event["payload"]["confidence"])
            for event in gazes
            if isinstance(event.get("payload", {}).get("confidence"), (int, float))
        ]
        yaw_deviation = _mean(
            [
                abs(float(event["payload"]["head_yaw_deg"]) - baseline_yaw)
                for event in gazes
                if isinstance(event.get("payload", {}).get("head_yaw_deg"), (int, float))
            ]
        )
        pitch_deviation = _mean(
            [
                abs(float(event["payload"]["head_pitch_deg"]) - baseline_pitch)
                for event in gazes
                if isinstance(event.get("payload", {}).get("head_pitch_deg"), (int, float))
            ]
        )
        openness_values = [
            float(event["payload"]["eye_openness"])
            for event in gazes
            if isinstance(event.get("payload", {}).get("eye_openness"), (int, float))
        ]
        eye_narrowing = (
            _clamp((baseline_openness - median(openness_values)) / baseline_openness)
            if openness_values and baseline_openness > 0
            else 0.0
        )
        gaze_availability = _clamp(len(gazes) / (WINDOW_SECONDS * 4))
        loss_ratio = len(lost) / max(len(gazes) + len(lost), 1)
        head_stability = _clamp(1 - hypot(yaw_deviation, pitch_deviation) / 12)
        visual = _clamp(
            0.35 * on_screen_ratio
            + 0.30 * gaze_availability
            + 0.20 * (1 - loss_ratio)
            + 0.15 * head_stability
        )
        interaction_density = _clamp(len(interactions) / 8)
        interaction = _clamp(
            0.75 * interaction_density + 0.25 * (1 - min(app_switches / 3, 1))
        )
        cognitive_effort = _clamp(0.5 + eye_narrowing * 0.5)
        quality = _clamp(
            0.45 * gaze_availability
            + 0.30 * _mean(confidences, 0.0)
            + 0.25 * (1 - loss_ratio)
        )
        score = _clamp(0.45 * visual + 0.35 * interaction + 0.20 * cognitive_effort)
        status = (
            "insufficient_signal"
            if quality < 0.3
            else "likely_engaged"
            if score >= 0.68
            else "possible_disengagement"
            if score < 0.42
            else "uncertain"
        )
        windows.append(
            {
                "start": window_start.isoformat(),
                "end": min(window_end, end).isoformat(),
                "visual_engagement": visual,
                "interaction_engagement": interaction,
                "cognitive_effort_evidence": cognitive_effort,
                "focus_evidence": score,
                "quality": quality,
                "status": status,
                "evidence": {
                    "gaze_samples": len(gazes),
                    "gaze_lost": len(lost),
                    "on_screen_ratio": round(on_screen_ratio, 4),
                    "avg_gaze_confidence": round(_mean(confidences), 4),
                    "head_deviation_deg": round(hypot(yaw_deviation, pitch_deviation), 3),
                    "eye_narrowing_from_baseline": eye_narrowing,
                    "interaction_count": len(interactions),
                    "app_switch_count": app_switches,
                },
            }
        )
        window_start = window_end

    probes = [
        {
            "timestamp": timestamp.isoformat(),
            "rating": event.get("payload", {}).get("rating"),
            "mind_wandering": event.get("payload", {}).get("mind_wandering"),
            "source": event.get("source"),
        }
        for timestamp, event in timed
        if event.get("event_type") == "attention_probe_response"
    ]
    valid_windows = [window for window in windows if window["status"] != "insufficient_signal"]
    return {
        "model_version": MODEL_VERSION,
        "window_seconds": WINDOW_SECONDS,
        "status": (
            max(
                ("likely_engaged", "uncertain", "possible_disengagement"),
                key=lambda value: sum(window["status"] == value for window in valid_windows),
            )
            if valid_windows
            else "insufficient_signal"
        ),
        "focus_evidence": round(
            _mean([window["focus_evidence"] for window in valid_windows]), 4
        ),
        "visual_engagement": round(
            _mean([window["visual_engagement"] for window in valid_windows]), 4
        ),
        "interaction_engagement": round(
            _mean([window["interaction_engagement"] for window in valid_windows]), 4
        ),
        "cognitive_effort_evidence": round(
            _mean([window["cognitive_effort_evidence"] for window in valid_windows]), 4
        ),
        "quality": round(_mean([window["quality"] for window in windows]), 4),
        "baseline": {
            "head_yaw_deg": round(baseline_yaw, 4),
            "head_pitch_deg": round(baseline_pitch, 4),
            "eye_openness": round(baseline_openness, 6),
        },
        "probes": probes,
        "windows": windows,
        "interpretation": "Evidence score, not a direct measurement or diagnosis of attention.",
    }
