from __future__ import annotations

from typing import Any


GAZE_CONTRACT_VERSION = "1.0"
DEFAULT_GAZE_SAMPLE_INTERVAL_MS = 200
DEFAULT_FIXATION_MIN_DURATION_MS = 500
DEFAULT_CONFIDENCE_THRESHOLD = 0.35
DEFAULT_GAZE_LOST_TIMEOUT_MS = 1000


def provider_details(
    provider_name: str,
    provider_type: str,
    sample_interval_ms: int = DEFAULT_GAZE_SAMPLE_INTERVAL_MS,
) -> dict[str, Any]:
    return {
        "gaze_contract_version": GAZE_CONTRACT_VERSION,
        "provider": provider_name,
        "provider_type": provider_type,
        "sample_interval_ms": sample_interval_ms,
    }


def status_payload(
    provider_name: str,
    provider_type: str,
    status: str,
    sample_interval_ms: int = DEFAULT_GAZE_SAMPLE_INTERVAL_MS,
    **extra: Any,
) -> dict[str, Any]:
    payload = provider_details(provider_name, provider_type, sample_interval_ms)
    payload["status"] = status
    payload.update(extra)
    return payload


def gaze_point_payload(
    provider_name: str,
    provider_type: str,
    screen_x: float,
    screen_y: float,
    confidence: float | None,
    viewport_width: int | None = None,
    viewport_height: int | None = None,
    sample_interval_ms: int = DEFAULT_GAZE_SAMPLE_INTERVAL_MS,
    **extra: Any,
) -> dict[str, Any]:
    payload = provider_details(provider_name, provider_type, sample_interval_ms)
    payload.update(
        {
            "screen_x": round(screen_x),
            "screen_y": round(screen_y),
            "confidence": confidence,
            "confidence_threshold": DEFAULT_CONFIDENCE_THRESHOLD,
        }
    )
    if viewport_width and viewport_height:
        payload["viewport"] = {
            "width": viewport_width,
            "height": viewport_height,
        }
        payload["normalized_x"] = round(screen_x / max(viewport_width, 1), 6)
        payload["normalized_y"] = round(screen_y / max(viewport_height, 1), 6)
    payload.update(extra)
    return payload


def gaze_lost_payload(
    provider_name: str,
    provider_type: str,
    reason: str,
    sample_interval_ms: int = DEFAULT_GAZE_SAMPLE_INTERVAL_MS,
    **extra: Any,
) -> dict[str, Any]:
    payload = provider_details(provider_name, provider_type, sample_interval_ms)
    payload["reason"] = reason
    payload.update(extra)
    return payload


def gaze_fixation_payload(
    provider_name: str,
    provider_type: str,
    duration_ms: int,
    sample_interval_ms: int = DEFAULT_GAZE_SAMPLE_INTERVAL_MS,
    **extra: Any,
) -> dict[str, Any]:
    payload = provider_details(provider_name, provider_type, sample_interval_ms)
    payload["duration_ms"] = duration_ms
    payload["fixation_min_duration_ms"] = DEFAULT_FIXATION_MIN_DURATION_MS
    payload.update(extra)
    return payload
