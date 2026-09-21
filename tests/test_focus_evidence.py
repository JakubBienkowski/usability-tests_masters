import unittest

from focus_evidence import calculate_focus_evidence


def event(event_type, second, payload=None):
    return {
        "event_type": event_type,
        "timestamp": f"2026-07-28T10:00:{second:02d}+00:00",
        "source": "desktop_agent",
        "payload": payload or {},
    }


class FocusEvidenceTest(unittest.TestCase):
    def test_engaged_window_exposes_interpretable_components(self):
        events = []
        for second in range(10):
            for sample in range(4):
                events.append(
                    {
                        **event(
                            "gaze_point",
                            second,
                            {
                                "normalized_x": 0.45 + sample * 0.01,
                                "normalized_y": 0.5,
                                "confidence": 0.8,
                                "head_yaw_deg": 2.0,
                                "head_pitch_deg": 1.0,
                                "eye_openness": 0.3,
                            },
                        ),
                        "timestamp": f"2026-07-28T10:00:{second:02d}.{sample}00+00:00",
                    }
                )
            events.append(event("mouse_move", second))
        result = calculate_focus_evidence(events)
        self.assertEqual(result["model_version"], "mfem_interpretable_v1")
        self.assertEqual(result["status"], "likely_engaged")
        self.assertGreater(result["quality"], 0.7)
        self.assertIn("head_deviation_deg", result["windows"][0]["evidence"])

    def test_probe_is_preserved_as_ground_truth_label(self):
        events = [
            event("session_started", 0),
            event(
                "attention_probe_response",
                5,
                {"rating": 2, "mind_wandering": True},
            ),
        ]
        result = calculate_focus_evidence(events)
        self.assertEqual(result["probes"][0]["rating"], 2)
        self.assertTrue(result["probes"][0]["mind_wandering"])


if __name__ == "__main__":
    unittest.main()
