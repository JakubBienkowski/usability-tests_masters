from __future__ import annotations

import json
import os
from datetime import datetime
from math import sqrt
from typing import Any

import psycopg
from psycopg.rows import dict_row


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://ux_tracker:ux_tracker@postgres:5432/ux_tracker",
)


def get_connection() -> psycopg.Connection[Any]:
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def init_db() -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS study_sessions (
                    session_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    started_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    next_sequence INTEGER NOT NULL DEFAULT 1,
                    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS gaze_cursor_samples (
                    id BIGSERIAL PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES study_sessions(session_id) ON DELETE CASCADE,
                    timestamp TIMESTAMPTZ NOT NULL,
                    source_event_type TEXT NOT NULL,
                    gaze_x DOUBLE PRECISION NOT NULL,
                    gaze_y DOUBLE PRECISION NOT NULL,
                    cursor_x DOUBLE PRECISION NOT NULL,
                    cursor_y DOUBLE PRECISION NOT NULL,
                    distance_px DOUBLE PRECISION NOT NULL,
                    gaze_age_ms DOUBLE PRECISION NOT NULL,
                    cursor_age_ms DOUBLE PRECISION NOT NULL,
                    clarity_signal TEXT NOT NULL,
                    context JSONB NOT NULL DEFAULT '{}'::jsonb
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_gaze_cursor_samples_session_time
                ON gaze_cursor_samples (session_id, timestamp)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS gaze_cursor_session_metrics (
                    session_id TEXT PRIMARY KEY REFERENCES study_sessions(session_id) ON DELETE CASCADE,
                    sample_count INTEGER NOT NULL DEFAULT 0,
                    avg_distance_px DOUBLE PRECISION NOT NULL DEFAULT 0,
                    max_distance_px DOUBLE PRECISION NOT NULL DEFAULT 0,
                    close_sample_count INTEGER NOT NULL DEFAULT 0,
                    far_sample_count INTEGER NOT NULL DEFAULT 0,
                    close_ratio DOUBLE PRECISION NOT NULL DEFAULT 0,
                    last_distance_px DOUBLE PRECISION,
                    last_clarity_signal TEXT,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
        connection.commit()


def _as_json_text(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=True)


def upsert_session(
    session_id: str,
    source: str,
    started_at: datetime,
    updated_at: datetime,
    next_sequence: int,
    metadata: dict[str, Any],
) -> None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO study_sessions (
                    session_id,
                    source,
                    started_at,
                    updated_at,
                    next_sequence,
                    metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (session_id) DO UPDATE
                SET
                    source = EXCLUDED.source,
                    started_at = COALESCE(study_sessions.started_at, EXCLUDED.started_at),
                    updated_at = EXCLUDED.updated_at,
                    next_sequence = EXCLUDED.next_sequence,
                    metadata = study_sessions.metadata || EXCLUDED.metadata
                """,
                (
                    session_id,
                    source,
                    started_at,
                    updated_at,
                    next_sequence,
                    _as_json_text(metadata),
                ),
            )
        connection.commit()


def get_session(session_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT session_id, source, started_at, updated_at, next_sequence, metadata
                FROM study_sessions
                WHERE session_id = %s
                """,
                (session_id,),
            )
            row = cursor.fetchone()
    if not row:
        return None
    return {
        "session_id": row["session_id"],
        "source": row["source"],
        "started_at": row["started_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        "next_sequence": row["next_sequence"],
        "metadata": row["metadata"] or {},
    }


def list_sessions() -> list[dict[str, Any]]:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT session_id, source, started_at, updated_at, next_sequence, metadata
                FROM study_sessions
                ORDER BY updated_at DESC
                """
            )
            rows = cursor.fetchall()
    return [
        {
            "session_id": row["session_id"],
            "source": row["source"],
            "started_at": row["started_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
            "next_sequence": row["next_sequence"],
            "metadata": row["metadata"] or {},
        }
        for row in rows
    ]


def insert_gaze_cursor_sample(
    *,
    session_id: str,
    timestamp: datetime,
    source_event_type: str,
    gaze_x: float,
    gaze_y: float,
    cursor_x: float,
    cursor_y: float,
    gaze_age_ms: float,
    cursor_age_ms: float,
    clarity_signal: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    distance_px = sqrt((gaze_x - cursor_x) ** 2 + (gaze_y - cursor_y) ** 2)
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO gaze_cursor_samples (
                    session_id,
                    timestamp,
                    source_event_type,
                    gaze_x,
                    gaze_y,
                    cursor_x,
                    cursor_y,
                    distance_px,
                    gaze_age_ms,
                    cursor_age_ms,
                    clarity_signal,
                    context
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    session_id,
                    timestamp,
                    source_event_type,
                    gaze_x,
                    gaze_y,
                    cursor_x,
                    cursor_y,
                    distance_px,
                    gaze_age_ms,
                    cursor_age_ms,
                    clarity_signal,
                    _as_json_text(context),
                ),
            )
            cursor.execute(
                """
                INSERT INTO gaze_cursor_session_metrics (
                    session_id,
                    sample_count,
                    avg_distance_px,
                    max_distance_px,
                    close_sample_count,
                    far_sample_count,
                    close_ratio,
                    last_distance_px,
                    last_clarity_signal,
                    updated_at
                )
                VALUES (
                    %s,
                    1,
                    %s,
                    %s,
                    CASE WHEN %s = 'close' THEN 1 ELSE 0 END,
                    CASE WHEN %s = 'far' THEN 1 ELSE 0 END,
                    CASE WHEN %s = 'close' THEN 1.0 ELSE 0.0 END,
                    %s,
                    %s,
                    %s
                )
                ON CONFLICT (session_id) DO UPDATE
                SET
                    sample_count = gaze_cursor_session_metrics.sample_count + 1,
                    avg_distance_px = (
                        gaze_cursor_session_metrics.avg_distance_px * gaze_cursor_session_metrics.sample_count
                        + EXCLUDED.last_distance_px
                    ) / (gaze_cursor_session_metrics.sample_count + 1),
                    max_distance_px = GREATEST(gaze_cursor_session_metrics.max_distance_px, EXCLUDED.last_distance_px),
                    close_sample_count = gaze_cursor_session_metrics.close_sample_count
                        + CASE WHEN EXCLUDED.last_clarity_signal = 'close' THEN 1 ELSE 0 END,
                    far_sample_count = gaze_cursor_session_metrics.far_sample_count
                        + CASE WHEN EXCLUDED.last_clarity_signal = 'far' THEN 1 ELSE 0 END,
                    close_ratio = (
                        gaze_cursor_session_metrics.close_sample_count
                        + CASE WHEN EXCLUDED.last_clarity_signal = 'close' THEN 1 ELSE 0 END
                    )::DOUBLE PRECISION / (gaze_cursor_session_metrics.sample_count + 1),
                    last_distance_px = EXCLUDED.last_distance_px,
                    last_clarity_signal = EXCLUDED.last_clarity_signal,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    session_id,
                    distance_px,
                    distance_px,
                    clarity_signal,
                    clarity_signal,
                    clarity_signal,
                    distance_px,
                    clarity_signal,
                    timestamp,
                ),
            )
        connection.commit()
    return {
        "distance_px": round(distance_px, 2),
        "clarity_signal": clarity_signal,
        "gaze_age_ms": round(gaze_age_ms, 2),
        "cursor_age_ms": round(cursor_age_ms, 2),
    }


def get_gaze_cursor_metrics(session_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    session_id,
                    sample_count,
                    avg_distance_px,
                    max_distance_px,
                    close_sample_count,
                    far_sample_count,
                    close_ratio,
                    last_distance_px,
                    last_clarity_signal,
                    updated_at
                FROM gaze_cursor_session_metrics
                WHERE session_id = %s
                """,
                (session_id,),
            )
            row = cursor.fetchone()
    if not row:
        return None
    return {
        "session_id": row["session_id"],
        "sample_count": row["sample_count"],
        "avg_distance_px": round(row["avg_distance_px"], 2),
        "max_distance_px": round(row["max_distance_px"], 2),
        "close_sample_count": row["close_sample_count"],
        "far_sample_count": row["far_sample_count"],
        "close_ratio": round(row["close_ratio"], 4),
        "last_distance_px": round(row["last_distance_px"], 2)
        if row["last_distance_px"] is not None
        else None,
        "last_clarity_signal": row["last_clarity_signal"],
        "updated_at": row["updated_at"].isoformat(),
    }
