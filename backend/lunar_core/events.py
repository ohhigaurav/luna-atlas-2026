"""Visibility event refinement over a scalar geometric margin.

This module deliberately knows nothing about SPICE, terrain rasters, or UTC conversion. The
caller supplies a continuous margin function in one declared time coordinate. Positive margin
means visible. All times are seconds in that same coordinate; they must not be labelled UTC
unless the caller actually supplied UTC elapsed seconds.

Two discovery modes
-------------------
*Certified* (``rate_bound`` supplied). The caller provides ``rate_bound(a, b)`` returning
``L >= max |dg/dt|`` on ``[a, b]``. For samples ``g(a), g(b)`` of the same sign, any function
with that bound satisfies::

    min g >= (g(a) + g(b) - L (b - a)) / 2      max g <= (g(a) + g(b) + L (b - a)) / 2

so if the relevant bound keeps its sign, no transition can hide between the samples. Otherwise
the interval is bisected until either the bound clears or the interval is no longer than
``tolerance_s``. Result: **no visible or non-visible interval longer than ``tolerance_s`` is
missed, provided the supplied bound is valid.** Leftover sub-tolerance intervals are reported in
``possible_grazing_intervals`` (a graze or a sub-tolerance event), never silently dropped.

*Heuristic* (no bound). Sign-change brackets plus local-extremum minimisation around sampled
extrema. Useful, but a short window between two monotone samples can be missed;
``EventSolution.certified`` is then ``False`` and callers must say so.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Callable, Literal, Sequence

from scipy.optimize import brentq, minimize_scalar

RootMethod = Literal["brentq", "sample_zero", "grazing_minimization"]


@dataclass(frozen=True, slots=True)
class EventRoot:
    """A visibility-margin zero, with enough evidence to audit its refinement."""

    time_s: float
    residual: float
    method: RootMethod
    crossing: bool
    visible_before: bool | None
    visible_after: bool | None


@dataclass(frozen=True, slots=True)
class VisibilityWindow:
    """A continuous interval for which a margin is positive.

    ``*_truncated`` means the requested analysis interval cut the window at that edge. Such a
    duration is a lower bound on the full visibility window and must be displayed accordingly.
    """

    start_s: float
    end_s: float
    start_truncated: bool
    end_truncated: bool
    start_residual: float | None = None
    end_residual: float | None = None
    start_method: str = "interval_boundary"
    end_method: str = "interval_boundary"

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass(frozen=True, slots=True)
class EventSolution:
    interval_start_s: float
    interval_end_s: float
    windows: tuple[VisibilityWindow, ...]
    roots: tuple[EventRoot, ...]
    certified: bool = False
    possible_grazing_intervals: tuple[tuple[float, float], ...] = ()
    subdivision_evaluations: int = 0


class EventBudgetExceeded(ValueError):
    """Certified subdivision needed more margin evaluations than the configured budget."""


RateBound = Callable[[float, float], float]


def _certify_samples(
    times: list[float],
    values: list[float],
    evaluate: Callable[[float], float],
    rate_bound: RateBound,
    *,
    tolerance_s: float,
    zero_margin_tolerance: float,
    max_evaluations: int,
) -> tuple[list[float], list[float], list[tuple[float, float]], int]:
    """Bisect same-sign sample pairs until the rate bound excludes a hidden transition."""
    out_t: list[float] = [times[0]]
    out_v: list[float] = [values[0]]
    suspect: list[tuple[float, float]] = []
    evaluations = 0
    for index in range(len(times) - 1):
        stack: list[tuple[float, float, float, float]] = [
            (times[index], values[index], times[index + 1], values[index + 1])
        ]
        # Depth-first, right half pushed first, so accepted points are emitted in time order.
        while stack:
            a, ga, b, gb = stack.pop()
            same_sign = (
                (ga > zero_margin_tolerance and gb > zero_margin_tolerance)
                or (ga < -zero_margin_tolerance and gb < -zero_margin_tolerance)
            )
            if same_sign:
                bound = float(rate_bound(a, b))
                if not isfinite(bound) or bound < 0:
                    raise ValueError(f"rate_bound returned an invalid value {bound!r} on [{a}, {b}]")
                half_width = 0.5 * bound * (b - a)
                mean = 0.5 * (ga + gb)
                safe = (mean - half_width > 0.0) if ga > 0 else (mean + half_width < 0.0)
                if not safe:
                    if b - a > tolerance_s:
                        mid = 0.5 * (a + b)
                        evaluations += 1
                        if evaluations > max_evaluations:
                            raise EventBudgetExceeded(
                                f"certified event search exceeded {max_evaluations} margin evaluations; "
                                "increase event_tolerance_s or reduce the interval"
                            )
                        gm = evaluate(mid)
                        stack.append((mid, gm, b, gb))
                        stack.append((a, ga, mid, gm))
                        continue
                    suspect.append((a, b))
            out_t.append(b)
            out_v.append(gb)
    return out_t, out_v, suspect, evaluations


def find_visibility_windows(
    sample_times_s: Sequence[float],
    sampled_margins: Sequence[float],
    margin_function: Callable[[float], float],
    *,
    tolerance_s: float = 1.0,
    zero_margin_tolerance: float = 1e-12,
    grazing_margin_tolerance: float = 1e-8,
    rate_bound: RateBound | None = None,
    max_subdivision_evaluations: int = 200_000,
) -> EventSolution:
    """Find intervals where ``margin_function(t) > 0`` and refine transition times.

    Sign-changing brackets are refined by SciPy's Brent solver. Interior sampled extrema are
    additionally minimised/maximised so a short visibility island or near-tangent event can be
    detected even when the coarse samples have the same sign. Tangencies are recorded in
    ``roots`` with ``crossing=False`` and do not split a visibility window.

    Args:
        sample_times_s: Strictly increasing sample times, including both requested endpoints.
        sampled_margins: Margin values at exactly those times.
        margin_function: Continuous scalar margin in the same unit as ``sampled_margins``.
        tolerance_s: Absolute root-time tolerance in seconds (the PRD proposes 1 s).
        zero_margin_tolerance: Numerical tolerance for treating a sampled value as zero.
        grazing_margin_tolerance: Margin magnitude within which an optimised local extremum is
            reported as a possible grazing event. This is a numerical diagnostic, not physical
            uncertainty.
        rate_bound: Optional ``L(a, b) >= max |dg/dt|`` on ``[a, b]``. Enables certified
            discovery (see module docstring); the extremum heuristic is then not needed.
        max_subdivision_evaluations: Budget for extra margin evaluations in certified mode.

    Raises:
        ValueError: If samples, tolerances, or evaluated margins are invalid.
        EventBudgetExceeded: If certified subdivision exceeds its evaluation budget.
    """
    times = tuple(float(t) for t in sample_times_s)
    values = tuple(float(v) for v in sampled_margins)
    if len(times) < 2 or len(times) != len(values):
        raise ValueError("at least two times and an equal number of margins are required")
    if any(not isfinite(t) for t in times):
        raise ValueError("sample times must be finite")
    if any(times[i] >= times[i + 1] for i in range(len(times) - 1)):
        raise ValueError("sample times must be strictly increasing")
    if any(not isfinite(v) for v in values):
        raise ValueError("sampled margins must be finite; missing geometry must fail closed")
    if not isfinite(tolerance_s) or tolerance_s <= 0:
        raise ValueError("tolerance_s must be finite and positive")
    if not isfinite(zero_margin_tolerance) or zero_margin_tolerance < 0:
        raise ValueError("zero_margin_tolerance must be finite and non-negative")
    if not isfinite(grazing_margin_tolerance) or grazing_margin_tolerance < 0:
        raise ValueError("grazing_margin_tolerance must be finite and non-negative")

    def evaluate(time_s: float) -> float:
        value = float(margin_function(time_s))
        if not isfinite(value):
            raise ValueError(f"margin function returned a non-finite value at t={time_s}")
        return value

    def sign(value: float) -> int:
        if value > zero_margin_tolerance:
            return 1
        if value < -zero_margin_tolerance:
            return -1
        return 0

    certified = rate_bound is not None
    suspect_intervals: list[tuple[float, float]] = []
    subdivision_evaluations = 0
    if rate_bound is not None:
        if max_subdivision_evaluations < 0:
            raise ValueError("max_subdivision_evaluations must be non-negative")
        refined_t, refined_v, suspect_intervals, subdivision_evaluations = _certify_samples(
            list(times), list(values), evaluate, rate_bound,
            tolerance_s=tolerance_s, zero_margin_tolerance=zero_margin_tolerance,
            max_evaluations=max_subdivision_evaluations,
        )
        times, values = tuple(refined_t), tuple(refined_v)

    roots: list[EventRoot] = []
    # Ordinary sign-change brackets.
    for index in range(len(times) - 1):
        left_sign = sign(values[index])
        right_sign = sign(values[index + 1])
        if left_sign * right_sign == -1:
            root_time = brentq(
                evaluate,
                times[index],
                times[index + 1],
                xtol=tolerance_s,
                rtol=4.0 * 2.220446049250313e-16,
            )
            residual = evaluate(root_time)
            roots.append(EventRoot(
                time_s=float(root_time),
                residual=residual,
                method="brentq",
                crossing=True,
                visible_before=left_sign > 0,
                visible_after=right_sign > 0,
            ))

    # Sampled exact/near-zero values. Only an interior zero with opposite-sided signs is a
    # crossing; same-sided signs indicate a possible touch/tangency rather than an outage split.
    for index, value in enumerate(values):
        if sign(value) != 0:
            continue
        left_index = next((j for j in range(index - 1, -1, -1) if sign(values[j]) != 0), None)
        right_index = next(
            (j for j in range(index + 1, len(values)) if sign(values[j]) != 0), None
        )
        if left_index is None or right_index is None:
            continue
        left_sign, right_sign = sign(values[left_index]), sign(values[right_index])
        crossing = left_sign != right_sign
        roots.append(EventRoot(
            time_s=times[index],
            residual=evaluate(times[index]),
            method="sample_zero",
            crossing=crossing,
            visible_before=left_sign > 0,
            visible_after=right_sign > 0,
        ))

    # Grazing check: a local minimum while visible, or a local maximum while not visible, may
    # hide a short interval between coarse samples. Optimise only these candidate extrema.
    # In certified mode the rate bound has already excluded hidden transitions longer than the
    # tolerance, so this heuristic pass is skipped.
    for index in range(1, len(times) - 1 if not certified else 1):
        left, centre, right = values[index - 1], values[index], values[index + 1]
        left_sign, centre_sign, right_sign = sign(left), sign(centre), sign(right)
        if left_sign == right_sign == 1 and centre <= left and centre <= right:
            polarity = 1.0  # minimise a positive local minimum
            expected_initial_sign = 1
        elif left_sign == right_sign == -1 and centre >= left and centre >= right:
            polarity = -1.0  # maximise a negative local maximum by minimising its negative
            expected_initial_sign = -1
        else:
            continue

        optimum = minimize_scalar(
            lambda t: polarity * evaluate(float(t)),
            bounds=(times[index - 1], times[index + 1]),
            method="bounded",
            options={"xatol": tolerance_s},
        )
        if not optimum.success:
            continue
        optimum_time = float(optimum.x)
        optimum_value = evaluate(optimum_time)
        if expected_initial_sign * optimum_value < -zero_margin_tolerance:
            left_time, right_time = times[index - 1], times[index + 1]
            left_root = brentq(
                evaluate, left_time, optimum_time,
                xtol=tolerance_s, rtol=4.0 * 2.220446049250313e-16,
            )
            right_root = brentq(
                evaluate, optimum_time, right_time,
                xtol=tolerance_s, rtol=4.0 * 2.220446049250313e-16,
            )
            if expected_initial_sign > 0:
                transitions = ((left_root, True, False), (right_root, False, True))
            else:
                transitions = ((left_root, False, True), (right_root, True, False))
            for root_time, before, after in transitions:
                roots.append(EventRoot(
                    time_s=float(root_time),
                    residual=evaluate(float(root_time)),
                    method="brentq",
                    crossing=True,
                    visible_before=before,
                    visible_after=after,
                ))
        elif abs(optimum_value) <= grazing_margin_tolerance:
            roots.append(EventRoot(
                time_s=optimum_time,
                residual=optimum_value,
                method="grazing_minimization",
                crossing=False,
                visible_before=expected_initial_sign > 0,
                visible_after=expected_initial_sign > 0,
            ))

    # Deduplicate roots from the sampled-zero and grazing passes. Preserve a true transition if
    # a diagnostic root is coincident with it.
    roots.sort(key=lambda item: item.time_s)
    deduplicated: list[EventRoot] = []
    for root in roots:
        # Deduplicate only numerically coincident roots. The root-time tolerance is not a
        # licence to collapse two real crossings that delimit a short visibility window.
        duplicate_epsilon_s = 1e-7
        if deduplicated and abs(root.time_s - deduplicated[-1].time_s) <= duplicate_epsilon_s:
            previous = deduplicated[-1]
            if root.crossing and not previous.crossing:
                deduplicated[-1] = root
            elif root.crossing == previous.crossing and abs(root.residual) < abs(previous.residual):
                deduplicated[-1] = root
            continue
        deduplicated.append(root)
    roots = deduplicated

    start_s, end_s = times[0], times[-1]
    transitions = [
        root for root in roots
        if root.crossing and start_s < root.time_s < end_s
    ]
    boundaries: list[tuple[float, EventRoot | None]] = [(start_s, None)]
    boundaries.extend((root.time_s, root) for root in transitions)
    boundaries.append((end_s, None))

    windows: list[VisibilityWindow] = []
    for boundary_index in range(len(boundaries) - 1):
        left_time, left_root = boundaries[boundary_index]
        right_time, right_root = boundaries[boundary_index + 1]
        if right_time <= left_time:
            continue
        segment_duration = right_time - left_time
        probes = (
            left_time + segment_duration / 2.0,
            left_time + segment_duration / 4.0,
            left_time + 3.0 * segment_duration / 4.0,
        )
        # A grazing root may land exactly at the midpoint despite not changing visibility.
        # Probe away from such a root rather than treating that single point as the interval sign.
        probe_value = next(
            (evaluate(probe) for probe in probes if abs(evaluate(probe)) > zero_margin_tolerance),
            0.0,
        )
        if probe_value <= 0.0:
            continue
        windows.append(VisibilityWindow(
            start_s=left_time,
            end_s=right_time,
            start_truncated=left_root is None,
            end_truncated=right_root is None,
            start_residual=None if left_root is None else left_root.residual,
            end_residual=None if right_root is None else right_root.residual,
            start_method="interval_boundary" if left_root is None else left_root.method,
            end_method="interval_boundary" if right_root is None else right_root.method,
        ))

    # A suspect interval that shares an endpoint with a sign-change bracket is root ambiguity
    # next to a refined crossing, not a separate graze.
    bracket_ends = {
        t for i in range(len(times) - 1)
        if sign(values[i]) * sign(values[i + 1]) == -1
        for t in (times[i], times[i + 1])
    }
    grazing = tuple(
        (a, b) for a, b in suspect_intervals if a not in bracket_ends and b not in bracket_ends
    )

    return EventSolution(
        interval_start_s=start_s,
        interval_end_s=end_s,
        windows=tuple(windows),
        roots=tuple(roots),
        certified=certified,
        possible_grazing_intervals=grazing,
        subdivision_evaluations=subdivision_evaluations,
    )
