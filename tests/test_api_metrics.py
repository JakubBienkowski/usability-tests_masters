import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
