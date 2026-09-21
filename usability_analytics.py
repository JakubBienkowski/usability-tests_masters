from __future__ import annotations

from math import hypot
from statistics import mean
from typing import Any


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def screen_diagonal(event: dict[str, Any]) -> float | None:
    payload = event.get("payload", {})
    context = event.get("context", {})
    viewport = payload.get("viewport") or context.get("viewport") or {}
    width = (
        _number(payload.get("screen_width"))
        or _number(viewport.get("physical_width"))
        or _number(viewport.get("width"))
    )
    height = (
        _number(payload.get("screen_height"))
        or _number(viewport.get("physical_height"))
        or _number(viewport.get("height"))
    )
    return hypot(width, height) if width and height else None


def normalized_distance_px(distance_px: float, event: dict[str, Any]) -> float | None:
    diagonal = screen_diagonal(event)
    return distance_px / diagonal if diagonal else None


def normalized_gaze_series(
    coordinates: list[tuple[Any, float, float, dict[str, Any]]],
) -> list[tuple[Any, float, float]]:
    result = []
    for timestamp, x, y, event in coordinates:
        payload = event.get("payload", {})
        nx, ny = _number(payload.get("normalized_x")), _number(payload.get("normalized_y"))
        if nx is not None and ny is not None:
            result.append((timestamp, nx, ny))
            continue
        diagonal = screen_diagonal(event)
        viewport = payload.get("viewport") or event.get("context", {}).get("viewport") or {}
        width = _number(payload.get("screen_width")) or _number(viewport.get("width"))
        height = _number(payload.get("screen_height")) or _number(viewport.get("height"))
        if diagonal and width and height:
            result.append((timestamp, x / width, y / height))
    return result


def ivt_metrics(
    points: list[tuple[Any, float, float]],
    velocity_threshold_normalized_s: float = 1.5,
    max_gap_ms: float = 250,
) -> dict[str, Any]:
    """Resolution-independent I-VT approximation in screen-width/height space."""
    saccades = 0
    fixation_segments = 0
    in_fixation = False
    velocities: list[float] = []
    for previous, current in zip(points, points[1:]):
        p_time, px, py = previous
        c_time, cx, cy = current
        interval_ms = (c_time - p_time).total_seconds() * 1000
        if interval_ms <= 0 or interval_ms > max_gap_ms:
            in_fixation = False
            continue
        velocity = hypot(cx - px, cy - py) / (interval_ms / 1000)
        velocities.append(velocity)
        if velocity >= velocity_threshold_normalized_s:
            saccades += 1
            in_fixation = False
        elif not in_fixation:
            fixation_segments += 1
            in_fixation = True
    return {
        "algorithm": "normalized_ivt_v1",
        "velocity_threshold_normalized_s": velocity_threshold_normalized_s,
        "max_gap_ms": max_gap_ms,
        "saccade_count": saccades,
        "fixation_segment_count": fixation_segments,
        "mean_velocity_normalized_s": round(mean(velocities), 4) if velocities else 0,
    }


def gaze_quality_summary(
    gaze_points: list[dict[str, Any]],
    gaze_lost: list[dict[str, Any]],
    sample_rate: float,
    low_confidence_ratio: float,
) -> dict[str, Any]:
    total = len(gaze_points) + len(gaze_lost)
    availability = len(gaze_points) / total if total else 0.0
    confidences = [
        float(event.get("payload", {}).get("confidence"))
        for event in gaze_points
        if isinstance(event.get("payload", {}).get("confidence"), (int, float))
    ]
    confidence = mean(confidences) if confidences else 0.0
    rate_score = min(sample_rate / 4.0, 1.0)
    score = max(
        0.0,
        min(
            1.0,
            0.4 * availability
            + 0.25 * confidence
            + 0.2 * rate_score
            + 0.15 * (1 - low_confidence_ratio),
        ),
    )
    status = "green" if score >= 0.75 else "yellow" if score >= 0.45 else "red"
    reasons = []
    if availability < 0.7:
        reasons.append("high_gaze_loss")
    if confidence < 0.5:
        reasons.append("low_mean_confidence")
    if sample_rate < 2:
        reasons.append("low_sample_rate")
    if not gaze_points:
        reasons.append("no_valid_gaze")
    return {
        "version": "gaze_quality_v1",
        "score": round(score, 4),
        "status": status,
        "availability_ratio": round(availability, 4),
        "mean_confidence": round(confidence, 4),
        "samples_per_second": round(sample_rate, 2),
        "low_confidence_ratio": round(low_confidence_ratio, 4),
        "reasons": reasons,
    }


def sus_score(answers: list[float]) -> float | None:
    if len(answers) != 10 or any(value < 1 or value > 5 for value in answers):
        return None
    contribution = sum(
        value - 1 if index % 2 == 0 else 5 - value
        for index, value in enumerate(answers)
    )
    return round(contribution * 2.5, 2)
