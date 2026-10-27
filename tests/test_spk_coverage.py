from __future__ import annotations

import math
from pathlib import Path

import pytest
from lunar_core.spk_coverage import (
    REQUIRED_OBJECTS,
    SPKCoverageError,
    assert_required_spk_coverage,
    interval_covers,
    merge_intervals,
)


class Cell:
    def __init__(self, _capacity: int) -> None:
        self.target_id: int | None = None


class FakeSpice:
    def __init__(self, intervals: dict[int, tuple[float, float]] | None = None) -> None:
        self.intervals = intervals or {target_id: (-5000.0, 50000.0) for target_id in REQUIRED_OBJECTS}

    def spkcov(self, path: str, target_id: int, cover: Cell) -> None:
        assert Path(path).suffix == ".bsp"
        if target_id not in self.intervals:
            raise RuntimeError("object has no coverage in this SPK")
        cover.target_id = target_id

    def wncard(self, cover: Cell) -> int:
        return 1 if cover.target_id in self.intervals else 0

    def wnfetd(self, cover: Cell, _index: int) -> tuple[float, float]:
        assert cover.target_id is not None
        return self.intervals[cover.target_id]

    def reset(self) -> None:
        pass


def test_merges_adjacent_coverage_but_preserves_real_gaps() -> None:
    assert merge_intervals([(5, 8), (1, 3), (3, 5), (10, 12)]) == [(1.0, 8.0), (10.0, 12.0)]
    assert interval_covers([(0, 5), (5, 10)], 1, 9)
    assert not interval_covers([(0, 4.9), (5.1, 10)], 1, 9)


def test_interval_covers_rejects_nonfinite_or_invalid_ranges() -> None:
    with pytest.raises(ValueError):
        merge_intervals([(0, math.inf)])
    with pytest.raises(ValueError):
        interval_covers([(0, 1)], 2, 1)


def test_required_coverage_includes_lt_preroll() -> None:
    report = assert_required_spk_coverage(
        FakeSpice(), [{"path": "/tmp/de421.bsp"}], 0.0, 40000.0, cell_factory=Cell
    )
    assert report["light_time_preroll_s"] == 1200.0
    assert all(item["covers_requested_interval"] for item in report["objects"].values())


def test_required_coverage_fails_when_an_object_has_a_gap() -> None:
    partial = {target_id: (-5000.0, 50000.0) for target_id in REQUIRED_OBJECTS}
    partial[399] = (-100.0, 1000.0)
    with pytest.raises(SPKCoverageError, match=r"EARTH \(399\)"):
        assert_required_spk_coverage(
            FakeSpice(partial), [{"path": "/tmp/de421.bsp"}], 0.0, 500.0, cell_factory=Cell
        )
