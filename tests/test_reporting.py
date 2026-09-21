import unittest

from reporting import (
    build_session_report,
    render_session_report_html,
    session_lifecycle,
)


def base_metrics():
    return {
        "rrweb_chunks": 0,
        "gaze_point_count": 0,
        "gaze_quality": {"status": "red", "score": 0.0, "reasons": ["no_gaze"]},
        "task_started_count": 0,
        "task_success_rate": 0,
        "weighted_task_effectiveness": 0,
        "avg_task_duration_ms": 0,
        "seq_response_count": 0,
        "avg_seq_rating": 0,
        "sus_response_count": 0,
        "avg_sus_score": 0,
        "friction_marker_count": 0,
        "high_severity_friction_count": 0,
        "client_error_count": 0,
        "completed_task_durations": [],
        "mouse_click_count": 0,
        "scroll_event_count": 0,
        "route_change_count": 0,
        "unique_route_count": 0,
        "route_revisit_count": 0,
        "max_scroll_depth_ratio": 0,
        "input_correction_count": 0,
        "web_vitals": {"lcp_ms": 0, "inp_ms": 0, "cls": 0},
        "web_vital_ratings": {
            "lcp_ms": "good",
            "inp_ms": "good",
            "cls": "good",
        },
        "gaze_samples_per_second": 0,
        "gaze_lost_count": 0,
        "gaze_fixation_count": 0,
        "gaze_path_length_normalized": 0,
        "gaze_ivt": {"saccade_count": 0},
        "avg_gaze_cursor_distance_screen_diagonal_ratio": 0,
        "top_fixated_elements": [],
        "friction_marker_counts": {},
        "multimodal_focus_evidence": {
            "model_version": "mfem_interpretable_v1",
            "windows": [],
            "probes": [],
        },
        "open_task_count": 0,
    }


class SessionLifecycleTests(unittest.TestCase):
    def test_stop_marker_marks_session_completed(self):
        metadata = {
            "session_id": "desktop-1",
            "started_at": "2026-07-31T10:00:00+00:00",
            "metadata": {"mode": "desktop_only"},
        }
        events = [
            {
                "event_type": "session_stopped",
                "timestamp": "2026-07-31T10:02:05+00:00",
                "payload": {"mode": "desktop_only"},
            }
        ]
        lifecycle = session_lifecycle(metadata, events)
        self.assertTrue(lifecycle["completed"])
        self.assertEqual(lifecycle["mode"], "desktop_only")
        self.assertEqual(lifecycle["duration_seconds"], 125.0)


class ReportModelTests(unittest.TestCase):
    def test_desktop_report_omits_web_section(self):
        metrics = base_metrics()
        metrics.update(
            {
                "gaze_point_count": 20,
                "gaze_samples_per_second": 10,
                "gaze_quality": {
                    "status": "green",
                    "score": 0.9,
                    "reasons": [],
                },
                "mouse_click_count": 4,
            }
        )
        events = [
            {
                "event_type": "session_started",
                "source": "desktop_agent",
                "timestamp": "2026-07-31T10:00:00+00:00",
                "payload": {"mode": "desktop_only"},
            },
            {
                "event_type": "gaze_point",
                "source": "desktop_agent",
                "timestamp": "2026-07-31T10:00:01+00:00",
                "context": {"app_name": "Docker Desktop"},
                "payload": {},
            },
            {
                "event_type": "session_stopped",
                "source": "desktop_agent",
                "timestamp": "2026-07-31T10:01:00+00:00",
                "payload": {"mode": "desktop_only"},
            },
        ]
        report = build_session_report(
            session_id="desktop-1",
            metadata={
                "started_at": "2026-07-31T10:00:00+00:00",
                "metadata": {"mode": "desktop_only"},
            },
            events=events,
            metrics=metrics,
            timeline={"counts": {"events": 3, "timeline_items": 3}},
            recording_available=True,
        )
        self.assertTrue(report["lifecycle"]["completed"])
        self.assertTrue(report["channels"]["desktop"])
        self.assertFalse(report["channels"]["web"])
        self.assertIsNone(report["web"])
        self.assertIsNotNone(report["desktop"])
        html = render_session_report_html(report)
        self.assertIn("Desktop behaviour", html)
        self.assertNotIn("Web behaviour and technical UX", html)
        self.assertIn("<video", html)

    def test_web_desktop_report_contains_tasks_and_web_quality(self):
        metrics = base_metrics()
        metrics.update(
            {
                "rrweb_chunks": 3,
                "gaze_point_count": 30,
                "gaze_samples_per_second": 15,
                "gaze_quality": {
                    "status": "yellow",
                    "score": 0.67,
                    "reasons": ["low_sample_rate"],
                },
                "task_started_count": 1,
                "task_success_rate": 1.0,
                "weighted_task_effectiveness": 1.0,
                "seq_response_count": 1,
                "avg_seq_rating": 6.0,
                "sus_response_count": 1,
                "avg_sus_score": 82.5,
                "completed_task_durations": [
                    {
                        "task_id": "login",
                        "label": "Log in",
                        "outcome": "success",
                        "duration_ms": 12000,
                        "seq_rating": 6,
                        "click_count": 2,
                        "scroll_event_count": 0,
                        "friction_marker_count": 0,
                        "client_error_count": 0,
                    }
                ],
                "route_change_count": 2,
                "unique_route_count": 2,
                "web_vitals": {"lcp_ms": 1800, "inp_ms": 120, "cls": 0.04},
            }
        )
        events = [
            {
                "event_type": "session_started",
                "source": "browser_extension",
                "timestamp": "2026-07-31T11:00:00+00:00",
                "payload": {"mode": "web_desktop"},
            },
            {
                "event_type": "session_stopped",
                "source": "browser_extension",
                "timestamp": "2026-07-31T11:02:00+00:00",
                "payload": {"mode": "web_desktop"},
            },
        ]
        report = build_session_report(
            session_id="web-1",
            metadata={
                "started_at": "2026-07-31T11:00:00+00:00",
                "metadata": {"mode": "web_desktop"},
            },
            events=events,
            metrics=metrics,
            timeline={"counts": {"events": 2, "timeline_items": 8}},
            recording_available=True,
        )
        self.assertTrue(report["channels"]["web"])
        self.assertEqual(report["summary"]["avg_sus_score"], 82.5)
        self.assertEqual(len(report["tasks"]), 1)
        html = render_session_report_html(report)
        self.assertIn("Web behaviour and technical UX", html)
        self.assertIn("Log in", html)
        self.assertIn("82.5/100", html)
        self.assertIn("Save / print PDF", html)


if __name__ == "__main__":
    unittest.main()
