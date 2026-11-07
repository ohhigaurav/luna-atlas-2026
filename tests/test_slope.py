"""Slope layer (D-23): analytic surfaces, frames, statistics, ellipse integration (no rasterio needed)."""
from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from lunar_core import analysis_service, landing_ellipse, location_scan, slope
from lunar_core.api_models import EllipseRequest, SlopeRequest
from lunar_core.location_scan import GridOffset
from lunar_core.terrain import south_polar_stereo_m
from pydantic import ValidationError

R = 1737400.0


def _plane(ax: float, by: float, n: int = 9, dx: float = 5.0) -> np.ndarray:
    cols = np.arange(n) * dx
    rows = np.arange(n) * dx
    x, y_down = np.meshgrid(cols, rows)
    return ax * x + by * (-y_down)  # row 0 = north, so y decreases down the rows


def test_horn_slope_of_a_plane_is_exact_and_border_unknown() -> None:
    z = _plane(0.1, -0.05)
    s = slope.horn_slope_deg(z, 5.0, 5.0)
    expected = math.degrees(math.atan(math.hypot(0.1, 0.05)))
    assert np.allclose(s[1:-1, 1:-1], expected, atol=1e-12)
    assert np.isnan(s[0]).all() and np.isnan(s[-1]).all() and np.isnan(s[:, 0]).all() and np.isnan(s[:, -1]).all()
    assert np.allclose(slope.central_slope_deg(z, 5.0, 5.0)[1:-1, 1:-1], expected)


def test_horn_slope_never_averages_nodata_away() -> None:
    z = _plane(0.2, 0.0)
    z[4, 4] = np.nan
    s = slope.horn_slope_deg(z, 5.0, 5.0)
    assert np.isnan(s[3:6, 3:6]).all()  # every cell whose 3x3 touches the hole
    assert np.isfinite(s[1, 1]) and np.isfinite(s[7, 7])


def test_horn_scale_factor_multiplies_the_gradient() -> None:
    z = _plane(0.1, 0.0)
    s = slope.horn_slope_deg(z, 5.0, 5.0, scale_k=1.5)
    assert np.allclose(s[1:-1, 1:-1], math.degrees(math.atan(0.15)))


