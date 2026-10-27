"""Bilinear DEM sampling without Rasterio: fake datasets exercise the windowed read path."""
from __future__ import annotations

import math

import numpy as np
import pytest
from lunar_core import terrain
from lunar_core.terrain import (
    DEMManifestError,
    _bilinear_from_grid,
    _physical_grid_m,
    _ray_latlon_grid,
    _sample_dataset_bilinear,
)


class Affine2:
    """Minimal north-up affine: x = x0 + col*res, y = y0 - row*res (and its inverse)."""

    def __init__(self, x0: float, y0: float, res: float, inverse: bool = False) -> None:
        self.x0, self.y0, self.res, self.inverse = x0, y0, res, inverse

    def __invert__(self) -> Affine2:
        return Affine2(self.x0, self.y0, self.res, not self.inverse)

    # Coefficients in affine's convention: x' = a*x + b*y + c, y' = d*x + e*y + f.
    @property
    def a(self) -> float:
        return 1.0 / self.res if self.inverse else self.res

    @property
    def b(self) -> float:
        return 0.0

    @property
    def c(self) -> float:
        return -self.x0 / self.res if self.inverse else self.x0

    @property
    def d(self) -> float:
        return 0.0

    @property
    def e(self) -> float:
        return -1.0 / self.res if self.inverse else -self.res

    @property
    def f(self) -> float:
        return self.y0 / self.res if self.inverse else self.y0


class FakeDataset:
    def __init__(self, raw: np.ndarray, *, nodata: float | None = -9999.0, scale: float = 1.0,
                 offset: float = 0.0, res: float = 10.0) -> None:
        self.raw = raw
        self.height, self.width = raw.shape
        self.nodata = nodata
        self.scales = (scale,)
        self.offsets = (offset,)
        self.transform = Affine2(0.0, 0.0, res)
        self.reads: list[tuple[int, int, int, int]] = []

    def read_window(self, row_off: int, col_off: int, height: int, width: int) -> np.ma.MaskedArray:
        self.reads.append((row_off, col_off, height, width))
        block = self.raw[row_off:row_off + height, col_off:col_off + width]
        assert block.shape == (height, width), "window must lie inside the raster"
        return np.ma.masked_array(block, mask=np.zeros(block.shape, dtype=bool))


@pytest.fixture(autouse=True)
def _fake_window_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        terrain, "_read_window",
        lambda ds, row_off, col_off, height, width: ds.read_window(row_off, col_off, height, width),
    )


def _plane(height: int = 20, width: int = 30) -> np.ndarray:
    rows, cols = np.mgrid[0:height, 0:width]
    return (3.0 * cols + 7.0 * rows).astype(float)  # value at pixel centre (row, col)


def test_bilinear_reproduces_a_linear_surface_exactly() -> None:
    grid = _plane()
    rng = np.random.default_rng(1)
    cols_f = rng.uniform(0.5, 29.5, 500)  # inside the pixel-centre hull
    rows_f = rng.uniform(0.5, 19.5, 500)
    out = _bilinear_from_grid(grid, 0, 0, rows_f, cols_f, 20, 30)
    np.testing.assert_allclose(out, 3.0 * (cols_f - 0.5) + 7.0 * (rows_f - 0.5), atol=1e-9)


def test_nodata_neighbour_poisons_only_samples_that_use_it() -> None:
    grid = _plane()
    grid[5, 5] = np.nan
    # Exactly on the centre of pixel (5, 6): weight on (5, 5) is zero -> still valid.
    on_centre = _bilinear_from_grid(grid, 0, 0, np.array([5.5]), np.array([6.5]), 20, 30)
    assert on_centre[0] == pytest.approx(3.0 * 6 + 7.0 * 5)
    # Between centres (5, 5) and (5, 6): uses the NoData pixel -> unknown, never averaged away.
    between = _bilinear_from_grid(grid, 0, 0, np.array([5.5]), np.array([6.0]), 20, 30)
    assert np.isnan(between[0])


