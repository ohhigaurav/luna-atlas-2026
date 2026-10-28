"""Hash-verified lunar DEM sampling and topographic horizon construction.

The implementation intentionally refuses an absent asset, non-parseable CRS, or incomplete
ray coverage. It never converts NoData into zero elevation. Raster inputs are kept outside Git;
only the manifest and download instructions belong in the repository.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from lunar_core.horizon import HorizonBin, TerrainHorizon
from lunar_core.provenance import sha256_file


class DEMManifestError(ValueError):
    """DEM manifest or raster integrity contract failed."""


class DEMAsset(BaseModel):
    """A locally staged raster with explicit coverage and geodetic provenance."""
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    asset_id: str = Field(min_length=1, max_length=120)
    relative_path: str = Field(min_length=1, max_length=500)
    site_ids: list[str] = Field(min_length=1)
    source_url: str = Field(min_length=8, max_length=2048)
    product_id: str = Field(min_length=1, max_length=100)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    # Optional for backward compatibility with manually registered local assets; official
    # bootstrap/import tools always populate both fields for auditable source provenance.
    retrieved_utc: datetime | None = None
    size_bytes: int | None = Field(default=None, gt=0)
    native_resolution_m: float = Field(gt=0, le=10000)
    min_range_m: float = Field(ge=0)
    max_range_m: float = Field(gt=0)
    vertical_datum: str = Field(min_length=1, max_length=500)
    crs_contract: str = Field(min_length=1, max_length=1000)
    crs_contract_verified: bool = False
    crs_verification_note: str | None = Field(default=None, max_length=2000)
    vertical_datum_verified: bool = False
    vertical_datum_verification_note: str | None = Field(default=None, max_length=2000)
    elevation_units: Literal["m", "km", "cm", "mm"]
    nodata_policy: Literal["unknown"] = "unknown"

    @model_validator(mode="after")
    def ranges_valid(self) -> DEMAsset:
        if self.retrieved_utc is not None:
            if self.retrieved_utc.tzinfo is None or self.retrieved_utc.utcoffset() is None:
                raise ValueError("retrieved_utc must include a timezone")
            offset = self.retrieved_utc.utcoffset()
            if offset is not None and offset.total_seconds() != 0:
                raise ValueError("retrieved_utc must be UTC (use Z or +00:00)")
        if self.max_range_m <= self.min_range_m:
            raise ValueError("max_range_m must be greater than min_range_m")
        if not self.source_url.startswith(("https://", "http://")):
            raise ValueError("source_url must use HTTP(S)")
        if len(set(self.site_ids)) != len(self.site_ids):
            raise ValueError("site_ids must be unique")
        if self.crs_contract_verified and not (self.crs_verification_note or "").strip():
            raise ValueError("crs_verification_note is required when crs_contract_verified is true")
        if self.vertical_datum_verified and not (self.vertical_datum_verification_note or "").strip():
            raise ValueError("vertical_datum_verification_note is required when vertical_datum_verified is true")
        return self


class DEMManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.0"]
    manifest_state: Literal["not_configured", "configured"]
    body_radius_m: float = Field(gt=1_000_000, lt=2_000_000)
    coordinate_contract: str = Field(min_length=1)
    assets: list[DEMAsset] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def state_consistent(self) -> DEMManifest:
        if self.manifest_state == "not_configured" and self.assets:
            raise ValueError("not_configured DEM manifest must have no assets")
        if self.manifest_state == "configured" and not self.assets:
            raise ValueError("configured DEM manifest must contain at least one asset")
        ids = [a.asset_id for a in self.assets]
        paths = [a.relative_path for a in self.assets]
        if len(ids) != len(set(ids)):
            raise ValueError("DEM asset IDs must be unique")
        if len(paths) != len(set(paths)):
            raise ValueError("DEM asset paths must be unique")
        return self


@dataclass(frozen=True, slots=True)
class VerifiedDEMAsset:
    asset: DEMAsset
    path: Path
    actual_sha256: str


def default_dem_manifest_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "dems" / "manifest.json"


def load_dem_manifest(path: Path | None = None) -> DEMManifest:
    target = path or default_dem_manifest_path()
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        return DEMManifest.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise DEMManifestError(f"Cannot load DEM manifest {target}: {exc}") from exc


def dem_coverage_inventory(
    manifest_path: Path | None = None,
    project_root: Path | None = None,
    *,
    edge_samples: int = 24,
) -> dict[str, Any]:
    """Return auditable DEM footprints for the map without claiming terrain is validated.

    Raster bounds are transformed back to the spherical lunar geographic CRS and returned as
    latitude/longitude vertices for a schematic south-polar map. A footprint is ``verified`` only
    when the file hash, CRS contract and vertical datum have all passed the project's review gate.
    A provisional outline is a visual aid only; it must never unlock terrain analysis.
    """
    if edge_samples < 2 or edge_samples > 128:
        raise ValueError("edge_samples must be between 2 and 128")
    root = (project_root or Path(__file__).resolve().parents[2]).resolve(strict=True)
    target = manifest_path or default_dem_manifest_path()
    try:
        manifest = load_dem_manifest(target)
    except DEMManifestError as exc:
        return {
            "manifest_state": "invalid", "asset_count": 0,
            "verified_coverage_count": 0, "provisional_coverage_count": 0,
            "assets": [], "issues": [str(exc)],
        }

    result: list[dict[str, Any]] = []
    issues: list[str] = []
    if manifest.manifest_state != "configured":
        return {
            "manifest_state": manifest.manifest_state, "body_radius_m": manifest.body_radius_m,
            "asset_count": 0, "verified_coverage_count": 0,
            "provisional_coverage_count": 0, "assets": [],
            "issues": ["No DEM assets are registered. Run the public-input bootstrap after reviewing its output."],
        }

    # Build one reusable target CRS. Product 78/90 are documented in the lunar body-fixed
    # frame; the actual raster CRS metadata is still inspected for each file independently.
    try:
        import numpy as np
        import rasterio
        from pyproj import Transformer
    except ImportError as exc:
        return {
            "manifest_state": manifest.manifest_state, "body_radius_m": manifest.body_radius_m,
            "asset_count": len(manifest.assets), "verified_coverage_count": 0,
            "provisional_coverage_count": 0, "assets": [],
            "issues": [f"Raster coverage rendering requires rasterio, numpy and pyproj: {exc}"],
        }

    target_crs = _source_lunar_crs(manifest.body_radius_m)
    for asset in manifest.assets:
        entry: dict[str, Any] = {
            "asset_id": asset.asset_id,
            "product_id": asset.product_id,
            "source_url": asset.source_url,
            "native_resolution_m": asset.native_resolution_m,
            "min_range_m": asset.min_range_m,
            "max_range_m": asset.max_range_m,
            "site_ids": list(asset.site_ids),
            "crs_contract_verified": asset.crs_contract_verified,
            "vertical_datum_verified": asset.vertical_datum_verified,
            "hash_verified": False,
            "file_present": False,
            "footprint_status": "unavailable",
            "footprint": [],
            "issue": None,
        }
        candidate = root / asset.relative_path
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            entry["issue"] = "Raster file is missing or unreadable."
            result.append(entry)
            continue
        if not resolved.is_relative_to(root) or not resolved.is_file():
            entry["issue"] = "Raster path is outside the project root or is not a file."
            result.append(entry)
            continue
        entry["file_present"] = True
        try:
            actual_hash = sha256_file(resolved)
        except OSError:
            entry["issue"] = "Could not hash raster file."
            result.append(entry)
            continue
        if actual_hash != asset.sha256:
            entry["issue"] = "SHA-256 mismatch; footprint not rendered."
            result.append(entry)
            continue
        entry["hash_verified"] = True

        try:
            with rasterio.open(resolved, "r") as ds:
                if ds.crs is None:
                    raise DEMManifestError("Raster CRS is missing")
                if ds.width <= 0 or ds.height <= 0:
                    raise DEMManifestError("Raster dimensions are invalid")
                bounds = ds.bounds
                # Densify every side before projection. This matters for the large regional
                # stereographic tile; connecting only four transformed corners understates its
                # curved boundary on a polar map.
                fractions = np.linspace(0.0, 1.0, edge_samples, endpoint=False)
                xs: list[float] = []
                ys: list[float] = []
                for f in fractions:
                    xs.append(float(bounds.left + f * (bounds.right - bounds.left)))
                    ys.append(float(bounds.bottom))
                for f in fractions:
                    xs.append(float(bounds.right))
                    ys.append(float(bounds.bottom + f * (bounds.top - bounds.bottom)))
                for f in fractions:
                    xs.append(float(bounds.right - f * (bounds.right - bounds.left)))
                    ys.append(float(bounds.top))
                for f in fractions:
                    xs.append(float(bounds.left))
                    ys.append(float(bounds.top - f * (bounds.top - bounds.bottom)))
                transform = Transformer.from_crs(ds.crs, target_crs, always_xy=True)
                longitudes, latitudes = transform.transform(xs, ys, errcheck=True)
                footprint: list[dict[str, float]] = []
                for longitude, latitude in zip(longitudes, latitudes, strict=True):
                    lon = float(longitude)
                    lat = float(latitude)
                    if not (math.isfinite(lon) and math.isfinite(lat) and -90.000001 <= lat <= 90.000001):
                        raise DEMManifestError("Transformed footprint contains invalid lunar coordinates")
                    footprint.append({
                        "latitude_deg": max(-90.0, min(90.0, lat)),
                        "longitude_deg": (lon + 180.0) % 360.0 - 180.0,
                    })
                entry["footprint"] = footprint
                entry["raster_crs"] = ds.crs.to_string()
                entry["raster_width"] = ds.width
                entry["raster_height"] = ds.height
                entry["raster_bounds"] = [float(bounds.left), float(bounds.bottom), float(bounds.right), float(bounds.top)]
                entry["footprint_status"] = (
                    "verified" if asset.crs_contract_verified and asset.vertical_datum_verified else "provisional"
                )
                if entry["footprint_status"] == "provisional":
                    entry["issue"] = "Outline is provisional: CRS and/or vertical datum review is still open."
        except Exception as exc:
            entry["issue"] = f"Could not render footprint: {type(exc).__name__}: {exc}"
            entry["footprint"] = []
        result.append(entry)

    verified_count = sum(item["footprint_status"] == "verified" for item in result)
    provisional_count = sum(item["footprint_status"] == "provisional" for item in result)
    return {
        "manifest_state": manifest.manifest_state,
        "body_radius_m": manifest.body_radius_m,
        "asset_count": len(manifest.assets),
        "verified_coverage_count": verified_count,
        "provisional_coverage_count": provisional_count,
        "assets": result,
        "issues": issues,
        "warning": "Footprints show raster extents, not safe landing areas, height quality, per-site radial completeness, or scientific acceptance.",
    }


def preflight_dem_assets(
    manifest_path: Path, project_root: Path, site_id: str
) -> tuple[DEMManifest, tuple[VerifiedDEMAsset, ...]]:
    """Verify every asset selected for this site before opening any raster."""
    manifest = load_dem_manifest(manifest_path)
    if manifest.manifest_state != "configured":
        raise DEMManifestError("DEM manifest is not configured; terrain-aware analysis is disabled")
    root = project_root.resolve(strict=True)
    chosen: list[VerifiedDEMAsset] = []
    for asset in manifest.assets:
        if site_id not in asset.site_ids and "*" not in asset.site_ids:
            continue
        candidate = root / asset.relative_path
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise DEMManifestError(f"DEM asset {asset.asset_id} not found: {asset.relative_path}") from exc
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise DEMManifestError(f"DEM asset {asset.asset_id} is not a file under project root")
        if not asset.crs_contract_verified:
            raise DEMManifestError(
                f"DEM asset {asset.asset_id} CRS contract is unverified; inspect its projection, "
                "axis convention, lunar radius and coordinate transform, then record a verification note"
            )
        if not asset.vertical_datum_verified:
            raise DEMManifestError(
                f"DEM asset {asset.asset_id} vertical datum is unverified; establish compatibility "
                "between DEM elevation, reference radius and observer-point model before use"
            )
        actual_hash = sha256_file(resolved)
        if actual_hash != asset.sha256:
            raise DEMManifestError(
                f"DEM asset {asset.asset_id} SHA-256 mismatch: expected {asset.sha256}, got {actual_hash}"
            )
        chosen.append(VerifiedDEMAsset(asset, resolved, actual_hash))
    if not chosen:
        raise DEMManifestError(f"No DEM assets are configured for site {site_id}")
    return manifest, tuple(sorted(chosen, key=lambda item: item.asset.native_resolution_m))


def _ray_latlon_grid(
    latitude_deg: float,
    longitude_deg: float,
    azimuths_deg: Any,
    distances_m: Any,
    body_radius_m: float,
) -> tuple[Any, Any]:
    """Spherical forward geodesic for paired azimuth/distance arrays (azimuth clockwise from north)."""
    import numpy as np

    lat1 = math.radians(latitude_deg)
    lon1 = math.radians(longitude_deg)
    bearing = np.radians(np.asarray(azimuths_deg, dtype=float))
    delta = np.asarray(distances_m, dtype=float) / body_radius_m
    sin_lat2 = math.sin(lat1) * np.cos(delta) + math.cos(lat1) * np.sin(delta) * np.cos(bearing)
    lat2 = np.arcsin(np.clip(sin_lat2, -1.0, 1.0))
    lon2 = lon1 + np.arctan2(
        np.sin(bearing) * np.sin(delta) * math.cos(lat1),
        np.cos(delta) - math.sin(lat1) * np.sin(lat2),
    )
    return np.degrees(lat2), (np.degrees(lon2) + 180.0) % 360.0 - 180.0


def _source_lunar_crs(body_radius_m: float) -> Any:
    try:
        from pyproj import CRS
    except ImportError as exc:  # pragma: no cover - dependency listed in project extras
        raise DEMManifestError("pyproj is required for terrain analysis; install geo dependencies") from exc
    return CRS.from_proj4(f"+proj=longlat +R={body_radius_m:.3f} +no_defs +type=crs")


def json_safe_nodata(value: Any) -> float | str | None:
    """Raster NoData for JSON output: NaN (common in LOLA GeoTIFFs) becomes the string "NaN"."""
    if value is None:
        return None
    number = float(value)
    return "NaN" if math.isnan(number) else number


_ELEVATION_TO_METRES = {"m": 1.0, "km": 1000.0, "cm": 0.01, "mm": 0.001}


def _physical_elevation_array_m(dataset: Any, samples: Any, units: str) -> Any:
    """Vectorized equivalent of ``_physical_elevation_m`` for a Rasterio sample batch.

    Returns metres with invalid, masked, non-finite and NoData samples as NaN. NoData is tested
    against raw stored values before scale/offset and unit conversion, preserving GDAL semantics.
    """
    import numpy as np

    # numpy.ma has no type information in the pinned NumPy stubs; use it through Any.
    ma: Any = np.ma

    if units not in _ELEVATION_TO_METRES:
        raise DEMManifestError(f"Unsupported DEM elevation units: {units!r}")
    try:
        batch = ma.asarray(samples)
        if batch.ndim != 2 or batch.shape[1] < 1:
            raise ValueError("expected a 2-D batch of raster band samples")
        raw_sample = batch[:, 0]
        raw = np.asarray(ma.getdata(raw_sample), dtype=np.float64)
        invalid = np.asarray(ma.getmaskarray(raw_sample), dtype=bool).copy() | ~np.isfinite(raw)
    except (TypeError, ValueError) as exc:
        raise DEMManifestError(f"Invalid DEM sample batch: {exc}") from exc

    nodata = dataset.nodata
    if nodata is not None:
        invalid |= np.isclose(raw, float(nodata), rtol=0.0, atol=1e-12)
    scales = getattr(dataset, "scales", (1.0,))
    offsets = getattr(dataset, "offsets", (0.0,))
    scale = float(scales[0] if scales else 1.0)
    offset = float(offsets[0] if offsets else 0.0)
    if not math.isfinite(scale) or not math.isfinite(offset):
        raise DEMManifestError("DEM band scale/offset metadata must be finite")
    physical = (raw * scale + offset) * _ELEVATION_TO_METRES[units]
    invalid |= ~np.isfinite(physical)
    physical[invalid] = np.nan
    return physical


# Upper bound on pixels read in one window (~128 MB once converted to float64 metres). Larger
# point sets are split spatially into several windows, so this caps memory, not coverage.
MAX_WINDOW_PIXELS = 16_000_000


def _physical_grid_m(dataset: Any, raw: Any, units: str) -> Any:
    """Convert a masked raster window to metres (float64), NoData/masked/non-finite -> NaN."""
    import numpy as np

    # numpy.ma has no type information in the pinned NumPy stubs; use it through Any.
    ma: Any = np.ma

    if units not in _ELEVATION_TO_METRES:
        raise DEMManifestError(f"Unsupported DEM elevation units: {units!r}")
    data = np.asarray(ma.getdata(raw), dtype=np.float64)
    invalid = np.asarray(ma.getmaskarray(raw), dtype=bool) | ~np.isfinite(data)
    nodata = dataset.nodata
    if nodata is not None:
        invalid |= np.isclose(data, float(nodata), rtol=0.0, atol=1e-12)
    scales = getattr(dataset, "scales", (1.0,))
    offsets = getattr(dataset, "offsets", (0.0,))
    scale = float(scales[0] if scales else 1.0)
    offset = float(offsets[0] if offsets else 0.0)
    if not math.isfinite(scale) or not math.isfinite(offset):
        raise DEMManifestError("DEM band scale/offset metadata must be finite")
    physical = (data * scale + offset) * _ELEVATION_TO_METRES[units]
    invalid |= ~np.isfinite(physical)
    physical[invalid] = np.nan
    return physical


def _read_window(dataset: Any, row_off: int, col_off: int, height: int, width: int) -> Any:
    """Read band 1 for a pixel window as a masked array (isolated so tests can substitute it)."""
    from rasterio.windows import Window

    return dataset.read(1, window=Window(col_off, row_off, width, height), masked=True)


def _bilinear_from_grid(
    grid: Any, row_off: int, col_off: int, rows_f: Any, cols_f: Any,
    raster_height: int, raster_width: int,
) -> Any:
    """Bilinear interpolation between pixel centres; NaN where the answer is unknown.

    ``rows_f``/``cols_f`` are fractional raster coordinates of pixel *edges* (pixel i spans
    [i, i+1)), i.e. what the inverse affine transform returns. A point outside the raster footprint
    is unknown. Inside the footprint, the outermost half pixel is clamped to the edge pixel (the
    footprint semantics of nearest-neighbour sampling). Any contributing neighbour with a non-zero
    weight that is NoData makes the result unknown; NoData is never averaged away.
    """
    import numpy as np

    rows_f = np.asarray(rows_f, dtype=float)
    cols_f = np.asarray(cols_f, dtype=float)
    out = np.full(rows_f.shape, np.nan, dtype=float)
    inside = (
        np.isfinite(rows_f) & np.isfinite(cols_f)
        & (cols_f >= 0.0) & (cols_f < raster_width) & (rows_f >= 0.0) & (rows_f < raster_height)
    )
    if not np.any(inside):
        return out
    grid_h, grid_w = grid.shape
    c = np.clip(cols_f[inside] - 0.5, 0.0, raster_width - 1.0) - col_off
    r = np.clip(rows_f[inside] - 0.5, 0.0, raster_height - 1.0) - row_off
    c0 = np.floor(c).astype(int)
    r0 = np.floor(r).astype(int)
    if c0.min() < 0 or r0.min() < 0 or c0.max() >= grid_w or r0.max() >= grid_h:
        raise DEMManifestError("internal error: bilinear sample falls outside the read window")
    c1 = np.minimum(c0 + 1, grid_w - 1)
    r1 = np.minimum(r0 + 1, grid_h - 1)
    fc = c - c0
    fr = r - r0
    total = np.zeros(c.shape, dtype=float)
    unknown = np.zeros(c.shape, dtype=bool)
    for rr, cc, weight in (
        (r0, c0, (1.0 - fr) * (1.0 - fc)), (r0, c1, (1.0 - fr) * fc),
        (r1, c0, fr * (1.0 - fc)), (r1, c1, fr * fc),
    ):
        value = grid[rr, cc]
        used = weight > 0.0
        unknown |= used & ~np.isfinite(value)
        total += np.where(used & np.isfinite(value), value * weight, 0.0)
    total[unknown] = np.nan
    out[inside] = total
    return out


def _sample_dataset_bilinear(dataset: Any, xs: Any, ys: Any, units: str) -> Any:
    """Bilinear heights (metres) at projected x/y.

    Reads the bounding window of the points; if that window exceeds ``MAX_WINDOW_PIXELS`` the
    point set is split at its median along the longer side and each half is read separately.
    Rays fill only a small part of their bounding box, so splitting also cuts the pixels read.
    """
    import numpy as np

    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    # Apply the inverse affine coefficients directly: affine 3.x deprecates `*` on tuples and
    # `@` is not available in older affine releases.
    inv = ~dataset.transform
    cols_f = inv.a * xs + inv.b * ys + inv.c
    rows_f = inv.d * xs + inv.e * ys + inv.f
    cols_f = np.asarray(cols_f, dtype=float)
    rows_f = np.asarray(rows_f, dtype=float)
    height, width = int(dataset.height), int(dataset.width)
    out = np.full(xs.shape, np.nan, dtype=float)
    inside = (
        np.isfinite(rows_f) & np.isfinite(cols_f)
        & (cols_f >= 0.0) & (cols_f < width) & (rows_f >= 0.0) & (rows_f < height)
    )
    if not np.any(inside):
        return out
    flat_rows, flat_cols = rows_f.ravel(), cols_f.ravel()
    flat_out = out.ravel()
    centre_c = np.clip(flat_cols - 0.5, 0.0, width - 1.0)
    centre_r = np.clip(flat_rows - 0.5, 0.0, height - 1.0)

    pending = [np.flatnonzero(inside.ravel())]
    while pending:
        idx = pending.pop()
        c, r = centre_c[idx], centre_r[idx]
        col0, col1 = int(np.floor(c.min())), min(int(np.floor(c.max())) + 1, width - 1)
        row0, row1 = int(np.floor(r.min())), min(int(np.floor(r.max())) + 1, height - 1)
        win_h, win_w = row1 - row0 + 1, col1 - col0 + 1
        if win_h * win_w > MAX_WINDOW_PIXELS and idx.size > 1:
            key = c if win_w >= win_h else r
            order = np.argsort(key, kind="stable")
            half = idx.size // 2
            pending.extend((idx[order[:half]], idx[order[half:]]))
            continue
        grid = _physical_grid_m(dataset, _read_window(dataset, row0, col0, win_h, win_w), units)
        flat_out[idx] = _bilinear_from_grid(
            grid, row0, col0, flat_rows[idx], flat_cols[idx], height, width,
        )
    return out


def build_horizon_from_dem_assets(
    site_id: str,
    latitude_deg: float,
    longitude_deg: float,
    *,
    observer_height_m: float,
    reference_radius_m: float,
    max_range_m: float = 200_000.0,
    azimuth_step_deg: float = 0.5,
    near_range_m: float = 8_000.0,
    near_step_m: float = 5.0,
    far_step_m: float = 240.0,
    manifest_path: Path | None = None,
    project_root: Path | None = None,
) -> tuple[TerrainHorizon, float, dict[str, Any]]:
    """Build a terrain horizon using the finest configured asset at each radial sample.

    The function is intentionally explicit about resolution/range selection. Assets are sampled
    in source coordinates with Rasterio's base dataset values; this function never requests an
    overview. Missing/out-of-coverage values become incomplete ray flags.
    """
    if not all(math.isfinite(v) for v in (
        latitude_deg, longitude_deg, observer_height_m, reference_radius_m,
        max_range_m, azimuth_step_deg, near_range_m, near_step_m, far_step_m,
    )):
        raise ValueError("terrain parameters must be finite")
    if observer_height_m < 0 or reference_radius_m <= 0 or max_range_m <= 0:
        raise ValueError("invalid observer height, reference radius or max range")
    if not (0 < azimuth_step_deg <= 10) or near_range_m <= 0 or near_step_m <= 0 or far_step_m <= 0:
        raise ValueError("invalid terrain sampling step")
    if near_range_m >= max_range_m:
        raise ValueError("near_range_m must be less than max_range_m")

    import numpy as np
    import rasterio
    from pyproj import Transformer

    root = project_root or Path(__file__).resolve().parents[2]
    dem_manifest_path = manifest_path or default_dem_manifest_path()
    manifest, verified = preflight_dem_assets(dem_manifest_path, root, site_id)
    source_crs = _source_lunar_crs(manifest.body_radius_m)

    with ExitStack() as stack:
        open_assets: list[tuple[VerifiedDEMAsset, Any, Any]] = []
        for item in verified:
            ds = stack.enter_context(rasterio.open(item.path, "r"))
            if ds.crs is None:
                raise DEMManifestError(f"DEM {item.asset.asset_id} has no CRS")
            if ds.count < 1:
                raise DEMManifestError(f"DEM {item.asset.asset_id} has no raster band")
            transformer = Transformer.from_crs(source_crs, ds.crs, always_xy=True)
            # Metadata is recorded into the run manifest; CRS validity is not proof of datum correctness.
            open_assets.append((item, ds, transformer))

        # Ground elevation at the observer from the finest DEM with a valid value there.
        origin_lat, origin_lon = latitude_deg, ((longitude_deg + 180) % 360) - 180
        site_ground_elevation: float | None = None
        for item, ds, transformer in open_assets:
            if not (item.asset.min_range_m <= 0 <= item.asset.max_range_m):
                continue
            x0, y0 = transformer.transform(float(origin_lon), float(origin_lat))
            x, y = np.array([float(x0)]), np.array([float(y0)])
            sampled = _sample_dataset_bilinear(ds, x, y, item.asset.elevation_units)
            if np.isfinite(sampled[0]):
                site_ground_elevation = float(sampled[0])
                break
        if site_ground_elevation is None:
            raise DEMManifestError(
                f"No valid DEM elevation at observer point for {site_id}; check site coordinate, CRS and coverage"
            )

        observer_radius_m = reference_radius_m + site_ground_elevation + observer_height_m
        if observer_radius_m <= 0:
            raise DEMManifestError("Observer radius is non-positive after applying DEM ground height")

        count = int(round(360.0 / azimuth_step_deg))
        if not math.isclose(count * azimuth_step_deg, 360.0, abs_tol=1e-8):
            raise ValueError("azimuth_step_deg must divide 360 exactly")

        # Adapt radial sampling to the native resolution actually available at each range.
        # A 5 m requested step is suitable for Product 78's 5 m tiles, but sampling Product 90's
        # 240 m raster every 5 m only multiplies I/O and does not create 5 m information. Include
        # each asset range boundary so high-resolution near-field sampling is retained where it exists.
        boundaries = sorted({
            0.0, near_range_m, max_range_m,
            *(max(0.0, min(max_range_m, item.asset.min_range_m)) for item, _ds, _tr in open_assets),
            *(max(0.0, min(max_range_m, item.asset.max_range_m)) for item, _ds, _tr in open_assets),
        })
        distance_chunks: list[Any] = []
        sampling_segments: list[dict[str, float | None]] = []
        for segment_start, segment_end in zip(boundaries[:-1], boundaries[1:], strict=True):
            if segment_end <= segment_start:
                continue
            midpoint = (segment_start + segment_end) / 2.0
            base_step = near_step_m if midpoint < near_range_m else far_step_m
            eligible_resolutions = [
                item.asset.native_resolution_m
                for item, _ds, _tr in open_assets
                if item.asset.min_range_m <= midpoint <= item.asset.max_range_m
            ]
            native_resolution = min(eligible_resolutions) if eligible_resolutions else None
            step = max(base_step, native_resolution) if native_resolution is not None else base_step
            chunk = np.arange(segment_start, segment_end, step, dtype=float)
            distance_chunks.append(chunk)
            sampling_segments.append({
                "start_m": float(segment_start), "end_m": float(segment_end),
                "base_step_m": float(base_step), "native_resolution_m": (
                    float(native_resolution) if native_resolution is not None else None
                ), "effective_step_m": float(step),
            })
        distance_chunks.append(np.array([max_range_m], dtype=float))
        distances = np.unique(np.concatenate(distance_chunks))
        azimuths = np.arange(count, dtype=float) * azimuth_step_deg

        # One (azimuth x distance) grid for the whole horizon. Assets arrive sorted finest to
        # coarsest; each asset is offered only the samples that are still unknown, so a NoData or
        # out-of-footprint pixel in a fine tile can fall back to a valid coarser DEM, while a value
        # unknown in every eligible asset stays NaN and makes its azimuth incomplete.
        heights = np.full((count, distances.size), np.nan, dtype=float)
        chosen = np.full((count, distances.size), -1, dtype=int)
        asset_sample_counts = {item.asset.asset_id: 0 for item, _ds, _tr in open_assets}
        fallback_sample_count = 0
        for asset_index, (item, ds, transformer) in enumerate(open_assets):
            asset = item.asset
            in_range = (distances >= asset.min_range_m) & (distances <= min(asset.max_range_m, max_range_m))
            if not np.any(in_range):
                continue
            eligible = in_range[None, :] & (chosen < 0)
            az_idx, dist_idx = np.nonzero(eligible)
            if az_idx.size == 0:
                continue
            lats, lons = _ray_latlon_grid(
                latitude_deg, longitude_deg, azimuths[az_idx], distances[dist_idx], manifest.body_radius_m
            )
            xs, ys = transformer.transform(lons, lats)
            sampled = _sample_dataset_bilinear(ds, xs, ys, asset.elevation_units)
            known_here = np.isfinite(sampled)
            heights[az_idx[known_here], dist_idx[known_here]] = sampled[known_here]
            chosen[az_idx[known_here], dist_idx[known_here]] = asset_index
            asset_sample_counts[asset.asset_id] += int(known_here.sum())
            if asset_index > 0 and np.any(known_here):
                finer_eligible = np.zeros(int(known_here.sum()), dtype=bool)
                accepted_distances = distances[dist_idx[known_here]]
                for finer_item, _fds, _ftr in open_assets[:asset_index]:
                    finer_eligible |= (
                        (accepted_distances >= finer_item.asset.min_range_m)
                        & (accepted_distances <= min(finer_item.asset.max_range_m, max_range_m))
                    )
                fallback_sample_count += int(finer_eligible.sum())

        known = np.isfinite(heights)
        radii = reference_radius_m + np.where(known, heights, 0.0)
        angles = distances[None, :] / reference_radius_m
        apparent = np.arctan2(radii * np.cos(angles) - observer_radius_m, radii * np.sin(angles))
        apparent = np.where(known, apparent, -np.inf)
        reaches_origin = math.isclose(float(distances[0]), 0.0)
        reaches_range = math.isclose(float(distances[-1]), max_range_m)
        bins: list[HorizonBin] = []
        for az_index in range(count):
            nodata_count = int((~known[az_index]).sum())
            if not np.any(known[az_index]):
                bins.append(HorizonBin(
                    azimuth_deg=float(azimuths[az_index]), elevation_rad=None,
                    controlling_distance_m=None, coverage_status="none",
                    sample_count=int(distances.size), nodata_count=nodata_count,
                ))
                continue
            maximum_index = int(np.argmax(apparent[az_index]))
            complete = nodata_count == 0 and reaches_origin and reaches_range
            bins.append(HorizonBin(
                azimuth_deg=float(azimuths[az_index]),
                elevation_rad=float(apparent[az_index, maximum_index]),
                controlling_distance_m=float(distances[maximum_index]),
                coverage_status="complete" if complete else "incomplete",
                sample_count=int(distances.size),
                nodata_count=nodata_count,
            ))

        # Captured while every dataset is still open.
        asset_metadata = [
            {
                "asset_id": item.asset.asset_id,
                "path": item.asset.relative_path,
                "sha256": item.actual_sha256,
                "source_url": item.asset.source_url,
                "product_id": item.asset.product_id,
                "native_resolution_m": item.asset.native_resolution_m,
                "min_range_m": item.asset.min_range_m,
                "max_range_m": item.asset.max_range_m,
                "raster_crs": ds.crs.to_string(),
                "raster_width": ds.width,
                "raster_height": ds.height,
                "raster_nodata": json_safe_nodata(ds.nodata),
                "raster_scales": tuple(float(v) for v in ds.scales),
                "raster_offsets": tuple(float(v) for v in ds.offsets),
                "elevation_units": item.asset.elevation_units,
                "transform": tuple(ds.transform)[:6],
                "samples_used_total": asset_sample_counts.get(item.asset.asset_id, 0),
            }
            for item, ds, _transformer in open_assets
        ]

    horizon = TerrainHorizon(
        reference_radius_m=reference_radius_m,
        observer_radius_m=observer_radius_m,
        observer_height_m=observer_height_m,
        max_range_m=max_range_m,
        bins=tuple(bins),
    )
    metadata = {
        "manifest_sha256": sha256_file(dem_manifest_path),
        "site_ground_elevation_m": site_ground_elevation,
        "assets": asset_metadata,
        "interpolation": (
            "bilinear between pixel centres; unknown if any contributing pixel is NoData or the "
            "point lies outside the raster footprint"
        ),
        "azimuth_step_deg": azimuth_step_deg,
        "near_range_m": near_range_m,
        "near_step_m_requested": near_step_m,
        "far_step_m_requested": far_step_m,
        "radial_sampling_segments": sampling_segments,
        "radial_sample_count": int(len(distances)),
        "asset_sample_counts_total": asset_sample_counts,
        "fallback_sample_count_total": fallback_sample_count,
        "missing_sample_count_total": int(sum(bin_.nodata_count for bin_ in bins)),
        "max_range_m": max_range_m,
    }
    return horizon, site_ground_elevation, metadata


HORIZON_ALGORITHM_VERSION = "terrain-horizon-2.0-windowed-bilinear-nested-fallback"


def _horizon_cache_key(
    *, site_id: str, latitude_deg: float, longitude_deg: float, observer_height_m: float,
    reference_radius_m: float, max_range_m: float, azimuth_step_deg: float,
    near_range_m: float, near_step_m: float, far_step_m: float,
    manifest_sha256: str, asset_hashes: list[tuple[str, str]],
) -> str:
    contract = {
        "algorithm": HORIZON_ALGORITHM_VERSION,
        "site_id": site_id,
        "latitude_deg": latitude_deg,
        "longitude_deg": longitude_deg,
        "observer_height_m": observer_height_m,
        "reference_radius_m": reference_radius_m,
        "max_range_m": max_range_m,
        "azimuth_step_deg": azimuth_step_deg,
        "near_range_m": near_range_m,
        "near_step_m": near_step_m,
        "far_step_m": far_step_m,
        "manifest_sha256": manifest_sha256,
        "asset_hashes": sorted(asset_hashes),
    }
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_cached_horizon_from_dem_assets(
    site_id: str,
    latitude_deg: float,
    longitude_deg: float,
    *,
    observer_height_m: float,
    reference_radius_m: float,
    max_range_m: float = 200_000.0,
    azimuth_step_deg: float = 0.5,
    near_range_m: float = 8_000.0,
    near_step_m: float = 5.0,
    far_step_m: float = 240.0,
    manifest_path: Path | None = None,
    project_root: Path | None = None,
) -> tuple[TerrainHorizon, float, dict[str, Any]]:
    """Hash-verified, content-addressed horizon cache.

    The DEM manifest and each selected raster are hashed on every invocation before a cached
    horizon can be reused. A cache file cannot override the declared settings or input hashes.
    """
    root = (project_root or Path(__file__).resolve().parents[2]).resolve(strict=True)
    manifest_file = manifest_path or default_dem_manifest_path()
    manifest, verified = preflight_dem_assets(manifest_file, root, site_id)
    manifest_hash = sha256_file(manifest_file)
    cache_key = _horizon_cache_key(
        site_id=site_id, latitude_deg=latitude_deg, longitude_deg=longitude_deg,
        observer_height_m=observer_height_m, reference_radius_m=reference_radius_m,
        max_range_m=max_range_m, azimuth_step_deg=azimuth_step_deg,
        near_range_m=near_range_m, near_step_m=near_step_m, far_step_m=far_step_m,
        manifest_sha256=manifest_hash,
        asset_hashes=[(item.asset.asset_id, item.actual_sha256) for item in verified],
    )
    cache_dir = root / "data" / "cache" / "horizons"
    cache_file = cache_dir / f"{cache_key}.json"
    if cache_file.is_file():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if cached.get("cache_key") != cache_key or cached.get("algorithm_version") != HORIZON_ALGORITHM_VERSION:
                raise DEMManifestError("horizon cache key/algorithm does not match current inputs")
            raw = cached["horizon"]
            bins = tuple(HorizonBin(**item) for item in raw["bins"])
            horizon = TerrainHorizon(
                reference_radius_m=float(raw["reference_radius_m"]),
                observer_radius_m=float(raw["observer_radius_m"]),
                observer_height_m=float(raw["observer_height_m"]),
                max_range_m=float(raw["max_range_m"]), bins=bins,
            )
            metadata = dict(cached["metadata"])
            metadata.update({"cache_hit": True, "cache_key": cache_key, "cache_algorithm_version": HORIZON_ALGORITHM_VERSION})
            return horizon, float(cached["site_ground_elevation_m"]), metadata
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, DEMManifestError):
            # A corrupted/obsolete cache is discarded and recalculated, never consumed silently.
            try:
                cache_file.unlink(missing_ok=True)
            except OSError:
                pass

    horizon, ground_elevation, metadata = build_horizon_from_dem_assets(
        site_id=site_id, latitude_deg=latitude_deg, longitude_deg=longitude_deg,
        observer_height_m=observer_height_m, reference_radius_m=reference_radius_m,
        max_range_m=max_range_m, azimuth_step_deg=azimuth_step_deg,
        near_range_m=near_range_m, near_step_m=near_step_m, far_step_m=far_step_m,
        manifest_path=manifest_file, project_root=root,
    )
    metadata.update({"cache_hit": False, "cache_key": cache_key, "cache_algorithm_version": HORIZON_ALGORITHM_VERSION})
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_payload = {
        "cache_key": cache_key, "algorithm_version": HORIZON_ALGORITHM_VERSION,
        "site_ground_elevation_m": ground_elevation, "metadata": metadata,
        "horizon": {
            "reference_radius_m": horizon.reference_radius_m,
            "observer_radius_m": horizon.observer_radius_m,
            "observer_height_m": horizon.observer_height_m,
            "max_range_m": horizon.max_range_m,
            "bins": [
                {"azimuth_deg": item.azimuth_deg, "elevation_rad": item.elevation_rad,
                 "controlling_distance_m": item.controlling_distance_m, "coverage_status": item.coverage_status,
                 "sample_count": item.sample_count, "nodata_count": item.nodata_count}
                for item in horizon.bins
            ],
        },
    }
    fd, temp_name = tempfile.mkstemp(prefix=f".{cache_key}.", suffix=".tmp", dir=cache_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(cache_payload, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, cache_file)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return horizon, ground_elevation, metadata
