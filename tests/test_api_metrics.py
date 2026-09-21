import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import main


def event(event_type, timestamp, payload=None, source="browser_extension"):
    return {
        "session_id": "sess_test",
        "source": source,
        "event_type": event_type,
        "timestamp": timestamp,
        "context": {},
        "payload": payload or {},
    }


class ApiMetricsTest(unittest.TestCase):
    def test_report_endpoints_share_versioned_report_model(self):
        events = [
            event(
                "session_stopped",
                "2026-05-16T10:02:00+00:00",
                {"mode": "desktop_only"},
                source="desktop_agent",
            )
        ]
        metrics = {
            "rrweb_chunks": 0,
            "gaze_point_count": 0,
            "task_started_count": 0,
            "friction_marker_count": 0,
            "high_severity_friction_count": 0,
            "client_error_count": 0,
            "completed_task_durations": [],
            "mouse_click_count": 0,
            "scroll_event_count": 0,
            "friction_marker_counts": {},
            "multimodal_focus_evidence": {
                "model_version": "mfem_interpretable_v1",
                "windows": [],
                "probes": [],
            },
            "open_task_count": 0,
        }
        timeline = {"counts": {"events": 1, "timeline_items": 1}}
        with patch.object(
            main,
            "load_session_metadata",
            return_value={
                "session_id": "sess_test",
                "started_at": "2026-05-16T10:00:00+00:00",
                "metadata": {"mode": "desktop_only"},
            },
        ), patch.object(main, "load_json_lines", return_value=events), patch.object(
            main, "get_session_metrics", new=AsyncMock(return_value=metrics)
        ), patch.object(
            main, "get_session_timeline", new=AsyncMock(return_value=timeline)
        ), patch.object(
            main, "screen_recording_path", return_value=None
        ):
            report = asyncio.run(main.get_session_report_json("sess_test"))
            html_response = asyncio.run(main.get_session_report("sess_test"))

        self.assertEqual(report["report_version"], "session_report_v2")
        self.assertTrue(report["lifecycle"]["completed"])
        self.assertEqual(report["lifecycle"]["mode"], "desktop_only")
        self.assertIn(b"session_report_v2", html_response.body)

    def test_screen_recording_path_returns_non_empty_webm(self):
        with tempfile.TemporaryDirectory() as directory:
            session_dir = Path(directory)
            recording = session_dir / "screen_recording.webm"
            recording.write_bytes(b"webm")
            with patch.object(main, "session_path", return_value=session_dir):
                self.assertEqual(main.screen_recording_path("sess_test"), recording)

    def test_session_listing_does_not_scan_event_history(self):
        item = {
            "session_id": "sess_listing",
            "metadata": {
                "status": "completed",
                "ended_at": "2026-01-01T00:01:00+00:00",
            },
        }
        with (
            patch.object(main, "db_list_sessions", return_value=[item]),
            patch.object(
                main,
                "load_json_lines",
                side_effect=AssertionError("listing must not load event history"),
            ),
            patch.object(main, "screen_recording_path", return_value=None),
        ):
            result = asyncio.run(main.list_sessions())

        self.assertTrue(result["sessions"][0]["lifecycle"]["completed"])

    def test_task_metrics_pair_by_task_id_not_label(self):
        events = [
            event("task_started", "2026-05-16T10:00:00+00:00", {"task_id": "task_a", "label": "Checkout"}),
            event("task_started", "2026-05-16T10:00:05+00:00", {"task_id": "task_b", "label": "Checkout"}),
            event(
                "task_completed",
                "2026-05-16T10:00:15+00:00",
                {"task_id": "task_b", "label": "Checkout", "completion_source": "auto_rule"},
            ),
        ]

        with patch.object(main, "load_session_metadata", return_value={"session_id": "sess_test"}), patch.object(
            main, "load_json_lines", side_effect=[events, []]
        ), patch.object(main, "get_gaze_cursor_metrics", return_value={}):
            metrics = asyncio.run(main.get_session_metrics("sess_test"))

        self.assertEqual(metrics["task_started_count"], 2)
        self.assertEqual(metrics["task_completed_count"], 1)
        self.assertEqual(metrics["open_task_count"], 1)
        self.assertEqual(metrics["completed_task_durations"][0]["task_id"], "task_b")
        self.assertEqual(metrics["completed_task_durations"][0]["duration_ms"], 10000)
        self.assertEqual(metrics["completed_task_durations"][0]["completion_source"], "auto_rule")

    def test_timeline_marks_tasks_notes_and_friction(self):
        events = [
            event("task_started", "2026-05-16T10:00:00+00:00", {"task_id": "task_a", "label": "Checkout"}),
            event("note_added", "2026-05-16T10:00:01+00:00", {"note": "Participant hesitated"}),
            event(
                "friction_marker",
                "2026-05-16T10:00:02+00:00",
                {"marker_type": "rage_click", "severity": "high"},
            ),
        ]

        with patch.object(main, "load_session_metadata", return_value={"session_id": "sess_test"}), patch.object(
            main, "session_path", return_value=Path("/tmp/sess_test")
        ), patch.object(main, "load_json_lines", side_effect=[events, [], []]):
            timeline = asyncio.run(main.get_session_timeline("sess_test"))

        kinds = [item["kind"] for item in timeline["timeline"]]
        self.assertEqual(kinds, ["marker", "marker", "friction"])
        self.assertEqual(timeline["counts"]["friction_markers"], 1)
        self.assertEqual(timeline["counts"]["timeline_items"], 3)

    def test_behavioral_and_web_vital_metrics(self):
        events = [
            event("task_started", "2026-05-16T10:00:00+00:00", {"task_id": "task_a"}),
            event("scroll", "2026-05-16T10:00:01+00:00", {
                "scroll_y": 400, "delta_y": 400, "document_height": 1400, "viewport_height": 600,
            }),
            event("scroll", "2026-05-16T10:00:02+00:00", {
                "scroll_y": 200, "delta_y": -200, "document_height": 1400, "viewport_height": 600,
            }),
            event("text_input_metadata", "2026-05-16T10:00:03+00:00"),
            event("input_correction", "2026-05-16T10:00:04+00:00"),
            event("field_interaction", "2026-05-16T10:00:05+00:00", {
                "duration_ms": 2500, "correction_count": 1,
            }),
            event("route_changed", "2026-05-16T10:00:06+00:00", {"to": "https://example.test/a"}),
            event("route_changed", "2026-05-16T10:00:07+00:00", {"to": "https://example.test/a"}),
            event("client_error", "2026-05-16T10:00:08+00:00", {"error_type": "javascript_error"}),
            event("web_vitals_snapshot", "2026-05-16T10:00:09+00:00", {
                "lcp_ms": 2600, "inp_ms": 180, "cls": 0.3,
            }),
            event("page_performance", "2026-05-16T10:00:10+00:00", {"load_event_ms": 1200}),
            event("task_completed", "2026-05-16T10:00:30+00:00", {"task_id": "task_a"}),
        ]

        with patch.object(main, "load_session_metadata", return_value={"session_id": "sess_test"}), patch.object(
            main, "load_json_lines", side_effect=[events, []]
        ), patch.object(main, "get_gaze_cursor_metrics", return_value={}):
            metrics = asyncio.run(main.get_session_metrics("sess_test"))

        self.assertEqual(metrics["task_success_rate"], 1)
        self.assertEqual(metrics["task_efficiency_completed_per_minute"], 2)
        self.assertEqual(metrics["scroll_direction_change_count"], 1)
        self.assertEqual(metrics["max_scroll_depth_ratio"], 0.5)
        self.assertEqual(metrics["route_revisit_count"], 1)
        self.assertEqual(metrics["input_correction_ratio"], 1)
        self.assertEqual(metrics["client_error_count"], 1)
        self.assertEqual(metrics["web_vital_ratings"]["lcp_ms"], "needs_improvement")
        self.assertEqual(metrics["web_vital_ratings"]["inp_ms"], "good")
        self.assertEqual(metrics["web_vital_ratings"]["cls"], "poor")
        self.assertEqual(metrics["avg_page_load_ms"], 1200)
        self.assertIn(metrics["gaze_quality"]["status"], {"green", "yellow", "red"})

    def test_task_outcomes_and_seq_are_aggregated(self):
        events = [
            event("task_started", "2026-05-16T10:00:00+00:00", {"task_id": "success"}),
            event("task_completed", "2026-05-16T10:00:10+00:00", {
                "task_id": "success", "outcome": "success", "seq_rating": 6,
            }),
            event("task_started", "2026-05-16T10:01:00+00:00", {"task_id": "partial"}),
            event("task_completed", "2026-05-16T10:01:20+00:00", {
                "task_id": "partial", "outcome": "success", "assessment_pending": True,
            }),
            event("task_assessed", "2026-05-16T10:01:25+00:00", {
                "task_id": "partial", "outcome": "partial_success", "seq_rating": 3,
            }),
            event("task_started", "2026-05-16T10:02:00+00:00", {"task_id": "failed"}),
            event("task_completed", "2026-05-16T10:02:30+00:00", {
                "task_id": "failed", "outcome": "failure", "seq_rating": 2,
            }),
            event("task_started", "2026-05-16T10:03:00+00:00", {"task_id": "open"}),
        ]

        with patch.object(main, "load_session_metadata", return_value={"session_id": "sess_test"}), patch.object(
            main, "load_json_lines", side_effect=[events, []]
        ), patch.object(main, "get_gaze_cursor_metrics", return_value={}):
            metrics = asyncio.run(main.get_session_metrics("sess_test"))

        self.assertEqual(metrics["paired_task_completion_count"], 3)
        self.assertEqual(metrics["successful_task_count"], 1)
        self.assertEqual(metrics["partial_success_task_count"], 1)
        self.assertEqual(metrics["failed_task_count"], 1)
        self.assertEqual(metrics["task_success_rate"], 0.25)
        self.assertEqual(metrics["weighted_task_effectiveness"], 0.375)
        self.assertEqual(metrics["seq_response_count"], 3)
        self.assertEqual(metrics["seq_response_rate"], 1)
        self.assertEqual(metrics["avg_seq_rating"], 3.67)
        self.assertEqual(metrics["median_seq_rating"], 3)
        self.assertEqual(metrics["open_task_count"], 1)
        partial = next(item for item in metrics["completed_task_durations"] if item["task_id"] == "partial")
        self.assertEqual(partial["outcome"], "partial_success")
        self.assertEqual(partial["seq_rating"], 3)
        self.assertEqual(partial["event_count"], 2)

    def test_sus_is_scored(self):
        events = [
            event(
                "session_questionnaire_response",
                "2026-05-16T10:00:00+00:00",
                {"sus_answers": [5, 1, 5, 1, 5, 1, 5, 1, 5, 1]},
            )
        ]
        with patch.object(main, "load_session_metadata", return_value={"session_id": "sess_test"}), patch.object(
            main, "load_json_lines", side_effect=[events, []]
        ), patch.object(main, "get_gaze_cursor_metrics", return_value={}):
            metrics = asyncio.run(main.get_session_metrics("sess_test"))
        self.assertEqual(metrics["sus_response_count"], 1)
        self.assertEqual(metrics["avg_sus_score"], 100)


if __name__ == "__main__":
    unittest.main()
