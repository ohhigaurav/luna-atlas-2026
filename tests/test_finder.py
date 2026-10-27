from __future__ import annotations

import pytest

from lunar_core.events import VisibilityWindow
from lunar_core.finder import (
    MissionProfile,
    SiteVisibilityWindows,
    candidate_start_times,
    evaluate_finder_grid,
)


def window(start: float, end: float) -> VisibilityWindow:
    return VisibilityWindow(
        start_s=start, end_s=end, start_truncated=False, end_truncated=False
    )


def test_candidate_start_grid_is_inclusive_and_deterministic() -> None:
    assert candidate_start_times(0, 10, 3) == (0, 3, 6, 9)
    assert candidate_start_times(0, 12, 3) == (0, 3, 6, 9, 12)


def test_finder_reports_first_failed_constraint_and_violation_margin() -> None:
    site = SiteVisibilityWindows(
        site_id="synthetic-fixture-a",
        sun_windows=(window(0, 4), window(6, 100)),
        earth_windows=(window(0, 100),),
    )
    profile = MissionProfile(
        mission_duration_s=10,
        max_darkness_s=1.5,
        max_dte_gap_s=2,
        max_joint_outage_s=1,
        min_sunlit_fraction=0.5,
    )

    cells = evaluate_finder_grid([site], [0, 5], profile)

    assert len(cells) == 2
    assert not cells[0].feasible
    assert cells[0].first_failed_constraint == "max_darkness"
    assert cells[0].failures[0].actual == pytest.approx(2)
    assert cells[0].failures[0].limit == pytest.approx(1.5)
    assert cells[0].failures[0].violation == pytest.approx(0.5)
    assert cells[1].feasible
    assert cells[1].first_failed_constraint is None


def test_finder_uses_outage_already_in_progress_at_landing() -> None:
    site = SiteVisibilityWindows(
        site_id="synthetic-fixture-a",
        sun_windows=(window(5, 100),),
        earth_windows=(window(0, 100),),
    )
    profile = MissionProfile(
        mission_duration_s=10,
        max_darkness_s=4,
        max_dte_gap_s=None,
        max_joint_outage_s=None,
        min_sunlit_fraction=None,
    )

    cell = evaluate_finder_grid([site], [0], profile)[0]
    # At landing, the Sun is not visible until t=5. The outage counts from t=0.
    assert cell.metrics.longest_darkness.duration_s == pytest.approx(5)
    assert not cell.feasible
    assert cell.first_failed_constraint == "max_darkness"


def test_finder_rejects_duplicate_site_ids_and_unsorted_dates() -> None:
    site = SiteVisibilityWindows("same", (), ())
    profile = MissionProfile(1, None, None, None, None)
    with pytest.raises(ValueError, match="unique"):
        evaluate_finder_grid([site, site], [0], profile)
    with pytest.raises(ValueError, match="strictly increasing"):
        evaluate_finder_grid([site], [2, 1], profile)