def test_horn_slope_of_a_cone_away_from_the_apex() -> None:
    n, dx = 61, 5.0
    c = (np.arange(n) - n // 2) * dx
    x, y = np.meshgrid(c, -c)
    z = 0.25 * np.hypot(x, y)
    s = slope.horn_slope_deg(z, dx, dx)
    r = np.hypot(x, y)
    ring = (r > 40) & (r < 140)
    assert np.allclose(s[ring], math.degrees(math.atan(0.25)), atol=0.15)


def test_stereo_scale_factor_matches_the_projection_derivative() -> None:
    assert slope.stereo_scale_factor(0.0, 0.0, R) == 1.0
    lat = -89.0
    h = 1e-4  # degrees; smaller steps lose digits in 90 + lat
    rho = lambda la: 2 * R * math.tan(math.radians(90 + la) / 2)  # noqa: E731
    numeric = (rho(lat + h) - rho(lat - h)) / (2 * math.radians(h) * R)
    x, y = south_polar_stereo_m(lat, 30.0, R)
    assert float(slope.stereo_scale_factor(x, y, R)) == pytest.approx(numeric, abs=1e-9)


@pytest.mark.parametrize("lat,lon", [(-89.78, -24.3), (-89.45, 222.7), (-85.0, 10.0), (-60.0, -170.0)])
def test_stereo_inverse_round_trips(lat: float, lon: float) -> None:
    x, y = south_polar_stereo_m(lat, lon, R)
    la, lo = slope.stereo_to_latlon(x, y, R)
    assert float(la) == pytest.approx(lat, abs=1e-10)
    assert (float(lo) - lon + 180) % 360 - 180 == pytest.approx(0.0, abs=1e-9)


def test_local_frame_is_the_inverse_of_the_ellipse_point_geodesic() -> None:
    lat0, lon0 = -89.78, -24.3  # near Site 004, ~6.7 km from the pole: the hardest case for frames
    for e, n in [(0.0, 1500.0), (1500.0, 0.0), (-1060.0, -1060.0), (300.0, -1400.0), (25.0, 25.0)]:
        lat, lon = location_scan.offset_point(lat0, lon0, GridOffset(e, n), R)
        ee, nn = slope.local_east_north(lat0, lon0, lat, lon, R)
        assert float(ee) == pytest.approx(e, abs=1e-6) and float(nn) == pytest.approx(n, abs=1e-6)


def test_ellipse_mask_matches_the_ellipse_sample_grid() -> None:
    for a, b, th in [(250, 250, 0), (300, 100, 30), (200, 50, 90)]:
        pts = landing_ellipse.ellipse_offsets(a, b, th, 25)
        assert slope.inside_ellipse([p.east_m for p in pts], [p.north_m for p in pts], a, b, th).all()
        grid = np.arange(-a - 50, a + 51, 25.0)
        e, n = np.meshgrid(grid, grid)
        kept = {(p.east_m, p.north_m) for p in pts}
        mask = slope.inside_ellipse(e, n, a, b, th)
        assert {(float(x), float(y)) for x, y in zip(e[mask], n[mask], strict=True)} == kept


def test_verdicts_with_and_without_uncertainty() -> None:
    s = [2.0, 7.5, 8.0, 8.4, 12.0, float("nan")]
    assert list(slope.verdicts(s, 8.0)) == ["within", "within", "within", "over", "over", None]
    e = [1.0, 1.0, 1.0, 0.2, 1.0, 1.0]
    assert list(slope.verdicts(s, 8.0, e)) == ["within", "uncertain", "uncertain", "over", "over", None]


def test_area_statistics_and_cdf() -> None:
    v = np.array([1.0, 2.0, 3.0, 4.0, 9.0, 10.0, 20.0, 30.0, np.nan, np.nan])
    a = slope.area_statistics(v, 8.0, pixel_area_m2=25.0)
    assert a["pixels"] == 10 and a["pixels_known"] == 8 and a["area_m2"] == 200.0
    assert a["share_within_limit"] == pytest.approx(0.5) and a["share_over_limit"] == pytest.approx(0.5)
    assert a["slope_deg"]["max"] == 30.0 and a["slope_deg"]["median"] == 4.0
    cdf = a["cdf"]["share_at_or_below"]
    assert cdf[int(8.0 / 0.5)] == pytest.approx(0.5) and cdf[0] == 0.0 and cdf[-1] == 1.0
    assert all(x <= y for x, y in zip(cdf, cdf[1:], strict=False))
    with_err = slope.area_statistics(v, 8.0, err_deg=np.full(10, 1.5))
    shares = with_err["share_clearly_within"] + with_err["share_uncertain"] + with_err["share_clearly_over"]
    assert shares == pytest.approx(1.0) and with_err["share_uncertain"] == pytest.approx(1 / 8)  # only 9 deg is within 1.5 of 8
    assert slope.area_statistics(np.array([np.nan]), 8.0) == {"pixels": 1, "pixels_known": 0}


def test_overlay_is_max_pooled_in_the_local_frame() -> None:
    e = np.array([-98.0, -97.0, 99.0, 0.0])  # first two share the north-west cell
    n = np.array([98.0, 97.0, -99.0, 0.0])
    s = np.array([3.0, 7.0, 12.0, 1.0])
    inside = np.array([True, True, True, False])
    o = slope.overlay_grid(e, n, s, inside, 100.0, 5.0)
    assert o["cells_east"] == o["cells_north"] == math.ceil(200 / o["cell_m"])
    rows = o["max_slope_deg"]
    assert rows[0][0] == 7.0 and rows[-1][-1] == 12.0
    assert sum(v is not None for r in rows for v in r) == 2


# ------------------------------------------------------------------ end to end with a fake raster


SITE = {"site_id": "polar", "name": "Polar", "latitude_deg": -89.5, "longitude_deg": 10.0, "origin": "reference"}
GRADIENT = 0.1  # z = 0.1 x (map metres): slope atan(0.1 k) everywhere


def _fake_reader(edge_x: float = 20000.0) -> Any:
    def read(path: Path, x_m: float, y_m: float, half_m: float, units: str = "m") -> slope.Window:
        x_left, y_top, dx, width = -edge_x, edge_x, 5.0, int(2 * edge_x / 5.0)
        c0 = math.floor((x_m - half_m - x_left) / dx) - slope.MARGIN_PIXELS
        c1 = math.ceil((x_m + half_m - x_left) / dx) + slope.MARGIN_PIXELS
        r0 = math.floor((y_top - (y_m + half_m)) / dx) - slope.MARGIN_PIXELS
        r1 = math.ceil((y_top - (y_m - half_m)) / dx) + slope.MARGIN_PIXELS
        if c0 < 0 or r0 < 0 or c1 > width or r1 > width:
            raise slope.SlopeNotAvailable("off the tile")
        xs = x_left + (np.arange(c0, c1) + 0.5) * dx
        z = np.tile(GRADIENT * xs, (r1 - r0, 1))
        if units == "deg":  # a stand-in error layer: 1 deg everywhere
            z = np.ones_like(z)
        return slope.Window(z, r0, c0, width, width, x_left, y_top, dx, dx, ("crs", width))
    return read


@pytest.fixture
def fake_terrain(monkeypatch: pytest.MonkeyPatch) -> None:
    asset = SimpleNamespace(asset_id="fake-5m", product_id="fake", native_resolution_m=5.0, sha256="0" * 64,
                            elevation_units="m")
    monkeypatch.setattr(slope, "fine_assets", lambda site: [(asset, Path("fake.tif"))])
    monkeypatch.setattr(slope, "read_window", _fake_reader())
    monkeypatch.setattr(slope, "load_layers", lambda: [])


def test_ellipse_slope_on_a_known_plane(fake_terrain: None) -> None:
    offsets = landing_ellipse.ellipse_offsets(250, 250, 0, 50)
    out = slope.ellipse_slope(SITE, 250, 250, 0, offsets, limit_deg=6.0)
    x, y = south_polar_stereo_m(SITE["latitude_deg"], SITE["longitude_deg"], R)
    k = float(slope.stereo_scale_factor(x, y, R))
    expected = math.degrees(math.atan(GRADIENT * k))  # 5.7106 deg
    assert out["status"] == "ok" and out["method"]["source"] == "computed"
    assert out["area"]["slope_deg"]["median"] == pytest.approx(expected, abs=1e-6)
    assert out["area"]["pixels_known"] == out["area"]["pixels"] == pytest.approx(math.pi * 250**2 / 25, rel=0.02)
    assert out["area"]["share_within_limit"] == 1.0
    assert len(out["points"]) == len(offsets)
    assert all(p["slope_deg"] == pytest.approx(expected, abs=0.01) and p["slope_verdict"] == "within"
               for p in out["points"])
    assert out["chips"][0].startswith("target 5.7") and out["uncertainty"]["available"] is False
    assert out["overlay"]["cells_east"] <= slope.OVERLAY_MAX_CELLS + 1
    tight = slope.ellipse_slope(SITE, 250, 250, 0, offsets, limit_deg=5.0)
    assert tight["area"]["share_over_limit"] == 1.0 and tight["points"][0]["slope_verdict"] == "over"


def test_ellipse_slope_uses_the_published_error_layer(fake_terrain: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(slope, "companion", lambda asset_id, kind, root, layers:
                        (Path("err.tif"), {"layer_id": "fake-err"}) if kind == "slope_rms_error_deg" else None)
    offsets = landing_ellipse.ellipse_offsets(100, 100, 0, 50)
    out = slope.ellipse_slope(SITE, 100, 100, 0, offsets, limit_deg=6.0)  # 5.71 is within 1 deg of 6
    assert out["uncertainty"]["layer_id"] == "fake-err"
    assert out["area"]["share_uncertain"] == 1.0
    assert {p["slope_verdict"] for p in out["points"]} == {"uncertain"}
    assert out["points"][0]["slope_err_deg"] == 1.0


def test_slope_not_available_cases(fake_terrain: None, monkeypatch: pytest.MonkeyPatch) -> None:
    north = slope.ellipse_slope({**SITE, "latitude_deg": 10.0}, 250, 250, 0, [])
    assert north["status"] == "not_available"
    monkeypatch.setattr(slope, "read_window", _fake_reader(edge_x=15500.0))  # tile edge inside the ellipse
    edge = slope.ellipse_slope(SITE, 1500, 1500, 0, [])
    assert edge["status"] == "not_available" and edge["reason"] == "off the tile"
    assert slope.ellipse_slope(SITE, 250, 250, 0, [])["status"] == "ok"  # a small ellipse still fits
    monkeypatch.setattr(slope, "fine_assets", lambda site: [])
    none = slope.ellipse_slope(SITE, 250, 250, 0, [])
    assert none["status"] == "not_available" and "240 m" in none["reason"]


def test_fine_assets_never_offers_the_regional_map() -> None:
    # Excluded by rule (resolution and the "*" catch-all), whether or not the rasters are staged.
    from lunar_core.terrain import load_dem_manifest
    regional = [a for a in load_dem_manifest(analysis_service.DEM_MANIFEST).assets if "*" in a.site_ids]
    assert regional and all(a.native_resolution_m > slope.MAX_SLOPE_RESOLUTION_M for a in regional)
    offered = slope.fine_assets({"site_id": "reference-lola-site-001", "latitude_deg": -89.45, "longitude_deg": 222.69})
    assert all(a.native_resolution_m <= slope.MAX_SLOPE_RESOLUTION_M for a, _ in offered)


def test_slope_request_rules() -> None:
    ok = SlopeRequest(site_id="s")
    assert ok.slope_limit_deg == 8.0 and ok.semi_major_m == 250.0
    for bad in ({"slope_limit_deg": 0.1}, {"slope_limit_deg": 60}, {"semi_minor_m": 300},
                {"latitude_deg": -89.0, "longitude_deg": 10.0}, {"extra": 1}):
        with pytest.raises(ValidationError):
            SlopeRequest(**{"site_id": "s", **bad})
    with pytest.raises(ValidationError):
        SlopeRequest()
    assert SlopeRequest(latitude_deg=-89.4, longitude_deg=220.0).site_id is None


def test_run_slope_for_site_and_point(fake_terrain: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analysis_service, "_load_sites", lambda: {"polar": SITE})
    out = slope.run_slope(SlopeRequest(site_id="polar", semi_major_m=200, slope_limit_deg=10))
    assert out["status"] == "ok" and out["site"]["site_id"] == "polar"
    assert out["ellipse"]["point_count"] == len(out["points"]) and out["limit_deg"] == 10
    pt = slope.run_slope(SlopeRequest(latitude_deg=-89.5, longitude_deg=10.0))
    assert pt["status"] == "ok" and pt["site"]["origin"] == "custom"
    with pytest.raises(ValueError, match="unknown site"):
        slope.run_slope(SlopeRequest(site_id="nope"))


# ------------------------------------------------------------------ ellipse integration


def _pt(e: float, n: float, sun: float) -> dict[str, Any]:
    return {"east_m": e, "north_m": n, "distance_m": math.hypot(e, n), "latitude_deg": -89.5,
            "longitude_deg": 10.0, "status": "ok", "sunlit_percent": sun, "dte_clear_percent": 50.0,
            "both_percent": min(sun, 50.0)}


@pytest.fixture
def fake_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analysis_service, "_load_sites", lambda: {"polar": SITE})
    monkeypatch.setattr(analysis_service, "RUNS_DIR", tmp_path / "runs")

    def scan(site_id: str, request: Any, **kw: Any) -> dict[str, Any]:
        pts = [_pt(o.east_m, o.north_m, 90.0 if o.east_m > 0 else 40.0) for o in kw["offsets"]]
        return {"site": {"site_id": site_id}, "settings": {}, "points": pts, "points_unavailable": 0,
                "provenance": {"fake": True}}

    monkeypatch.setattr(location_scan, "run_location_scan", scan)


def test_ellipse_points_carry_slope_and_best_flat_enough_point(fake_scan: None, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_slope(site: Any, a: float, b: float, th: float, offsets: list[GridOffset], limit: float) -> dict[str, Any]:
        pts = [{"east_m": o.east_m, "north_m": o.north_m, "slope_deg": 12.0 if o.east_m > 0 else 3.0,
                "slope_err_deg": None, "slope_verdict": "over" if o.east_m > 0 else "within"} for o in offsets]
        return {"kind": "slope", "status": "ok", "points": pts, "chips": ["typical 3.0°"]}

    monkeypatch.setattr(slope, "ellipse_slope", fake_slope)
    r = landing_ellipse.run_landing_ellipse(EllipseRequest(site_id="polar", start_utc="2027-01-01T00:00:00Z",
                                                           semi_major_m=100, spacing_m=50))
    assert r["slope"]["status"] == "ok" and "points" not in r["slope"]
    east = [p for p in r["points"] if p["east_m"] > 0]
    assert east and all(p["slope_deg"] == 12.0 and p["slope_verdict"] == "over" for p in east)
    best = r["slope"]["best_sunlit_within_limit"]
    assert best["east_m"] <= 0 and best["sunlit_percent"] == 40.0 and best["slope_deg"] == 3.0
    assert r["risk"]["best_point"]["sunlit_percent"] == 90.0  # the sunlight answer is unchanged


def test_slope_failure_never_breaks_the_ellipse(fake_scan: None, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any, **k: Any) -> dict[str, Any]:
        raise RuntimeError("rasterio missing")

    monkeypatch.setattr(slope, "ellipse_slope", boom)
    r = landing_ellipse.run_landing_ellipse(EllipseRequest(site_id="polar", start_utc="2027-01-01T00:00:00Z",
                                                           semi_major_m=100))
    assert r["slope"]["status"] == "error" and "rasterio missing" in r["slope"]["reason"]
    assert r["risk"]["points_ok"] == len(r["points"]) and all(p["slope_deg"] is None for p in r["points"])


@pytest.mark.usefixtures("unconfigured_project")
def test_unconfigured_checkout_gives_a_reason_not_an_error() -> None:
    out = slope.ellipse_slope({**SITE, "site_id": "custom-point"}, 250, 250, 0,
                              landing_ellipse.ellipse_offsets(250, 250, 0, 50))
    assert out["status"] == "not_available" and "240 m" in out["reason"] and out["chips"] == []


def test_window_covers_the_whole_ellipse_where_map_scale_is_large(fake_terrain: None, monkeypatch: pytest.MonkeyPatch) -> None:
    far = {**SITE, "latitude_deg": -62.0, "longitude_deg": 10.0}  # k ~ 1.06: an unscaled box would clip
    monkeypatch.setattr(slope, "read_window", _fake_reader(edge_x=1000000.0))
    out = slope.ellipse_slope(far, 1500, 1500, 0, [], include_overlay=False)
    assert out["status"] == "ok"
    # every ground pixel of the disc is present: area matches pi a^2 to the pixel quantisation
    assert out["area"]["area_m2"] == pytest.approx(math.pi * 1500**2, rel=0.005)
