from __future__ import annotations

import pytest

from lunar_core.events import VisibilityWindow
from lunar_core.metrics import compute_metrics


def window(start: float, end: float) -> VisibilityWindow:
    return VisibilityWindow(
        start_s=start, end_s=end, start_truncated=False, end_truncated=False
    )


def test_metrics_follow_prd_duration_definitions() -> None:
    sun = [window(0, 2), window(6, 8)]
    earth = [window(1, 3), window(7, 9)]

    metrics = compute_metrics(
        sun, earth, interval_start_s=0, interval_end_s=10
    )

    assert metrics.interval_duration_s == 10
    assert metrics.sunlit_fraction == pytest.approx(0.4)
    assert metrics.dte_clear_fraction == pytest.approx(0.4)
    assert metrics.both_fraction == pytest.approx(0.2)
    assert metrics.joint_outage_fraction == pytest.approx(0.4)
    assert metrics.longest_darkness.duration_s == pytest.approx(4)
    assert metrics.longest_dte_gap.duration_s == pytest.approx(4)
    assert metrics.longest_joint_outage.duration_s == pytest.approx(3)
    assert metrics.sun_window_count == 2
    assert metrics.median_sun_window_s == pytest.approx(2)


def test_outages_touching_interval_edges_are_flagged_as_truncated() -> None:
    metrics = compute_metrics(
        [window(3, 7)], [], interval_start_s=0, interval_end_s=10
    )

    assert metrics.longest_darkness.duration_s == pytest.approx(3)
    # Both equally long darkness intervals touch different requested-interval edges.
    assert metrics.longest_darkness.truncated_start
    assert metrics.longest_darkness.truncated_end
    assert metrics.longest_dte_gap.duration_s == pytest.approx(10)
    assert metrics.longest_dte_gap.truncated_start
    assert metrics.longest_dte_gap.truncated_end
    assert metrics.longest_joint_outage.duration_s == pytest.approx(3)
    assert metrics.longest_joint_outage.truncated_start
    assert metrics.longest_joint_outage.truncated_end


def test_metrics_clip_windows_to_requested_interval_and_merge_overlaps() -> None:
    metrics = compute_metrics(
        [window(-5, 3), window(2, 6), window(8, 15)],
        [window(4, 9)],
        interval_start_s=0,
        interval_end_s=10,
    )

    assert metrics.sunlit_fraction == pytest.approx(0.8)
    assert metrics.sun_window_count == 2
    assert metrics.median_sun_window_s == pytest.approx(4)
    assert metrics.both_fraction == pytest.approx(0.3)


def test_nonpositive_requested_interval_is_rejected() -> None:
    with pytest.raises(ValueError, match="greater than"):
        compute_metrics([], [], interval_start_s=2, interval_end_s=2)
