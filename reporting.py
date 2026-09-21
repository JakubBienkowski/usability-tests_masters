from __future__ import annotations

import html
import json
from collections import Counter
from datetime import datetime
from typing import Any


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _event_timestamp(event: dict[str, Any]) -> datetime | None:
    return _parse_timestamp(event.get("timestamp") or event.get("captured_at"))


def _nested_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    nested = metadata.get("metadata")
    return nested if isinstance(nested, dict) else {}


def _mode(metadata: dict[str, Any], events: list[dict[str, Any]]) -> str:
    nested = _nested_metadata(metadata)
    candidate = nested.get("mode") or metadata.get("mode")
    if candidate in {"desktop_only", "web_desktop"}:
        return candidate
    for event in events:
        payload = event.get("payload") or {}
        candidate = payload.get("mode")
        if candidate in {"desktop_only", "web_desktop"}:
            return candidate
    web_types = {"route_changed", "gaze_dom_context", "web_vitals_snapshot"}
    return (
        "web_desktop"
        if any(event.get("event_type") in web_types for event in events)
        else "desktop_only"
    )


def session_lifecycle(
    metadata: dict[str, Any], events: list[dict[str, Any]]
) -> dict[str, Any]:
    nested = _nested_metadata(metadata)
    starts = [
        timestamp
        for event in events
        if event.get("event_type") == "session_started"
        and (timestamp := _event_timestamp(event))
    ]
    stops = [
        timestamp
        for event in events
        if event.get("event_type") == "session_stopped"
        and (timestamp := _event_timestamp(event))
    ]
    started_at = (
        _parse_timestamp(metadata.get("started_at"))
        or (min(starts) if starts else None)
    )
    ended_at = (
        _parse_timestamp(nested.get("ended_at"))
        or (max(stops) if stops else None)
    )
    explicit_status = nested.get("status")
    completed = bool(stops or explicit_status == "completed")
    if starts and stops and max(starts) > max(stops):
        completed = False
        ended_at = None
    duration_seconds = (
        max((ended_at - started_at).total_seconds(), 0.0)
        if started_at and ended_at
        else None
    )
    return {
        "status": "completed" if completed else "recording",
        "completed": completed,
        "mode": _mode(metadata, events),
        "started_at": started_at.isoformat() if started_at else None,
        "ended_at": ended_at.isoformat() if ended_at else None,
        "duration_seconds": round(duration_seconds, 2)
        if duration_seconds is not None
        else None,
    }


