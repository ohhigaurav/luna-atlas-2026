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


# --- Certified (rate-bounded) discovery -------------------------------------------------------

def _gaussian_island(center: float = 50_000.0, sigma: float = 300.0):
    # A slow downward trend makes the coarse samples strictly monotone, so no sampled local
    # extremum exists for the heuristic to inspect.
    trend = 1e-7
    def margin(t: float) -> float:
        return -1.0 - trend * (t - center) + 2.0 * math.exp(-(((t - center) / sigma) ** 2))
    # max |g'| <= trend + 2 * sqrt(2/e) / sigma
    bound = (trend + 2.0 * math.sqrt(2.0 / math.e) / sigma) * 1.01
    return margin, bound, center, sigma


def test_certified_mode_finds_window_hidden_between_monotone_samples() -> None:
    margin, bound, center, sigma = _gaussian_island()
    times = [float(t) for t in range(0, 86_401, 21_600)]  # 6 h samples, ~500 s window
    values = [margin(t) for t in times]
    heuristic = find_visibility_windows(times, values, margin, tolerance_s=1e-3)
    assert heuristic.windows == ()  # documented failure of plain sampling
    assert not heuristic.certified

    certified = find_visibility_windows(
        times, values, margin, tolerance_s=1e-3, rate_bound=lambda _a, _b: bound,
    )
    assert certified.certified
    assert len(certified.windows) == 1
    window = certified.windows[0]
    assert abs(margin(window.start_s)) < 1e-6 and abs(margin(window.end_s)) < 1e-6
    assert window.start_s < center < window.end_s
    assert window.duration_s == pytest.approx(2 * sigma * math.sqrt(math.log(2.0)), rel=1e-3)
    assert certified.possible_grazing_intervals == ()
    assert certified.subdivision_evaluations > 0


def test_certified_mode_reports_tangency_as_possible_grazing() -> None:
    def margin(t: float) -> float:
        return -(((t - 40_000.0) / 1_000.0) ** 2)
    bound = 2.0 * 86_400.0 / 1_000.0 ** 2
    times = [float(t) for t in range(0, 86_401, 3_600)]
    solution = find_visibility_windows(
        times, [margin(t) for t in times], margin, tolerance_s=1e-2,
        rate_bound=lambda _a, _b: bound,
    )
    assert solution.windows == ()
    assert any(a <= 40_000.0 <= b for a, b in solution.possible_grazing_intervals)
    assert all(b - a <= 1e-2 for a, b in solution.possible_grazing_intervals)


def test_certified_mode_near_miss_is_cleanly_excluded() -> None:
    def margin(t: float) -> float:
        return -0.5 - (((t - 40_000.0) / 1_000.0) ** 2)
    bound = 2.0 * 86_400.0 / 1_000.0 ** 2
    times = [float(t) for t in range(0, 86_401, 3_600)]
    solution = find_visibility_windows(
        times, [margin(t) for t in times], margin, tolerance_s=1e-2,
        rate_bound=lambda _a, _b: bound,
    )
    assert solution.windows == ()
    assert solution.possible_grazing_intervals == ()


def test_certified_crossings_are_not_reported_as_grazes() -> None:
    period = 86_400.0
    def margin(t: float) -> float:
        return math.sin(2 * math.pi * t / period) - 0.5
    bound = 2 * math.pi / period * 1.01
    times = [float(t) for t in range(0, 3 * 86_400 + 1, 3_600)]
    solution = find_visibility_windows(
        times, [margin(t) for t in times], margin, tolerance_s=1e-3,
        rate_bound=lambda _a, _b: bound,
    )
    assert len(solution.windows) == 3
    for k, window in enumerate(solution.windows):
        assert window.start_s == pytest.approx(k * period + period / 12, abs=1e-3)
        assert window.end_s == pytest.approx(k * period + 5 * period / 12, abs=1e-3)
    assert solution.possible_grazing_intervals == ()


def test_certified_budget_is_enforced() -> None:
    from lunar_core.events import EventBudgetExceeded

    def margin(t: float) -> float:
        return -abs(t - 500.0) * 1e-9
    times = [float(t) for t in range(0, 1001, 100)]
    with pytest.raises(EventBudgetExceeded):
        find_visibility_windows(
            times, [margin(t) for t in times], margin, tolerance_s=1e-9,
            rate_bound=lambda _a, _b: 1e3, max_subdivision_evaluations=200,
        )


def test_invalid_rate_bound_fails_closed() -> None:
    times = [0.0, 10.0]
    with pytest.raises(ValueError, match="rate_bound"):
        find_visibility_windows(
            times, [1.0, 1.0], lambda _t: 1.0, rate_bound=lambda _a, _b: float("nan"),
        )
