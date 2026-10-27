"""SPK coverage preflight for actual requested ET ranges.

Kernel file hashes prove byte identity, not that a target has ephemeris coverage for the requested
interval. This module unions segment coverage from all registered SPK files and rejects holes for
Moon, Sun or Earth. LT+S requires target ephemeris before the receive epoch, so a conservative
pre-roll is required at the start of the requested interval.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable

from lunar_core.spice_runtime import SPICE_LOCK


class SPKCoverageError(RuntimeError):
    """The loaded SPK set cannot cover the requested ET interval continuously."""


LT_PRE_ROLL_S = 1200.0
REQUIRED_OBJECTS = {301: "MOON (301)", 10: "SUN (10)", 399: "EARTH (399)"}


def merge_intervals(intervals: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    """Return sorted, unioned finite closed intervals."""
    clean: list[tuple[float, float]] = []
    for start, end in intervals:
        if not math.isfinite(start) or not math.isfinite(end) or end < start:
            raise ValueError(f"invalid SPK coverage interval: {(start, end)}")
        clean.append((float(start), float(end)))
    clean.sort()
    merged: list[tuple[float, float]] = []
    for start, end in clean:
        if merged and start <= merged[-1][1] + 1e-6:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def interval_covers(
    intervals: Iterable[tuple[float, float]], start_et: float, end_et: float, *, tolerance_s: float = 1e-3
) -> bool:
    """Whether the union of intervals covers the complete requested interval without gaps."""
    if not all(math.isfinite(value) for value in (start_et, end_et, tolerance_s)):
        raise ValueError("coverage bounds and tolerance must be finite")
    if end_et < start_et or tolerance_s < 0:
        raise ValueError("invalid requested coverage bounds/tolerance")
    for left, right in merge_intervals(intervals):
        if left <= start_et + tolerance_s and right >= end_et - tolerance_s:
            return True
    # A continuous requested interval may span adjacent windows; merge already folds touching
    # windows together but deliberately preserves any positive gap.
    return False


def read_spk_coverage(
    spice: Any,
    spk_paths: Iterable[str | Path],
    *,
    cell_factory: Any | None = None,
) -> dict[int, list[tuple[float, float]]]:
    """Read the union of SPK segment coverage across all paths using SpiceyPy's CSPICE wrapper.

    A file that does not contain a particular object may trigger a CSPICE exception. Such a file is
    ignored for that object; if no other SPK provides the object, the final preflight rejects it.
    All registered SPKs were already hash-checked and successfully furnished before this function.
    """
    if cell_factory is None:
        try:
            from spiceypy.utils.support_types import SPICEDOUBLE_CELL
        except ImportError as exc:  # pragma: no cover - dependency is mandatory for real runs
            raise SPKCoverageError("SpiceyPy coverage-cell support is unavailable") from exc
        cell_factory = SPICEDOUBLE_CELL

    result: dict[int, list[tuple[float, float]]] = {target_id: [] for target_id in REQUIRED_OBJECTS}
    candidates = [Path(path) for path in spk_paths if Path(path).suffix.lower() in {".bsp", ".spk"}]
    if not candidates:
        raise SPKCoverageError("the kernel manifest contains no SPK/BSP files")
    with SPICE_LOCK:
        for target_id in REQUIRED_OBJECTS:
            for path in candidates:
                cover = cell_factory(20000)
                try:
                    spice.spkcov(str(path), target_id, cover)
                    for index in range(int(spice.wncard(cover))):
                        left, right = spice.wnfetd(cover, index)
                        result[target_id].append((float(left), float(right)))
                except Exception:
                    # The SPK may simply not contain this object ID. Reset CSPICE's error state before
                    # trying another SPK; the final continuous-coverage assertion is the fail-closed gate.
                    try:
                        spice.reset()
                    except Exception:
                        pass
    return {target_id: merge_intervals(intervals) for target_id, intervals in result.items()}


def assert_required_spk_coverage(
    spice: Any,
    loaded_kernels: Iterable[dict[str, Any]],
    start_et: float,
    end_et: float,
    *,
    light_time_preroll_s: float = LT_PRE_ROLL_S,
    cell_factory: Any | None = None,
) -> dict[str, Any]:
    """Reject an analysis unless SPK coverage continuously covers Moon/Sun/Earth over the run.

    The required coverage starts ``light_time_preroll_s`` before the requested ET start to support
    the configured LT+S apparent-position convention for the Sun. The bound is deliberately
    conservative and should be revisited if the aberration policy or target set changes.
    """
    if not all(math.isfinite(v) for v in (start_et, end_et, light_time_preroll_s)):
        raise ValueError("SPK coverage bounds must be finite")
    if end_et <= start_et or light_time_preroll_s < 0:
        raise ValueError("invalid SPK coverage interval or light-time pre-roll")
    paths = [entry["path"] for entry in loaded_kernels if entry.get("path")]
    all_coverage = read_spk_coverage(spice, paths, cell_factory=cell_factory)
    required_start = start_et - light_time_preroll_s
    report: dict[str, Any] = {
        "requested_et_s": [start_et, end_et],
        "required_et_s_including_lt_preroll": [required_start, end_et],
        "light_time_preroll_s": light_time_preroll_s,
        "objects": {},
    }
    for object_id, label in REQUIRED_OBJECTS.items():
        intervals = all_coverage[object_id]
        covered = interval_covers(intervals, required_start, end_et)
        report["objects"][str(object_id)] = {
            "name": label,
            "coverage_intervals_et_s": [[left, right] for left, right in intervals],
            "covers_requested_interval": covered,
        }
        if not covered:
            raise SPKCoverageError(
                f"SPK coverage for {label} does not continuously cover ET [{required_start:.3f}, "
                f"{end_et:.3f}] including {light_time_preroll_s:g} s light-time pre-roll; "
                f"available intervals: {intervals}"
            )
    return report
