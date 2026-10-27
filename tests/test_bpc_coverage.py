from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from lunar_core.bpc_coverage import (
    BPCoverageError,
    assert_required_bpc_coverage,
    read_bpc_coverage,
)


class Window:
    def __init__(self, _capacity: int) -> None:
        self.intervals: list[tuple[float, float]] = []


class FakeSpice:
    frame_codes = {"MOON_ME": 31001, "MOON_PA_DE421": 31006}

    def __init__(self, by_path: dict[str, list[tuple[float, float]]]) -> None:
        self.by_path = by_path
        self.resets = 0
        self.pckcov_calls: list[tuple[str, int]] = []
        self.pxform_calls: list[tuple[str, str, float]] = []

    def namfrm(self, frame: str) -> int:
        return self.frame_codes.get(frame, 0)

    def pckcov(self, path: str, idcode: int, cover: Window) -> None:
        self.pckcov_calls.append((path, idcode))
        assert idcode == self.frame_codes["MOON_PA_DE421"]
        if path not in self.by_path:
            raise RuntimeError("this BPC does not contain this reference frame")
        cover.intervals.extend(self.by_path[path])

    def wncard(self, cover: Window) -> int:
        return len(cover.intervals)

    def wnfetd(self, cover: Window, index: int) -> tuple[float, float]:
        return cover.intervals[index]

    def pxform(self, source: str, target: str, epoch: float) -> np.ndarray:
        self.pxform_calls.append((source, target, epoch))
        if source != "MOON_PA_DE421" or target != "MOON_ME":
            raise RuntimeError(f"no frame transform from {source} to {target}")
        return np.eye(3)

    def reset(self) -> None:
        self.resets += 1


def bpc(path: str, start: float = 0.0, end: float = 100.0) -> dict[str, Any]:
    return {
        "kernel_id": path.rsplit("/", 1)[-1],
        "path": path,
        "kernel_type": "BPC",
        "coverage_frame": "MOON_PA_DE421",
    }


def test_bpc_coverage_uses_stored_pck_frame_then_checks_me_transform() -> None:
    spice = FakeSpice({"/kernels/a.bpc": [(0.0, 50.0)], "/kernels/b.bpc": [(50.0, 100.0)]})
    report = assert_required_bpc_coverage(
        spice,
        [bpc("/kernels/a.bpc"), bpc("/kernels/b.bpc")],
        10.0,
        90.0,
        frame="MOON_ME",
        cell_factory=Window,
    )
    assert report["requested_frame"] == "MOON_ME"
    assert report["requested_frame_id"] == 31001
    assert report["pck_coverage_frame"] == "MOON_PA_DE421"
    assert report["pck_coverage_frame_id"] == 31006
    assert report["coverage_intervals_et_s"] == [[0.0, 100.0]]
    assert report["covers_requested_interval"] is True
    assert report["frame_transform_verified_at_et_s"] == [10.0, 90.0]
    assert spice.pckcov_calls == [
        ("/kernels/a.bpc", 31006), ("/kernels/b.bpc", 31006),
    ]
    assert spice.pxform_calls == [
        ("MOON_PA_DE421", "MOON_ME", 10.0),
        ("MOON_PA_DE421", "MOON_ME", 90.0),
    ]


def test_orientation_coverage_fails_on_gap() -> None:
    spice = FakeSpice({"/kernels/a.bpc": [(0.0, 40.0)], "/kernels/b.bpc": [(60.0, 100.0)]})
    with pytest.raises(BPCoverageError, match="does not continuously cover"):
        assert_required_bpc_coverage(
            spice,
            [bpc("/kernels/a.bpc"), bpc("/kernels/b.bpc")],
            10.0,
            90.0,
            frame="MOON_ME",
            cell_factory=Window,
        )


def test_orientation_coverage_fails_without_binary_pck() -> None:
    with pytest.raises(BPCoverageError, match="no binary-PCK"):
        read_bpc_coverage(
            FakeSpice({}), [{"path": "/kernels/de421.bsp", "kernel_type": "SPK"}],
            coverage_frame="MOON_PA_DE421", cell_factory=Window,
        )


def test_unresolved_stored_pck_frame_fails_closed() -> None:
    spice = FakeSpice({"/kernels/moon.bpc": [(0.0, 100.0)]})
    spice.frame_codes = {"MOON_ME": 31001}  # omit MOON_PA_DE421 from the FK map
    with pytest.raises(BPCoverageError, match="does not resolve PCK coverage frame"):
        read_bpc_coverage(
            spice, [bpc("/kernels/moon.bpc")], coverage_frame="MOON_PA_DE421", cell_factory=Window,
        )


def test_non_orientation_file_errors_are_cleared_before_next_bpc() -> None:
    spice = FakeSpice({"/kernels/good.bpc": [(0.0, 100.0)]})
    frame_id, intervals = read_bpc_coverage(
        spice,
        [bpc("/kernels/other-frame.bpc"), bpc("/kernels/good.bpc")],
        coverage_frame="MOON_PA_DE421",
        cell_factory=Window,
    )
    assert frame_id == 31006
    assert intervals == [(0.0, 100.0)]
    assert spice.resets == 1


def test_missing_coverage_frame_in_manifest_fails_closed() -> None:
    with pytest.raises(BPCoverageError, match="must declare its exact coverage_frame"):
        read_bpc_coverage(
            FakeSpice({"/kernels/moon.bpc": [(0.0, 100.0)]}),
            [{"path": "/kernels/moon.bpc", "kernel_type": "BPC"}],
            coverage_frame="MOON_PA_DE421",
            cell_factory=Window,
        )


def test_transform_chain_is_verified_at_requested_endpoints() -> None:
    spice = FakeSpice({"/kernels/moon.bpc": [(0.0, 100.0)]})

    def fail_transform(_source: str, _target: str, _epoch: float) -> np.ndarray:
        raise RuntimeError("FK association missing")

    spice.pxform = fail_transform  # type: ignore[method-assign]
    with pytest.raises(BPCoverageError, match="cannot verify frame transform"):
        assert_required_bpc_coverage(
            spice, [bpc("/kernels/moon.bpc")], 10.0, 90.0,
            frame="MOON_ME", cell_factory=Window,
        )


def test_non_rotation_frame_transform_fails_closed() -> None:
    spice = FakeSpice({"/kernels/moon.bpc": [(0.0, 100.0)]})
    spice.pxform = lambda _source, _target, _epoch: np.full((3, 3), 2.0)  # type: ignore[method-assign]
    with pytest.raises(BPCoverageError, match="proper rotation matrix"):
        assert_required_bpc_coverage(
            spice, [bpc("/kernels/moon.bpc")], 10.0, 90.0,
            frame="MOON_ME", cell_factory=Window,
        )
