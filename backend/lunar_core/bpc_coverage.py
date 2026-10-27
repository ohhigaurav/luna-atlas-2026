"""Binary-PCK coverage and frame-chain preflight for the Moon orientation model.

A binary PCK's coverage is indexed by the PCK frame class actually stored in the file. For the
DE421-associated lunar kernels, the BPC supplies ``MOON_PA_DE421`` (frame ID 31006); the mission
geometry uses the derived ``MOON_ME`` frame. Therefore we check coverage on the manifest-declared
PCK frame class, then verify SPICE can transform that frame into the requested geometry frame at
both endpoints. We deliberately do not call ``pckcov`` with ``MOON_ME`` merely because that is the
frame used by ``azlcpo``.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from lunar_core.spk_coverage import interval_covers, merge_intervals
from lunar_core.spice_runtime import SPICE_LOCK


class BPCoverageError(RuntimeError):
    """The loaded binary-PCK files cannot support the requested frame and ET interval."""


def _as_bpc_entries(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for entry in entries:
        path_value = entry.get("path")
        if not path_value:
            continue
        path = Path(str(path_value))
        kind = str(entry.get("kernel_type", "")).upper()
        if kind == "BPC" or path.suffix.lower() in {".bpc", ".bc"}:
            candidates.append({**entry, "path": path})
    if not candidates:
        raise BPCoverageError("the loaded kernel manifest contains no binary-PCK/BPC files")
    missing = [str(entry["path"]) for entry in candidates if not str(entry.get("coverage_frame", "")).strip()]
    if missing:
        raise BPCoverageError(
            "every BPC asset must declare its exact coverage_frame in the kernel manifest; "
            f"missing for: {', '.join(missing)}"
        )
    frame_names = {str(entry["coverage_frame"]).strip() for entry in candidates}
    if len(frame_names) != 1:
        raise BPCoverageError(
            "the configured BPC set declares multiple coverage_frame values; do not merge "
            f"different frame-class coverage without an explicit frame contract: {sorted(frame_names)}"
        )
    return candidates


def read_bpc_coverage(
    spice: Any,
    bpc_entries: Iterable[dict[str, Any]],
    *,
    coverage_frame: str,
    cell_factory: Any | None = None,
) -> tuple[int, list[tuple[float, float]]]:
    """Read and merge ET coverage for the exact frame class stored in the binary PCK files.

    ``coverage_frame`` is not the final observer frame by assumption; it is the PCK frame class
    recorded in the manifest. BPC files that do not contain this class are skipped after the
    CSPICE error state is reset. A missing/invalid frame definition fails explicitly.
    """
    if not coverage_frame.strip():
        raise ValueError("coverage_frame must not be empty")
    entries = _as_bpc_entries(bpc_entries)
    declared_frames = {str(entry["coverage_frame"]).strip() for entry in entries}
    if declared_frames != {coverage_frame.strip()}:
        raise BPCoverageError(
            f"requested PCK coverage frame {coverage_frame!r} does not match manifest declaration "
            f"{sorted(declared_frames)}"
        )

    if cell_factory is None:
        try:
            from spiceypy.utils.support_types import SPICEDOUBLE_CELL
        except ImportError as exc:  # pragma: no cover - required dependency for real runs
            raise BPCoverageError("SpiceyPy coverage-cell support is unavailable") from exc
        cell_factory = SPICEDOUBLE_CELL

    with SPICE_LOCK:
        frame_id = int(spice.namfrm(coverage_frame))
        if frame_id == 0:
            raise BPCoverageError(
                f"SPICE does not resolve PCK coverage frame {coverage_frame!r}; inspect the FK load "
                "order and the exact frame name in the binary-PCK manifest"
            )
        intervals: list[tuple[float, float]] = []
        for entry in entries:
            path = Path(entry["path"])
            cover = cell_factory(20000)
            try:
                spice.pckcov(str(path), frame_id, cover)
                for index in range(int(spice.wncard(cover))):
                    left, right = spice.wnfetd(cover, index)
                    intervals.append((float(left), float(right)))
            except Exception:
                # A BPC may store other frame classes. Clear CSPICE's global failure state before
                # trying the next asset; if none provides the requested class, the caller rejects it.
                try:
                    spice.reset()
                except Exception:
                    pass
    merged = merge_intervals(intervals)
    if not merged:
        raise BPCoverageError(
            f"none of the configured binary-PCK files contains coverage for frame class "
            f"{coverage_frame!r} (ID {frame_id})"
        )
    return frame_id, merged


def _verify_frame_transform(
    spice: Any,
    source_frame: str,
    target_frame: str,
    epochs_et_s: tuple[float, float],
) -> tuple[int, list[float]]:
    """Verify the FK/frames chain connects source and requested frame at both interval ends."""
    with SPICE_LOCK:
        target_frame_id = int(spice.namfrm(target_frame))
        if target_frame_id == 0:
            raise BPCoverageError(
                f"SPICE does not resolve requested geometry frame {target_frame!r}; the FK frame "
                "definition/association load sequence is incomplete"
            )
        try:
            for epoch in epochs_et_s:
                matrix = np.asarray(spice.pxform(source_frame, target_frame, float(epoch)), dtype=float)
                if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
                    raise ValueError("pxform returned a non-finite or non-3x3 matrix")
                orthogonality_error = float(np.max(np.abs(matrix @ matrix.T - np.eye(3))))
                determinant = float(np.linalg.det(matrix))
                if orthogonality_error > 1e-8 or abs(determinant - 1.0) > 1e-8:
                    raise ValueError(
                        "pxform result is not a proper rotation matrix "
                        f"(orthogonality_error={orthogonality_error:g}, determinant={determinant:g})"
                    )
        except Exception as exc:
            try:
                spice.reset()
            except Exception:
                pass
            raise BPCoverageError(
                f"cannot verify frame transform {source_frame!r} -> {target_frame!r} at ET "
                f"{epochs_et_s}: {type(exc).__name__}: {exc}"
            ) from exc
    return target_frame_id, [float(epochs_et_s[0]), float(epochs_et_s[1])]


def assert_required_bpc_coverage(
    spice: Any,
    loaded_kernels: Iterable[dict[str, Any]],
    start_et: float,
    end_et: float,
    *,
    frame: str = "MOON_ME",
    cell_factory: Any | None = None,
) -> dict[str, Any]:
    """Require BPC time coverage plus a valid transform to the requested frame at both endpoints."""
    if not all(math.isfinite(value) for value in (start_et, end_et)):
        raise ValueError("BPC coverage bounds must be finite")
    if end_et <= start_et:
        raise ValueError("BPC coverage end must be after start")
    loaded = list(loaded_kernels)
    bpc_entries = _as_bpc_entries(loaded)
    coverage_frame = str(bpc_entries[0]["coverage_frame"]).strip()
    frame_id, intervals = read_bpc_coverage(
        spice, bpc_entries, coverage_frame=coverage_frame, cell_factory=cell_factory,
    )
    covered = interval_covers(intervals, start_et, end_et)
    if not covered:
        raise BPCoverageError(
            f"binary-PCK coverage for stored frame class {coverage_frame} (ID {frame_id}) does not "
            f"continuously cover ET [{start_et:.3f}, {end_et:.3f}]; available intervals: {intervals}"
        )
    requested_frame_id, checked_epochs = _verify_frame_transform(
        spice, coverage_frame, frame, (start_et, end_et),
    )
    return {
        "requested_frame": frame,
        "requested_frame_id": requested_frame_id,
        "pck_coverage_frame": coverage_frame,
        "pck_coverage_frame_id": frame_id,
        "requested_et_s": [float(start_et), float(end_et)],
        "coverage_intervals_et_s": [[left, right] for left, right in intervals],
        "covers_requested_interval": True,
        "frame_transform_verified_at_et_s": checked_epochs,
    }
