import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import worker


def event(event_type, timestamp, payload, source="browser_extension"):
    return {
        "session_id": "sess_test",
        "source": source,
        "event_type": event_type,
        "timestamp": timestamp,
        "context": {"url": "https://example.test"},
        "payload": payload,
    }


class WorkerDerivationsTest(unittest.TestCase):
    def setUp(self):
        worker.latest_by_session.clear()
        worker.fixation_by_session.clear()

    def test_desktop_raw_events_are_correlated_centrally(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            worker, "insert_gaze_cursor_sample"
        ) as insert_sample:
            path = Path(directory)
            worker.maybe_store_gaze_cursor_distance(
                "sess_test",
                path,
                event(
                    "gaze_point",
                    "2026-01-01T00:00:00Z",
                    {"screen_x": 100, "screen_y": 100},
                    source="desktop_agent",
                ),
            )
            worker.maybe_store_gaze_cursor_distance(
                "sess_test",
                path,
                event(
                    "cursor_position",
                    "2026-01-01T00:00:00.050Z",
                    {"screen_x": 103, "screen_y": 104},
                    source="desktop_agent",
                ),
            )

            rows = [
                json.loads(line)
                for line in (path / worker.EVENTS_FILE).read_text().splitlines()
            ]
            self.assertEqual(rows[0]["event_type"], "gaze_cursor_distance")
            self.assertEqual(rows[0]["payload"]["distance_px"], 5.0)
            insert_sample.assert_called_once()

    def test_dom_dwell_is_emitted_as_one_fixation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            for timestamp in (
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00.200Z",
                "2026-01-01T00:00:00.400Z",
                "2026-01-01T00:00:00.600Z",
            ):
                worker.maybe_emit_fixation(
                    "sess_test",
                    path,
                    event(
                        "gaze_dom_context",
                        timestamp,
                        {"element": {"tag_name": "button", "id": "buy", "path": "button#buy"}},
                    ),
                )
            worker.finalize_fixation("sess_test", path)

            rows = [
                json.loads(line)
                for line in (path / worker.EVENTS_FILE).read_text().splitlines()
            ]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["payload"]["duration_ms"], 600.0)
            self.assertEqual(rows[0]["payload"]["fixation_algorithm"], "dom_dwell_v1")


if __name__ == "__main__":
    unittest.main()
