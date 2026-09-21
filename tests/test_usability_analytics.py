from datetime import datetime, timedelta, timezone

from usability_analytics import gaze_quality_summary, ivt_metrics, sus_score


def test_sus_scoring_extremes():
    assert sus_score([5, 1, 5, 1, 5, 1, 5, 1, 5, 1]) == 100
    assert sus_score([1, 5, 1, 5, 1, 5, 1, 5, 1, 5]) == 0
    assert sus_score([3] * 9) is None


def test_ivt_uses_normalized_velocity():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    points = [
        (start, 0.1, 0.1),
        (start + timedelta(milliseconds=100), 0.11, 0.1),
        (start + timedelta(milliseconds=200), 0.8, 0.8),
    ]
    result = ivt_metrics(points)
    assert result["algorithm"] == "normalized_ivt_v1"
    assert result["saccade_count"] == 1
    assert result["fixation_segment_count"] == 1


def test_quality_is_red_without_gaze():
    result = gaze_quality_summary([], [{"event_type": "gaze_lost"}], 0, 0)
    assert result["status"] == "red"
    assert "no_valid_gaze" in result["reasons"]