def build_session_report(
    *,
    session_id: str,
    metadata: dict[str, Any],
    events: list[dict[str, Any]],
    metrics: dict[str, Any],
    timeline: dict[str, Any],
    recording_available: bool,
) -> dict[str, Any]:
    lifecycle = session_lifecycle(metadata, events)
    event_counts = Counter(
        event.get("event_type", "unknown") for event in events
    )
    sources = sorted(
        {
            str(event.get("source"))
            for event in events
            if event.get("source")
        }
    )
    has_web = lifecycle["mode"] == "web_desktop" or bool(
        metrics.get("rrweb_chunks")
        or event_counts["route_changed"]
        or event_counts["web_vitals_snapshot"]
    )
    has_desktop = lifecycle["mode"] == "desktop_only" or any(
        source in {"desktop_agent", "desktop"} for source in sources
    )
    has_gaze = metrics.get("gaze_point_count", 0) > 0
    has_tasks = metrics.get("task_started_count", 0) > 0
    mfem = metrics.get("multimodal_focus_evidence") or {}
    mfem_windows = mfem.get("windows") or []
    mfem_statuses = Counter(
        window.get("status", "unknown") for window in mfem_windows
    )

    app_durations: Counter[str] = Counter()
    app_switches = 0
    last_app = None
    last_time = None
    for event in sorted(events, key=lambda item: item.get("timestamp", "")):
        context = event.get("context") or {}
        payload = event.get("payload") or {}
        app_name = (
            context.get("app_name")
            or payload.get("app_name")
            or context.get("window_title")
        )
        timestamp = _event_timestamp(event)
        if last_app and last_time and timestamp:
            app_durations[last_app] += max(
                (timestamp - last_time).total_seconds(), 0.0
            )
        if app_name and last_app and app_name != last_app:
            app_switches += 1
        if app_name:
            last_app = str(app_name)
        if timestamp:
            last_time = timestamp

    warnings: list[str] = []
    if not lifecycle["completed"]:
        warnings.append(
            "The session has no final stop marker. This is a draft report."
        )
    if not recording_available:
        warnings.append("No playable screen recording is available.")
    if not has_gaze:
        warnings.append(
            "No gaze samples were captured; gaze and MFEM results are unavailable."
        )
    else:
        quality = metrics.get("gaze_quality") or {}
        if quality.get("status") in {"yellow", "red"}:
            warnings.append(
                "Gaze quality is below green; interpret spatial metrics with caution."
            )
    if has_web and not metrics.get("rrweb_chunks"):
        warnings.append("Web mode was used, but no rrweb DOM replay was stored.")
    if has_tasks and metrics.get("open_task_count"):
        warnings.append(
            f"{metrics['open_task_count']} task(s) have no completion marker."
        )

    return {
        "report_version": "session_report_v2",
        "session_id": session_id,
        "lifecycle": lifecycle,
        "sources": sources,
        "channels": {
            "desktop": has_desktop,
            "web": has_web,
            "gaze": has_gaze,
            "tasks": has_tasks,
            "screen_recording": recording_available,
            "dom_replay": bool(metrics.get("rrweb_chunks")),
        },
        "warnings": warnings,
        "summary": {
            "task_success_rate": metrics.get("task_success_rate")
            if has_tasks
            else None,
            "weighted_task_effectiveness": metrics.get(
                "weighted_task_effectiveness"
            )
            if has_tasks
            else None,
            "avg_task_duration_ms": metrics.get("avg_task_duration_ms")
            if has_tasks
            else None,
            "avg_seq_rating": metrics.get("avg_seq_rating")
            if metrics.get("seq_response_count")
            else None,
            "avg_sus_score": metrics.get("avg_sus_score")
            if metrics.get("sus_response_count")
            else None,
            "gaze_quality": metrics.get("gaze_quality") if has_gaze else None,
            "friction_marker_count": metrics.get("friction_marker_count", 0),
            "high_severity_friction_count": metrics.get(
                "high_severity_friction_count", 0
            ),
            "client_error_count": metrics.get("client_error_count", 0),
        },
        "tasks": metrics.get("completed_task_durations", []),
        "desktop": {
            "mouse_click_count": metrics.get("mouse_click_count", 0),
            "scroll_event_count": metrics.get("scroll_event_count", 0),
            "app_switch_count": app_switches,
            "top_applications": [
                {"name": name, "duration_seconds": round(seconds, 2)}
                for name, seconds in app_durations.most_common(5)
            ],
        }
        if has_desktop
        else None,
        "web": {
            "route_change_count": metrics.get("route_change_count", 0),
            "unique_route_count": metrics.get("unique_route_count", 0),
            "route_revisit_count": metrics.get("route_revisit_count", 0),
            "max_scroll_depth_ratio": metrics.get(
                "max_scroll_depth_ratio", 0
            ),
            "input_correction_count": metrics.get(
                "input_correction_count", 0
            ),
            "client_error_count": metrics.get("client_error_count", 0),
            "web_vitals": metrics.get("web_vitals", {}),
            "web_vital_ratings": metrics.get("web_vital_ratings", {}),
            "rrweb_chunks": metrics.get("rrweb_chunks", 0),
        }
        if has_web
        else None,
        "gaze": {
            "quality": metrics.get("gaze_quality"),
            "point_count": metrics.get("gaze_point_count", 0),
            "sample_rate": metrics.get("gaze_samples_per_second", 0),
            "lost_count": metrics.get("gaze_lost_count", 0),
            "fixation_count": metrics.get("gaze_fixation_count", 0),
            "path_length_normalized": metrics.get(
                "gaze_path_length_normalized", 0
            ),
            "ivt": metrics.get("gaze_ivt", {}),
            "avg_gaze_cursor_distance_ratio": metrics.get(
                "avg_gaze_cursor_distance_screen_diagonal_ratio", 0
            ),
            "top_fixated_elements": metrics.get("top_fixated_elements", []),
        }
        if has_gaze
        else None,
        "friction": {
            "counts": metrics.get("friction_marker_counts", {}),
            "total": metrics.get("friction_marker_count", 0),
            "high_severity": metrics.get(
                "high_severity_friction_count", 0
            ),
        },
        "mfem": {
            "model_version": mfem.get("model_version"),
            "window_count": len(mfem_windows),
            "status_counts": dict(mfem_statuses),
            "probe_count": len(mfem.get("probes") or []),
        },
        "evidence": {
            "event_count": timeline.get("counts", {}).get("events", len(events)),
            "timeline_items": timeline.get("counts", {}).get(
                "timeline_items", 0
            ),
            "screen_recording_url": (
                f"/api/sessions/{session_id}/screen-recording"
                if recording_available
                else None
            ),
            "replay_url": f"/?mode=replay&replay={session_id}",
            "mfem_csv_url": f"/api/sessions/{session_id}/mfem.csv",
            "report_json_url": f"/api/sessions/{session_id}/report.json",
        },
    }


