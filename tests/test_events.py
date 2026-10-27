from __future__ import annotations

import math

import pytest

from lunar_core.events import find_visibility_windows


def _solve(function, times, tolerance=0.01):
    margins = [function(time_s) for time_s in times]
    return find_visibility_windows(
        times, margins, function, tolerance_s=tolerance,
        grazing_margin_tolerance=1e-6,
    )


def test_refines_a_simple_crossing_with_brent() -> None:
    solution = _solve(lambda t: t - 5.0, [0.0, 10.0])

    assert len(solution.roots) == 1
    root = solution.roots[0]
    assert root.method == "brentq"
    assert root.crossing
    assert root.time_s == pytest.approx(5.0, abs=0.01)
    assert abs(root.residual) < 1e-9
    assert len(solution.windows) == 1
    assert solution.windows[0].start_s == pytest.approx(5.0, abs=0.01)
    assert solution.windows[0].end_truncated


def test_finds_two_crossings_and_a_short_hidden_visibility_island() -> None:
    # The coarse samples are all negative. A local maximum between them rises above zero.
    def margin(t: float) -> float:
        return 0.1 - (t - 5.5) ** 2
    solution = _solve(margin, [0.0, 5.0, 10.0], tolerance=1e-4)

    assert len([root for root in solution.roots if root.crossing]) == 2
    assert len(solution.windows) == 1
    assert solution.windows[0].start_s == pytest.approx(5.5 - math.sqrt(0.1), abs=2e-4)
    assert solution.windows[0].end_s == pytest.approx(5.5 + math.sqrt(0.1), abs=2e-4)
    assert not solution.windows[0].start_truncated
    assert not solution.windows[0].end_truncated


def test_tangency_is_diagnostic_not_a_visibility_transition() -> None:
    solution = _solve(lambda t: (t - 5.0) ** 2, [0.0, 5.0, 10.0])

    assert len(solution.windows) == 1
    assert solution.windows[0].start_truncated
    assert solution.windows[0].end_truncated
    assert any(not root.crossing for root in solution.roots)


def test_always_positive_window_is_truncated_at_both_requested_edges() -> None:
    solution = _solve(lambda _t: 1.0, [0.0, 10.0])

    assert len(solution.windows) == 1
    assert solution.windows[0].duration_s == 10.0
    assert solution.windows[0].start_truncated
    assert solution.windows[0].end_truncated


def test_invalid_nonfinite_sample_fails_closed() -> None:
    with pytest.raises(ValueError, match="finite"):
        find_visibility_windows([0.0, 1.0], [1.0, float("nan")], lambda t: t)


def test_sample_times_must_be_strictly_increasing() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        find_visibility_windows([0.0, 1.0, 1.0], [-1.0, 1.0, -1.0], lambda t: t)


def test_refined_event_times_converge_when_coarse_step_halves() -> None:
    import math

    def margin(t: float) -> float:
        return math.sin(t)
    coarse_times = [float(t) for t in range(0, 9, 2)]
    fine_times = [float(t) for t in range(0, 9, 1)]
    coarse = find_visibility_windows(
        coarse_times, [margin(t) for t in coarse_times], margin, tolerance_s=1e-8
    )
    fine = find_visibility_windows(
        fine_times, [margin(t) for t in fine_times], margin, tolerance_s=1e-8
    )
    coarse_roots = [root.time_s for root in coarse.roots if root.crossing]
    fine_roots = [root.time_s for root in fine.roots if root.crossing]
    assert len(coarse_roots) == len(fine_roots)
    assert coarse_roots == pytest.approx(fine_roots, abs=1e-7)
