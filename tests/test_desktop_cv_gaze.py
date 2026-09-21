import unittest
import time

import numpy as np

from desktop_cv_gaze import (
    OpenCvMediaPipeGazeProvider,
    LatestFrameCapture,
    fit_ridge,
)


class DesktopCvGazeTest(unittest.TestCase):
    def make_provider(self):
        return OpenCvMediaPipeGazeProvider(
            emit_point=lambda *args, **kwargs: None,
            emit_status=lambda *args, **kwargs: None,
            emit_lost=lambda *args, **kwargs: None,
            sample_interval_ms=50,
        )

    def test_quality_rejects_multiple_faces(self):
        valid, score, reason = self.make_provider()._assess_sample_quality({}, 2)
        self.assertFalse(valid)
        self.assertEqual(score, 0.0)
        self.assertEqual(reason, "multiple_faces")

    def test_quality_rejects_head_pose_outside_range(self):
        raw = {
            "raw_x": 0.5,
            "raw_y": 0.5,
            "head_yaw_deg": 60.0,
            "head_pitch_deg": 0.0,
            "head_roll_deg": 0.0,
        }
        valid, _, reason = self.make_provider()._assess_sample_quality(raw, 1)
        self.assertFalse(valid)
        self.assertEqual(reason, "head_yaw_out_of_range")

    def test_quality_accepts_stable_centered_sample(self):
        raw = {
            "raw_x": 0.5,
            "raw_y": 0.5,
            "head_yaw_deg": 0.0,
            "head_pitch_deg": 0.0,
            "head_roll_deg": 0.0,
        }
        provider = self.make_provider()
        valid, score, reason = provider._assess_sample_quality(raw, 1)
        self.assertTrue(valid)
        self.assertGreaterEqual(score, 0.95)
        self.assertIsNone(reason)

    def test_ridge_calibration_recovers_linear_mapping(self):
        features = np.array(
            [[0.1, 1.0], [0.3, 1.0], [0.6, 1.0], [0.9, 1.0]],
            dtype=float,
        )
        targets = np.array([0.15, 0.35, 0.65, 0.95], dtype=float)
        weights = np.array(fit_ridge(features, targets, 0.0001))
        rmse = np.sqrt(np.mean((features @ weights - targets) ** 2))
        self.assertLess(rmse, 0.001)

    def test_capture_returns_newest_frame_without_queueing_old_frames(self):
        class FakeCamera:
            value = 0

            def read(self):
                self.value += 1
                time.sleep(0.002)
                return True, self.value

        capture = LatestFrameCapture(FakeCamera())
        capture.start()
        try:
            first_sequence, _ = capture.read_latest(0, timeout=0.1)
            deadline = time.time() + 0.2
            while capture.sequence <= first_sequence + 2 and time.time() < deadline:
                time.sleep(0.005)
            newest_sequence, newest_frame = capture.read_latest(first_sequence, timeout=0.1)
            self.assertGreater(newest_sequence, first_sequence + 1)
            self.assertEqual(newest_frame, newest_sequence)
        finally:
            capture.stop()


if __name__ == "__main__":
    unittest.main()
