"""Ground slope over a landing ellipse, from the 5 m LOLA site DEMs (D-23).

What it is: the slope of the 5 m/pixel LOLA surface model, Horn (1981) 3x3 finite differences
(the GDAL ``gdaldem slope`` default), so each value spans 10 m between outer pixel centres. The
polar-stereographic grid is not true scale away from the pole, so the gradient is multiplied by
k = 1 + rho^2 / (4 R^2) (at most ~3e-5 on the Site 001/004 tiles; applied anyway).

What it is not: a hazard certification. About 90 % of the 5 m pixels are interpolated between
LOLA tracks (PGDA Product 78), and rocks or craters smaller than ~10 m are not resolved, so real
lander-scale slopes can be steeper than shown. The 240 m regional map is never used: a 240 m slope
says nothing about a lander's footing. Where PGDA's slope RMS error layer is staged, a value within
one RMS error of the user's limit is reported as "uncertain" instead of within / over.

Validation (Gate S, PASS 2026-11-08): computed slope against PGDA's published slope maps for Sites
001 and 004, pass rule ``validation/slope_tolerances.json`` approved before the run, tool
``tools/validate_slope.py``, evidence ``validation/evidence/slope_check_2026-11-08.md``. Median
difference -0.002 / -0.004 deg, p95 0.70 / 0.92 deg (limit 1.5). ``SLOPE_SOURCE`` stays "computed".

The pure functions (Horn slope, projections, ellipse mask, statistics) need only NumPy. Rasters are
read through ``read_window``, which tests replace.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from lunar_core import custom_point

SLOPE_ALGORITHM = "slope-1.0-horn3x3-stereo-k"
SLOPE_SOURCE: Literal["computed", "published"] = "computed"  # Gate S consequence; see module docstring
MAX_SLOPE_RESOLUTION_M = 5.0
DEFAULT_LIMIT_DEG = 8.0
LIMIT_NOTE = ("Set this to your lander's slope limit. The default 8° is the example threshold used by "
              "Barker et al. (LEAG 2021), not a requirement for any lander.")
CDF_STEP_DEG = 0.5
CDF_MAX_DEG = 45.0
OVERLAY_MAX_CELLS = 48
MARGIN_PIXELS = 2
LABEL = ("Slope of the 5 m LOLA terrain, 10 m baseline (3×3 Horn). Not a hazard certification: rocks and "
         "craters smaller than ~10 m are not resolved, and most 5 m pixels are interpolated between LOLA tracks.")
VALIDATION: dict[str, Any] = {
    "gate": "S",
    "status": "pass",
    "rule": "validation/slope_tolerances.json",
    "evidence": "validation/evidence/slope_check_2026-11-08.md",
    "summary": ("Checked against NASA PGDA's published slope maps at Sites 001 and 004 (pass rule fixed before the run, "
                "8 Nov 2026): median difference -0.002 deg / -0.004 deg, 95% of pixels within 0.70 deg / 0.92 deg, "
                "within-vs-over-8 deg calls differ on 1.2% / 0.4% of the ground. Same grid, 100% coverage, 1.5 km "
                "around each site."),
    "scope": "Checked on the two 5 m tiles of Sites 001 and 004; other 5 m tiles use the same code but were not compared.",
}
SLOPE_LAYERS = Path(__file__).resolve().parents[2] / "data" / "dems" / "slope_layers.json"


class SlopeNotAvailable(ValueError):
    """No verified <= 5 m DEM covers the requested ground (an answer, not a server fault)."""


# --------------------------------------------------------------------------- pure geometry


def horn_slope_deg(z: Any, dx_m: float, dy_m: float, scale_k: Any = 1.0) -> Any:
    """Horn 3x3 slope in degrees of a north-up grid (row 0 = north). Border and NoData-touched cells NaN.

    ``scale_k`` (scalar or grid) multiplies the map gradient: true gradient = k x map gradient for a
    conformal projection whose map distances are k times ground distances.
    """
    import numpy as np

    z = np.asarray(z, dtype=float)
    out = np.full(z.shape, np.nan)
    if z.shape[0] < 3 or z.shape[1] < 3:
        return out
    a, b, c = z[:-2, :-2], z[:-2, 1:-1], z[:-2, 2:]
    d, f = z[1:-1, :-2], z[1:-1, 2:]
    g, h, i = z[2:, :-2], z[2:, 1:-1], z[2:, 2:]
    dzdx = ((c + 2 * f + i) - (a + 2 * d + g)) / (8.0 * dx_m)
    dzdy = ((a + 2 * b + c) - (g + 2 * h + i)) / (8.0 * dy_m)
    k = np.asarray(scale_k, dtype=float)
    k_inner = k[1:-1, 1:-1] if k.ndim == 2 else k
    # NaN in any of the 8 neighbours makes the sum NaN; Horn's weights skip the centre pixel, so
    # a NoData centre is masked explicitly. Unknown never becomes a number.
    inner = np.degrees(np.arctan(k_inner * np.hypot(dzdx, dzdy)))
    inner[~np.isfinite(z[1:-1, 1:-1])] = np.nan
    out[1:-1, 1:-1] = inner
    return out


def central_slope_deg(z: Any, dx_m: float, dy_m: float, scale_k: Any = 1.0) -> Any:
    """2-pixel central differences (diagnostic for Gate S only; not the production method)."""
    import numpy as np

    z = np.asarray(z, dtype=float)
    out = np.full(z.shape, np.nan)
    if z.shape[0] < 3 or z.shape[1] < 3:
        return out
    dzdx = (z[1:-1, 2:] - z[1:-1, :-2]) / (2.0 * dx_m)
    dzdy = (z[:-2, 1:-1] - z[2:, 1:-1]) / (2.0 * dy_m)
    k = np.asarray(scale_k, dtype=float)
    k_inner = k[1:-1, 1:-1] if k.ndim == 2 else k
    inner = np.degrees(np.arctan(k_inner * np.hypot(dzdx, dzdy)))
    inner[~np.isfinite(z[1:-1, 1:-1])] = np.nan
    out[1:-1, 1:-1] = inner
    return out


def stereo_scale_factor(x_m: Any, y_m: Any, radius_m: float) -> Any:
    """Point scale of the south-polar stereographic map (true at the pole): k = 1 + rho^2 / (4 R^2)."""
    import numpy as np

    x, y = np.asarray(x_m, dtype=float), np.asarray(y_m, dtype=float)
    return 1.0 + (x * x + y * y) / (4.0 * radius_m * radius_m)


def stereo_to_latlon(x_m: Any, y_m: Any, radius_m: float) -> tuple[Any, Any]:
    """Inverse of ``terrain.south_polar_stereo_m``: latitude (deg) and east longitude in [-180, 180)."""
    import numpy as np

    x, y = np.asarray(x_m, dtype=float), np.asarray(y_m, dtype=float)
    lat = np.degrees(2.0 * np.arctan(np.hypot(x, y) / (2.0 * radius_m))) - 90.0
    lon = (np.degrees(np.arctan2(x, y)) + 180.0) % 360.0 - 180.0
    return lat, lon


def local_east_north(lat0_deg: float, lon0_deg: float, lat_deg: Any, lon_deg: Any,
                     radius_m: float) -> tuple[Any, Any]:
    """Spherical geodesic distance and initial bearing from (lat0, lon0) as local east/north metres.

    The exact inverse of the forward geodesic that places ellipse sample points
    (``location_scan.offset_point``), so a pixel and a sample point use one frame.
    """
    import numpy as np

    p1, p2 = math.radians(lat0_deg), np.radians(np.asarray(lat_deg, dtype=float))
    dl = np.radians(np.asarray(lon_deg, dtype=float) - lon0_deg)
    hav = np.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    dist = 2.0 * radius_m * np.arcsin(np.sqrt(np.clip(hav, 0.0, 1.0)))
    bearing = np.arctan2(np.sin(dl) * np.cos(p2), math.cos(p1) * np.sin(p2) - math.sin(p1) * np.cos(p2) * np.cos(dl))
    return dist * np.sin(bearing), dist * np.cos(bearing)


def inside_ellipse(east_m: Any, north_m: Any, semi_major_m: float, semi_minor_m: float,
                   orientation_deg: float) -> Any:
    """Same test as ``landing_ellipse.ellipse_offsets`` (major axis bearing clockwise from north)."""
    import numpy as np

    theta = math.radians(orientation_deg)
    ux, uy = math.sin(theta), math.cos(theta)
    e, n = np.asarray(east_m, dtype=float), np.asarray(north_m, dtype=float)
    along = e * ux + n * uy
    across = -e * uy + n * ux
    return (along / semi_major_m) ** 2 + (across / semi_minor_m) ** 2 <= 1.0 + 1e-9


# --------------------------------------------------------------------------- statistics


def verdicts(slope_deg: Any, limit_deg: float, err_deg: Any = None) -> Any:
    """'within' / 'over', or 'uncertain' when the value is within one RMS error of the limit."""
    import numpy as np

    s = np.asarray(slope_deg, dtype=float)
    out = np.full(s.shape, None, dtype=object)
    ok = np.isfinite(s)
    out[ok & (s <= limit_deg)] = "within"
    out[ok & (s > limit_deg)] = "over"
    if err_deg is not None:
        e = np.asarray(err_deg, dtype=float)
        unsure = ok & np.isfinite(e) & (np.abs(s - limit_deg) <= e)
        out[unsure] = "uncertain"
    return out


def _quantile(sorted_values: Any, q: float) -> float:
    import numpy as np

    return float(np.quantile(sorted_values, q, method="inverted_cdf"))


def area_statistics(slope_deg: Any, limit_deg: float, err_deg: Any = None,
                    pixel_area_m2: float = 25.0) -> dict[str, Any]:
    """Distribution of slope over the ground pixels of an ellipse (each pixel counts once)."""
    import numpy as np

    s = np.asarray(slope_deg, dtype=float).ravel()
    known = np.isfinite(s)
    n_all, n = int(s.size), int(known.sum())
    if n == 0:
        return {"pixels": n_all, "pixels_known": 0}
    v = np.sort(s[known])
    out: dict[str, Any] = {
        "pixels": n_all, "pixels_known": n, "area_m2": round(n * pixel_area_m2, 1),
        "slope_deg": {"median": _quantile(v, 0.5), "p90": _quantile(v, 0.9), "p99": _quantile(v, 0.99),
                      "max": float(v[-1])},
        "share_within_limit": float(np.mean(v <= limit_deg)),
        "share_over_limit": float(np.mean(v > limit_deg)),
    }
    if err_deg is not None:
        e = np.asarray(err_deg, dtype=float).ravel()[known]
        cls = verdicts(s[known], limit_deg, e)
        out["uncertainty_known_share"] = float(np.mean(np.isfinite(e)))
        out["share_clearly_within"] = float(np.mean(cls == "within"))
        out["share_uncertain"] = float(np.mean(cls == "uncertain"))
        out["share_clearly_over"] = float(np.mean(cls == "over"))
    thresholds = np.arange(0.0, CDF_MAX_DEG + 1e-9, CDF_STEP_DEG)
    out["cdf"] = {"step_deg": CDF_STEP_DEG, "max_deg": CDF_MAX_DEG,
                  "share_at_or_below": [round(float(x), 4) for x in np.searchsorted(v, thresholds, side="right") / n]}
    return out


def overlay_grid(east_m: Any, north_m: Any, slope_deg: Any, inside: Any, semi_major_m: float,
                 pixel_m: float) -> dict[str, Any]:
    """Steepest slope per cell of a local east/north grid (max-pooled: conservative for display)."""
    import numpy as np

    cell = max(pixel_m, round(2.0 * semi_major_m / OVERLAY_MAX_CELLS, 1))
    n = int(math.ceil(2.0 * semi_major_m / cell))
    e = np.asarray(east_m, dtype=float)[inside]
    nn = np.asarray(north_m, dtype=float)[inside]
    s = np.asarray(slope_deg, dtype=float)[inside]
    ok = np.isfinite(s)
    col = np.clip(np.floor((e[ok] + semi_major_m) / cell).astype(int), 0, n - 1)
    row = np.clip(np.floor((semi_major_m - nn[ok]) / cell).astype(int), 0, n - 1)
    grid = np.full((n, n), -np.inf)
    np.maximum.at(grid, (row, col), s[ok])
    rows = [[None if not math.isfinite(x) else round(float(x), 1) for x in r] for r in grid]
    return {
        "frame": "local east/north metres from the target, the same frame as the ellipse points",
        "cell_m": cell, "cells_east": n, "cells_north": n,
        "first_cell_centre_east_m": -semi_major_m + cell / 2, "first_cell_centre_north_m": semi_major_m - cell / 2,
        "order": "rows from north to south, columns from west to east",
        "value": "steepest pixel slope in the cell (deg); null = outside the ellipse or unknown",
        "max_slope_deg": rows,
    }


def chips(area: dict[str, Any], limit_deg: float, target_deg: float | None) -> list[str]:
    if not area.get("pixels_known"):
        return []
    s = area["slope_deg"]
    out = [f"typical {s['median']:.1f}°", f"steepest {s['max']:.0f}°",
           f"{area['share_within_limit']:.0%} of ellipse ≤ {limit_deg:g}°"]
    if target_deg is not None and math.isfinite(target_deg):
        out.insert(0, f"target {target_deg:.1f}°")
    return out


# --------------------------------------------------------------------------- rasters


@dataclass(frozen=True, slots=True)
class Window:
    """A north-up raster window: values plus where they sit in the raster and in map metres."""
    values: Any            # float64 grid, NaN = unknown
    row_off: int
    col_off: int
    raster_height: int
    raster_width: int
    x_left_m: float        # raster origin (left edge of column 0)
    y_top_m: float         # raster origin (top edge of row 0)
    dx_m: float
    dy_m: float
    grid_signature: tuple[Any, ...]


def read_window(path: Path, x_m: float, y_m: float, half_m: float, units: str = "m") -> Window:
    """Read the pixels covering [x +- half] x [y +- half] plus a margin. Raises SlopeNotAvailable off-tile."""
    try:
        import rasterio
    except ImportError as exc:  # pragma: no cover - dependency listed in requirements
        raise RuntimeError("rasterio is required for the slope layer") from exc
    from lunar_core.terrain import _physical_grid_m, _read_window

    with rasterio.open(path) as ds:
        t = ds.transform
        if t.b != 0 or t.d != 0 or t.a <= 0 or t.e >= 0:
            raise RuntimeError(f"{path.name}: slope needs a north-up raster without rotation")
        dx, dy = float(t.a), float(-t.e)
        col_lo = math.floor((x_m - half_m - t.c) / dx) - MARGIN_PIXELS
        col_hi = math.ceil((x_m + half_m - t.c) / dx) + MARGIN_PIXELS
        row_lo = math.floor((t.f - (y_m + half_m)) / dy) - MARGIN_PIXELS
        row_hi = math.ceil((t.f - (y_m - half_m)) / dy) + MARGIN_PIXELS
        if col_lo < 0 or row_lo < 0 or col_hi > ds.width or row_hi > ds.height:
            raise SlopeNotAvailable(f"the ellipse runs past the edge of the 5 m tile {path.name}")
        raw = _read_window(ds, row_lo, col_lo, row_hi - row_lo, col_hi - col_lo)
        values = _degrees_grid(ds, raw) if units == "deg" else _physical_grid_m(ds, raw, units)
        sig = (str(ds.crs), tuple(t)[:6], ds.width, ds.height)
        return Window(values, row_lo, col_lo, ds.height, ds.width, float(t.c), float(t.f), dx, dy, sig)


def _degrees_grid(ds: Any, raw: Any) -> Any:
    """A degrees layer (slope or slope error) with NoData as NaN; scale/offset applied like heights."""
    from lunar_core.terrain import _physical_grid_m

    return _physical_grid_m(ds, raw, "m")  # unit factor 1: same masking rules, values stay degrees


def pixel_centres(w: Window) -> tuple[Any, Any]:
    import numpy as np

    h, wd = w.values.shape
    xs = w.x_left_m + (w.col_off + np.arange(wd) + 0.5) * w.dx_m
    ys = w.y_top_m - (w.row_off + np.arange(h) + 0.5) * w.dy_m
    return np.meshgrid(xs, ys)


def sample(w: Window, grid: Any, x_m: Any, y_m: Any) -> Any:
    """Bilinear between pixel centres (D-16 rules: unknown if any contributing pixel is unknown)."""
    import numpy as np

    from lunar_core.terrain import _bilinear_from_grid

    cols_f = (np.asarray(x_m, dtype=float) - w.x_left_m) / w.dx_m
    rows_f = (w.y_top_m - np.asarray(y_m, dtype=float)) / w.dy_m
    return _bilinear_from_grid(grid, w.row_off, w.col_off, rows_f, cols_f, w.raster_height, w.raster_width)


# --------------------------------------------------------------------------- assets


@lru_cache(maxsize=16)
def _hash(path: str, mtime_ns: int, size: int) -> str:
    from lunar_core.provenance import sha256_file

    return sha256_file(Path(path))


def _verified(path: Path, sha256: str) -> bool:
    try:
        st = path.stat()
    except OSError:
        return False
    return _hash(str(path), st.st_mtime_ns, st.st_size) == sha256


def load_layers(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or SLOPE_LAYERS
    if not p.is_file():
        return []
    return list(json.loads(p.read_text(encoding="utf-8")).get("layers", []))


def companion(asset_id: str, kind: str, project_root: Path, layers: list[dict[str, Any]]) -> tuple[Path, dict[str, Any]] | None:
    """A staged, hash-verified published layer of this asset, or None."""
    for layer in layers:
        if layer.get("base_asset_id") == asset_id and layer.get("kind") == kind and layer.get("sha256"):
            p = (project_root / layer["relative_path"]).resolve()
            if p.is_relative_to(project_root.resolve()) and _verified(p, layer["sha256"]):
                return p, layer
    return None


def fine_assets(site: dict[str, Any]) -> list[tuple[Any, Path]]:
    """Verified DEM assets of <= 5 m covering this place, finest first (by ID or footprint)."""
    from lunar_core import analysis_service
    from lunar_core.terrain import asset_selected, load_dem_manifest

    manifest = load_dem_manifest(analysis_service.DEM_MANIFEST)
    root = analysis_service.PROJECT_ROOT.resolve()
    out = []
    for a in sorted(manifest.assets, key=lambda a: a.native_resolution_m):
        if a.native_resolution_m > MAX_SLOPE_RESOLUTION_M or "*" in a.site_ids:
            continue
        if not asset_selected(a, site["site_id"], float(site["latitude_deg"]), float(site["longitude_deg"]),
                              manifest.body_radius_m):
            continue
        if not (a.crs_contract_verified and a.vertical_datum_verified):
            continue
        p = (root / a.relative_path).resolve()
        if p.is_relative_to(root) and _verified(p, a.sha256):
            out.append((a, p))
    return out


# --------------------------------------------------------------------------- the answer


def not_available(reason: str, limit_deg: float) -> dict[str, Any]:
    return {"kind": "slope", "status": "not_available", "reason": reason, "label": LABEL,
            "limit_deg": limit_deg, "limit_note": LIMIT_NOTE, "validation": VALIDATION, "chips": []}


def ellipse_slope(site: dict[str, Any], semi_major_m: float, semi_minor_m: float, orientation_deg: float,
                  offsets: list[Any], limit_deg: float = DEFAULT_LIMIT_DEG, *,
                  body_radius_m: float = 1737400.0, include_overlay: bool = True) -> dict[str, Any]:
    """Slope over an ellipse around a site: area statistics, one value per sample offset, an overlay."""
    import numpy as np

    from lunar_core import analysis_service
    from lunar_core.location_scan import offset_point
    from lunar_core.terrain import south_polar_stereo_m

    started = time.monotonic()
    lat0, lon0 = float(site["latitude_deg"]), float(site["longitude_deg"])
    if lat0 > 0:
        return not_available("No 5 m terrain here: slope is only computed on the south-polar 5 m LOLA tiles.", limit_deg)
    assets = fine_assets(site)
    if not assets:
        return not_available("No 5 m terrain covers this place; the 240 m regional map is too coarse for a "
                             "lander-scale slope, so none is given.", limit_deg)
    root = analysis_service.PROJECT_ROOT
    layers = load_layers()
    x0, y0 = south_polar_stereo_m(lat0, lon0, body_radius_m)
    # Map metres = k x ground metres, so the box must grow with k (1.00003 at Site 001, ~1.008 at 80 S).
    half = semi_major_m * float(stereo_scale_factor(x0, y0, body_radius_m)) * 1.001 + 10.0
    last_reason = ""
    for asset, path in assets:
        try:
            dem = read_window(path, x0, y0, half, asset.elevation_units)
        except SlopeNotAvailable as exc:
            last_reason = str(exc)
            continue
        xs, ys = pixel_centres(dem)
        k = stereo_scale_factor(xs, ys, body_radius_m)
        source = "computed"
        published = companion(asset.asset_id, "slope_deg", root, layers) if SLOPE_SOURCE == "published" else None
        if published is not None:
            pw = read_window(published[0], x0, y0, half, units="deg")
            if pw.grid_signature != dem.grid_signature:
                raise RuntimeError(f"{published[1]['layer_id']} is not on the DEM's grid")
            grid, source = pw.values, published[1]["layer_id"]
        else:
            grid = horn_slope_deg(dem.values, dem.dx_m, dem.dy_m, k)
        err_grid, err_layer = None, None
        err = companion(asset.asset_id, "slope_rms_error_deg", root, layers)
        if err is not None:
            ew = read_window(err[0], x0, y0, half, units="deg")
            if ew.grid_signature == dem.grid_signature:
                err_grid, err_layer = ew.values, err[1]
        lat, lon = stereo_to_latlon(xs, ys, body_radius_m)
        east, north = local_east_north(lat0, lon0, lat, lon, body_radius_m)
        inside = inside_ellipse(east, north, semi_major_m, semi_minor_m, orientation_deg)
        area = area_statistics(grid[inside], limit_deg, None if err_grid is None else err_grid[inside],
                               pixel_area_m2=dem.dx_m * dem.dy_m / float(np.mean(k[inside])) ** 2)
        # Sample points: the ellipse's own geodesic offsets -> map -> bilinear between pixel centres.
        pts_xy = [south_polar_stereo_m(*offset_point(lat0, lon0, o, body_radius_m), body_radius_m) for o in offsets]
        px = np.array([p[0] for p in pts_xy], dtype=float)
        py = np.array([p[1] for p in pts_xy], dtype=float)
        s_pts = sample(dem, grid, px, py) if len(offsets) else np.array([])
        e_pts = sample(dem, err_grid, px, py) if (err_grid is not None and len(offsets)) else None
        v_pts = verdicts(s_pts, limit_deg, e_pts)
        points = [{"east_m": o.east_m, "north_m": o.north_m,
                   "slope_deg": None if not math.isfinite(s) else round(float(s), 2),
                   "slope_err_deg": None if e_pts is None or not math.isfinite(e_pts[i]) else round(float(e_pts[i]), 2),
                   "slope_verdict": v_pts[i]}
                  for i, (o, s) in enumerate(zip(offsets, s_pts, strict=True))]
        target = next((p["slope_deg"] for p in points if p["east_m"] == 0.0 and p["north_m"] == 0.0), None)
        payload: dict[str, Any] = {
            "kind": "slope", "status": "ok", "label": LABEL,
            "limit_deg": limit_deg, "limit_note": LIMIT_NOTE,
            "method": {"algorithm": SLOPE_ALGORITHM, "source": source,
                       "stencil": "Horn (1981) 3x3, 10 m between outer pixel centres",
                       "scale_correction": "gradient x k, k = 1 + rho^2/(4R^2) (polar stereographic)",
                       "sampling": "points: bilinear between pixel centres; area: every 5 m pixel whose centre is inside the ellipse"},
            "terrain": {"asset_id": asset.asset_id, "product_id": asset.product_id,
                        "native_resolution_m": asset.native_resolution_m, "sha256": asset.sha256},
            "uncertainty": ({"available": True, "layer_id": err_layer["layer_id"],
                             "meaning": "1-sigma RMS slope error from PGDA's 100 DEM clones; 'uncertain' = within one error of the limit"}
                            if err_layer else {"available": False,
                                               "meaning": "PGDA slope error layer not staged; no 'uncertain' class (typical RMS 1.5–2.5°)"}),
            "area": area,
            "points": points,
            "chips": chips(area, limit_deg, target),
            "validation": VALIDATION,
            "compute_seconds": round(time.monotonic() - started, 2),
        }
        if include_overlay:
            payload["overlay"] = overlay_grid(east, north, grid, inside, semi_major_m, dem.dx_m)
        return payload
    return not_available(last_reason or "No 5 m terrain covers the whole ellipse.", limit_deg)


def run_slope(request: Any) -> dict[str, Any]:
    """``POST /api/slope``: slope over an ellipse at a catalogue site or a clicked point."""
    from lunar_core import analysis_service
    from lunar_core.landing_ellipse import auto_spacing, ellipse_offsets

    site = custom_point.resolve(request.site_id, request.latitude_deg, request.longitude_deg,
                                analysis_service._load_sites())
    b = request.semi_minor_m or request.semi_major_m
    spacing = request.spacing_m or auto_spacing(request.semi_major_m, b)
    offsets = ellipse_offsets(request.semi_major_m, b, request.orientation_deg, spacing)
    out = ellipse_slope(site, request.semi_major_m, b, request.orientation_deg, offsets, request.slope_limit_deg)
    out["site"] = {k: site.get(k) for k in ("site_id", "name", "latitude_deg", "longitude_deg", "origin")}
    out["ellipse"] = {"semi_major_m": request.semi_major_m, "semi_minor_m": b,
                      "orientation_deg": request.orientation_deg, "spacing_m": spacing, "point_count": len(offsets)}
    return out


__all__ = ["DEFAULT_LIMIT_DEG", "LABEL", "SLOPE_ALGORITHM", "SlopeNotAvailable", "area_statistics",
           "central_slope_deg", "ellipse_slope", "horn_slope_deg", "inside_ellipse", "local_east_north",
           "overlay_grid", "run_slope", "stereo_scale_factor", "stereo_to_latlon", "verdicts"]
