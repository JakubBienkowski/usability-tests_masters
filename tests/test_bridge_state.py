import unittest

from desktop_bridge import GazeBridgeState


class GazeBridgeStateTest(unittest.TestCase):
    def test_stream_returns_every_event_after_acknowledged_sequence(self):
        state = GazeBridgeState("sess_a")
        state.update("gaze_point", {"screen_x": 10, "screen_y": 20}, "2026-01-01T00:00:00Z")
        state.update("gaze_point", {"screen_x": 11, "screen_y": 21}, "2026-01-01T00:00:00.050Z")
        state.update("gaze_lost", {"reason": "blink"}, "2026-01-01T00:00:00.100Z")

        batch = state.events_after(1)

        self.assertFalse(batch["gap"])
        self.assertEqual([event["bridge_sequence"] for event in batch["events"]], [2, 3])
        self.assertEqual(batch["latest_sequence"], 3)

    def test_join_updates_session_and_notifies_agent(self):
        state = GazeBridgeState("idle")
        state.update("gaze_point", {"screen_x": 1, "screen_y": 2}, "2026-01-01T00:00:00Z")
        calls = []
        state.session_change = lambda session_id, metadata: calls.append((session_id, metadata))

        snapshot = state.join_session("sess_shared", {"run_id": "run_1"})

        self.assertEqual(snapshot["session_id"], "sess_shared")
        self.assertEqual(snapshot["sequence"], 0)
        self.assertIsNone(snapshot["last_event"])
        self.assertEqual(calls, [("sess_shared", {"run_id": "run_1"})])


if __name__ == "__main__":
    unittest.main()