def test_outside_footprint_is_unknown_and_edge_half_pixel_is_clamped() -> None:
    grid = _plane()
    out = _bilinear_from_grid(
        grid, 0, 0, np.array([-0.01, 0.2, 19.99, 10.0]), np.array([10.0, 0.2, 29.99, 30.0]), 20, 30,
    )
    assert np.isnan(out[0])          # above the top edge
    assert out[1] == pytest.approx(0.0)  # inside the outer half pixel: clamped to pixel (0, 0)
    assert out[2] == pytest.approx(3.0 * 29 + 7.0 * 19)
    assert np.isnan(out[3])          # col == width is outside


def test_dataset_sampler_reads_one_bounding_window_and_applies_scale_offset_units() -> None:
    raw = np.full((200, 300), 4.0)
    raw[150, 250] = -9999.0
    ds = FakeDataset(raw, scale=0.5, offset=2.0, res=10.0)  # (4 * 0.5 + 2) km = 4000 m
    xs = np.array([505.0, 1005.0, 1505.0])
    ys = np.array([-505.0, -805.0, -605.0])
    out = _sample_dataset_bilinear(ds, xs, ys, "km")
    np.testing.assert_allclose(out, 4_000.0)
    assert len(ds.reads) == 1
    row_off, col_off, height, width = ds.reads[0]
    assert (row_off, col_off) == (50, 50)
    assert row_off + height <= 82 and col_off + width <= 152  # only the bounding window

    near_nodata = _sample_dataset_bilinear(ds, np.array([2505.0]), np.array([-1500.0]), "m")
    assert np.isnan(near_nodata[0])


def test_oversized_window_is_split_not_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _plane(100, 100)
    ds = FakeDataset(raw, res=10.0)
    monkeypatch.setattr(terrain, "MAX_WINDOW_PIXELS", 50)
    rng = np.random.default_rng(3)
    cols = rng.uniform(1.0, 99.0, 40)
    rows = rng.uniform(1.0, 99.0, 40)
    out = _sample_dataset_bilinear(ds, cols * 10.0, -rows * 10.0, "m")
    np.testing.assert_allclose(out, 3.0 * (cols - 0.5) + 7.0 * (rows - 0.5), atol=1e-9)
    assert len(ds.reads) > 1
    assert all(h * w <= 50 or h * w <= 4 for _r, _c, h, w in ds.reads)


def test_unexpected_window_geometry_fails_closed() -> None:
    with pytest.raises(DEMManifestError, match="outside the read window"):
        _bilinear_from_grid(np.zeros((2, 2)), 0, 0, np.array([10.5]), np.array([10.5]), 20, 20)


def test_physical_grid_marks_nodata_masked_and_nonfinite_unknown() -> None:
    ds = FakeDataset(np.zeros((1, 1)), nodata=-9999.0, scale=2.0, offset=1.0)
    raw = np.ma.masked_array([[1.0, -9999.0, np.inf, 3.0]], mask=[[False, False, False, True]])
    out = _physical_grid_m(ds, raw, "m")
    assert out[0, 0] == pytest.approx(3.0)
    assert np.isnan(out[0, 1:]).all()


def test_ray_grid_matches_spherical_forward_geodesic() -> None:
    radius = 1_737_400.0
    lat, lon = _ray_latlon_grid(
        -89.5, 222.0, np.array([0.0, 180.0, 180.0]), np.array([10_000.0, 10_000.0, 20_000.0]), radius,
    )
    step_deg = math.degrees(10_000.0 / radius)  # 0.3298 deg per 10 km
    # Due north moves toward the equator along the same meridian.
    assert lat[0] == pytest.approx(-89.5 + step_deg, abs=1e-9)
    assert lon[0] == pytest.approx(222.0 - 360.0, abs=1e-6)
    # Due south 10 km stays on the meridian (the pole is 15.2 km away) ...
    assert lat[1] == pytest.approx(-89.5 - step_deg, abs=1e-9)
    # ... while 20 km crosses the pole onto the opposite meridian.
    assert lat[2] == pytest.approx(-90.0 + (2 * step_deg - 0.5), abs=1e-9)
    assert lon[2] == pytest.approx(42.0, abs=1e-6)