def _format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    minutes, remainder = divmod(int(seconds), 60)
    return f"{minutes}m {remainder}s" if minutes else f"{remainder}s"


def render_session_report_html(report: dict[str, Any]) -> str:
    esc = lambda value: html.escape(str(value))
    lifecycle = report["lifecycle"]
    summary = report["summary"]
    channels = report["channels"]
    cards = [
        ("Status", lifecycle["status"]),
        ("Mode", lifecycle["mode"]),
        ("Duration", _format_duration(lifecycle.get("duration_seconds"))),
        (
            "Task success",
            f"{summary['task_success_rate']:.1%}"
            if summary.get("task_success_rate") is not None
            else "not measured",
        ),
        (
            "SEQ",
            f"{summary['avg_seq_rating']}/7"
            if summary.get("avg_seq_rating") is not None
            else "not collected",
        ),
        (
            "SUS",
            f"{summary['avg_sus_score']}/100"
            if summary.get("avg_sus_score") is not None
            else "not collected",
        ),
        (
            "Gaze quality",
            (
                f"{summary['gaze_quality']['status']} "
                f"({summary['gaze_quality']['score']:.2f})"
            )
            if summary.get("gaze_quality")
            else "not available",
        ),
        ("Friction candidates", summary["friction_marker_count"]),
    ]
    card_html = "".join(
        f'<div class="card"><span>{esc(label)}</span><strong>{esc(value)}</strong></div>'
        for label, value in cards
    )
    warning_html = "".join(
        f"<li>{esc(warning)}</li>" for warning in report["warnings"]
    ) or "<li>No automatic data-quality warnings.</li>"
    channel_html = "".join(
        f'<span class="badge {("ok" if available else "off")}">'
        f'{esc(name.replace("_", " "))}: {("yes" if available else "no")}</span>'
        for name, available in channels.items()
    )
    task_rows = "".join(
        "<tr>"
        f"<td>{esc(task.get('label') or task.get('task_id') or '—')}</td>"
        f"<td>{esc(task.get('outcome') or 'not assessed')}</td>"
        f"<td>{float(task.get('duration_ms') or 0) / 1000:.1f}s</td>"
        f"<td>{esc(task.get('seq_rating') or '—')}</td>"
        f"<td>{task.get('click_count', 0)}</td>"
        f"<td>{task.get('scroll_event_count', 0)}</td>"
        f"<td>{task.get('friction_marker_count', 0)}</td>"
        f"<td>{task.get('client_error_count', 0)}</td>"
        "</tr>"
        for task in report["tasks"]
    ) or '<tr><td colspan="8">No completed tasks were recorded.</td></tr>'

    desktop = report.get("desktop")
    desktop_html = ""
    if desktop:
        apps = "".join(
            f"<li>{esc(item['name'])}: {item['duration_seconds']:.1f}s</li>"
            for item in desktop["top_applications"]
        ) or "<li>No active-application duration data.</li>"
        desktop_html = f"""
        <section><h2>Desktop behaviour</h2>
        <div class="metrics">
        <div>Clicks<strong>{desktop['mouse_click_count']}</strong></div>
        <div>Scroll events<strong>{desktop['scroll_event_count']}</strong></div>
        <div>Application switches<strong>{desktop['app_switch_count']}</strong></div>
        </div><h3>Most active applications</h3><ul>{apps}</ul></section>"""

    web = report.get("web")
    web_html = ""
    if web:
        vital_rows = "".join(
            f"<tr><td>{esc(name.upper())}</td><td>{esc(value)}</td>"
            f"<td>{esc(web['web_vital_ratings'].get(name, 'not measured'))}</td></tr>"
            for name, value in web["web_vitals"].items()
        )
        web_html = f"""
        <section><h2>Web behaviour and technical UX</h2>
        <div class="metrics">
        <div>Routes<strong>{web['route_change_count']}</strong></div>
        <div>Revisits<strong>{web['route_revisit_count']}</strong></div>
        <div>Scroll depth<strong>{web['max_scroll_depth_ratio']:.0%}</strong></div>
        <div>Input corrections<strong>{web['input_correction_count']}</strong></div>
        <div>Client errors<strong>{web['client_error_count']}</strong></div>
        <div>rrweb chunks<strong>{web['rrweb_chunks']}</strong></div>
        </div>
        <table><thead><tr><th>Web Vital</th><th>Value</th><th>Rating</th></tr></thead>
        <tbody>{vital_rows}</tbody></table></section>"""

    gaze = report.get("gaze")
    gaze_html = ""
    if gaze:
        quality = gaze["quality"] or {}
        reasons = "".join(
            f"<li>{esc(reason)}</li>" for reason in quality.get("reasons", [])
        ) or "<li>No quality warnings.</li>"
        gaze_html = f"""
        <section><h2>Gaze evidence</h2>
        <div class="metrics">
        <div>Valid points<strong>{gaze['point_count']}</strong></div>
        <div>Sample rate<strong>{gaze['sample_rate']}/s</strong></div>
        <div>Gaze lost<strong>{gaze['lost_count']}</strong></div>
        <div>DOM fixations<strong>{gaze['fixation_count']}</strong></div>
        <div>Normalised path<strong>{gaze['path_length_normalized']}</strong></div>
        <div>I-VT saccades<strong>{gaze['ivt'].get('saccade_count', 0)}</strong></div>
        </div><h3>Quality reasons</h3><ul>{reasons}</ul></section>"""

    mfem = report["mfem"]
    mfem_rows = "".join(
        f"<tr><td>{esc(status)}</td><td>{count}</td></tr>"
        for status, count in mfem["status_counts"].items()
    ) or '<tr><td colspan="2">No MFEM windows.</td></tr>'
    recording = report["evidence"].get("screen_recording_url")
    recording_html = (
        f'<video controls preload="metadata" src="{esc(recording)}"></video>'
        if recording
        else "<p>No screen recording is available.</p>"
    )
    json_ld = html.escape(
        json.dumps(
            {
                "report_version": report["report_version"],
                "session_id": report["session_id"],
            }
        )
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Usability report — {esc(report['session_id'])}</title>
<style>
:root{{--ink:#172033;--muted:#64748b;--line:#dbe2ea;--accent:#2457d6}}
*{{box-sizing:border-box}}body{{font:15px system-ui;margin:0;color:var(--ink);background:#f5f7fb}}
main{{max-width:1120px;margin:0 auto;padding:32px}}header,section{{background:white;border:1px solid var(--line);border-radius:14px;padding:22px;margin-bottom:18px}}
h1{{margin:0 0 6px}}h2{{margin-top:0}}.muted{{color:var(--muted)}}.cards{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:18px 0}}
.card,.metrics div{{border:1px solid var(--line);border-radius:10px;padding:12px}}.card span,.metrics div{{color:var(--muted)}}.card strong,.metrics strong{{display:block;color:var(--ink);font-size:1.25rem;margin-top:5px}}
.metrics{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-bottom:16px}}
.badge{{display:inline-block;padding:5px 9px;border-radius:999px;margin:3px;background:#dcfce7;color:#166534}}.badge.off{{background:#e2e8f0;color:#64748b}}
.warning{{border-left:4px solid #d97706;background:#fffbeb}}table{{width:100%;border-collapse:collapse}}th,td{{padding:9px;border:1px solid var(--line);text-align:left}}video{{width:100%;max-height:520px;background:#000}}
.actions a,.actions button{{display:inline-block;border:0;border-radius:8px;padding:9px 12px;margin:4px;background:var(--accent);color:white;text-decoration:none;cursor:pointer}}
@media(max-width:760px){{.cards,.metrics{{grid-template-columns:1fr 1fr}}main{{padding:12px}}}}
@media print{{body{{background:white}}main{{max-width:none;padding:0}}header,section{{break-inside:avoid;border-color:#bbb}}.no-print,video{{display:none}}}}
</style></head><body><main data-report="{json_ld}">
<header><h1>Usability session report</h1>
<p class="muted">Session {esc(report['session_id'])} · {esc(lifecycle['mode'])} ·
{esc(lifecycle['started_at'] or 'unknown start')} — {esc(lifecycle['ended_at'] or 'not stopped')}</p>
<div>{channel_html}</div><div class="cards">{card_html}</div>
<div class="actions no-print"><button onclick="window.print()">Save / print PDF</button>
<a href="{esc(report['evidence']['report_json_url'])}">Report JSON</a>
<a href="{esc(report['evidence']['mfem_csv_url'])}">MFEM CSV</a></div></header>
<section class="warning"><h2>Interpretation and data quality</h2><ul>{warning_html}</ul></section>
<section><h2>Tasks</h2><table><thead><tr><th>Task</th><th>Outcome</th><th>Time</th>
<th>SEQ</th><th>Clicks</th><th>Scroll</th><th>Friction</th><th>Errors</th></tr></thead>
<tbody>{task_rows}</tbody></table></section>
{desktop_html}{web_html}{gaze_html}
<section><h2>Multimodal focus evidence</h2>
<p>Model: {esc(mfem.get('model_version') or 'not available')}. The values are
evidence candidates, not a psychological diagnosis.</p>
<table><thead><tr><th>Status</th><th>Windows</th></tr></thead><tbody>{mfem_rows}</tbody></table></section>
<section><h2>Screen recording</h2>{recording_html}</section>
</main></body></html>"""
