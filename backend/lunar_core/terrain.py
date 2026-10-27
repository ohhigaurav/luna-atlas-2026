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
from datetime import datetime
from dataclasses import dataclass
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
    def ranges_valid(self) -> "DEMAsset":
        if self.retrieved_utc is not None:
            if self.retrieved_utc.tzinfo is None or self.retrieved_utc.utcoffset() is None:
                raise ValueError("retrieved_utc must include a timezone")
            if self.retrieved_utc.utcoffset().total_seconds() != 0:
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
    def state_consistent(self) -> "DEMManifest":
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
                for longitude, latitude in zip(longitudes, latitudes):
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


def _ray_latlon(
    latitude_deg: float,
    longitude_deg: float,
    azimuth_deg: float,
    distance_m: float,
    body_radius_m: float,
) -> tuple[float, float]:
    """Spherical forward-geodesic point; azimuth is clockwise from local north."""
    lat1 = math.radians(latitude_deg)
    lon1 = math.radians(longitude_deg)
    bearing = math.radians(azimuth_deg)
    delta = distance_m / body_radius_m
    sin_lat2 = math.sin(lat1) * math.cos(delta) + math.cos(lat1) * math.sin(delta) * math.cos(bearing)
    lat2 = math.asin(max(-1.0, min(1.0, sin_lat2)))
    lon2 = lon1 + math.atan2(
        math.sin(bearing) * math.sin(delta) * math.cos(lat1),
        math.cos(delta) - math.sin(lat1) * math.sin(lat2),
    )
    lon2_deg = (math.degrees(lon2) + 180.0) % 360.0 - 180.0
    return math.degrees(lat2), lon2_deg


def _ray_latlon_array(
    latitude_deg: float,
    longitude_deg: float,
    azimuth_deg: float,
    distances_m: Any,
    body_radius_m: float,
) -> tuple[Any, Any]:
    """Vectorised spherical forward-geodesic for a complete set of ray samples."""
    import numpy as np

    lat1 = math.radians(latitude_deg)
    lon1 = math.radians(longitude_deg)
    bearing = math.radians(azimuth_deg)
    delta = np.asarray(distances_m, dtype=float) / body_radius_m
    sin_lat2 = math.sin(lat1) * np.cos(delta) + math.cos(lat1) * np.sin(delta) * math.cos(bearing)
    lat2 = np.arcsin(np.clip(sin_lat2, -1.0, 1.0))
    lon2 = lon1 + np.arctan2(
        math.sin(bearing) * np.sin(delta) * math.cos(lat1),
        np.cos(delta) - math.sin(lat1) * np.sin(lat2),
    )
    lon2_deg = (np.degrees(lon2) + 180.0) % 360.0 - 180.0
    return np.degrees(lat2), lon2_deg


def _source_lunar_crs(body_radius_m: float) -> Any:
    try:
        from pyproj import CRS
    except ImportError as exc:  # pragma: no cover - dependency listed in project extras
        raise DEMManifestError("pyproj is required for terrain analysis; install geo dependencies") from exc
    return CRS.from_proj4(f"+proj=longlat +R={body_radius_m:.3f} +no_defs +type=crs")


_ELEVATION_TO_METRES = {"m": 1.0, "km": 1000.0, "cm": 0.01, "mm": 0.001}


def _physical_elevation_m(dataset: Any, sample: Any, units: str) -> float | None:
    """Convert a raw raster sample to metres, preserving NoData semantics.

    GeoTIFF band scale/offset apply to encoded raster values. NoData must be checked on the
    raw sample *before* applying those transforms; units are explicit in the DEM manifest.
    """
    import numpy as np

    if units not in _ELEVATION_TO_METRES:
        raise DEMManifestError(f"Unsupported DEM elevation units: {units!r}")
    if np.ma.is_masked(sample):
        return None
    try:
        raw_value = float(sample)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(raw_value):
        return None
    nodata = dataset.nodata
    if nodata is not None and math.isclose(raw_value, float(nodata), rel_tol=0.0, abs_tol=1e-12):
        return None

    scales = getattr(dataset, "scales", (1.0,))
    offsets = getattr(dataset, "offsets", (0.0,))
    scale = float(scales[0] if scales else 1.0)
    offset = float(offsets[0] if offsets else 0.0)
    if not math.isfinite(scale) or not math.isfinite(offset):
        raise DEMManifestError("DEM band scale/offset metadata must be finite")
    physical = (raw_value * scale + offset) * _ELEVATION_TO_METRES[units]
    return physical if math.isfinite(physical) else None


def _sample_one(dataset: Any, x: float, y: float, units: str) -> float | None:
    try:
        sample = next(dataset.sample([(x, y)], masked=True))[0]
    except Exception as exc:
        raise DEMManifestError(f"Raster sample failed: {exc}") from exc
    return _physical_elevation_m(dataset, sample, units)


def _physical_elevation_array_m(dataset: Any, samples: Any, units: str) -> Any:
    """Vectorized equivalent of ``_physical_elevation_m`` for a Rasterio sample batch.

    Returns metres with invalid, masked, non-finite and NoData samples as NaN. NoData is tested
    against raw stored values before scale/offset and unit conversion, preserving GDAL semantics.
    """
    import numpy as np

    if units not in _ELEVATION_TO_METRES:
        raise DEMManifestError(f"Unsupported DEM elevation units: {units!r}")
    try:
        batch = np.ma.asarray(samples)
        if batch.ndim != 2 or batch.shape[1] < 1:
            raise ValueError("expected a 2-D batch of raster band samples")
        raw_sample = batch[:, 0]
        raw = np.asarray(np.ma.getdata(raw_sample), dtype=float)
        invalid = np.ma.getmaskarray(raw_sample).copy() | ~np.isfinite(raw)
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

    bins: list[HorizonBin] = []
    site_ground_elevation: float | None = None
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

        # Read actual ground elevation at the observer from the finest DEM covering the origin.
        origin_lat, origin_lon = latitude_deg, ((longitude_deg + 180) % 360) - 180
        for item, ds, transformer in open_assets:
            if not (item.asset.min_range_m <= 0 <= item.asset.max_range_m):
                continue
            x, y = transformer.transform(origin_lon, origin_lat)
            sampled = _sample_one(ds, x, y, item.asset.elevation_units)
            if sampled is not None:
                site_ground_elevation = sampled
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
        for segment_start, segment_end in zip(boundaries[:-1], boundaries[1:]):
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
        asset_sample_counts = {item.asset.asset_id: 0 for item, _ds, _tr in open_assets}
        fallback_sample_count = 0
        for az_index in range(count):
            azimuth = az_index * azimuth_step_deg
            heights = np.full(distances.shape, np.nan, dtype=float)
            chosen_asset_index = np.full(distances.shape, -1, dtype=int)
            # Assets arrive sorted finest-to-coarsest. Only samples that have not yet received a
            # valid elevation are offered to the next asset. Therefore a masked/NoData pixel in a
            # fine local DEM can use a valid coarser regional DEM, but missing values are never
            # replaced with zero: if every eligible asset is unknown the ray remains incomplete.
            for asset_index, (item, ds, transformer) in enumerate(open_assets):
                asset = item.asset
                eligible = (
                    (distances >= asset.min_range_m)
                    & (distances <= min(asset.max_range_m, max_range_m))
                    & (chosen_asset_index < 0)
                )
                assigned = np.flatnonzero(eligible)
                if not len(assigned):
                    continue
                lats, lons = _ray_latlon_array(
                    latitude_deg, longitude_deg, azimuth, distances[assigned], manifest.body_radius_m
                )
                xs, ys = transformer.transform(lons, lats)
                xs = np.asarray(xs, dtype=float)
                ys = np.asarray(ys, dtype=float)
                # Chunk Rasterio sample calls to bound coordinate and sample memory.
                for offset in range(0, len(assigned), 25_000):
                    subset = assigned[offset:offset + 25_000]
                    end = min(offset + 25_000, len(assigned))
                    xy = list(zip(xs[offset:end].tolist(), ys[offset:end].tolist()))
                    samples = list(ds.sample(xy, masked=True))
                    sampled_heights = _physical_elevation_array_m(ds, samples, asset.elevation_units)
                    known_here = np.isfinite(sampled_heights)
                    accepted = subset[known_here]
                    heights[accepted] = sampled_heights[known_here]
                    chosen_asset_index[accepted] = asset_index
                    asset_sample_counts[asset.asset_id] += int(known_here.sum())
                    if asset_index > 0:
                        # Count any valid sample resolved by fallback when a finer asset would
                        # otherwise have been preferred by resolution. This is diagnostic only.
                        finer_eligible = np.zeros(len(accepted), dtype=bool)
                        if len(accepted):
                            for finer_item, _finer_ds, _finer_transformer in open_assets[:asset_index]:
                                finer_eligible |= (
                                    (distances[accepted] >= finer_item.asset.min_range_m)
                                    & (distances[accepted] <= min(finer_item.asset.max_range_m, max_range_m))
                                )
                        fallback_sample_count += int(finer_eligible.sum())

            known = np.isfinite(heights)
            nodata_count = int((~known).sum())
            elevations: list[tuple[float, float]] = []
            if np.any(known):
                radii = reference_radius_m + heights[known]
                angles = distances[known] / reference_radius_m
                apparent = np.arctan2(
                    radii * np.cos(angles) - observer_radius_m,
                    radii * np.sin(angles),
                )
                known_distances = distances[known]
                maximum_index = int(np.argmax(apparent))
                maximum_elevation = float(apparent[maximum_index])
                controlling_distance = float(known_distances[maximum_index])
                coverage_complete = nodata_count == 0 and math.isclose(float(distances[0]), 0.0) and math.isclose(float(distances[-1]), max_range_m)
                bins.append(HorizonBin(
                    azimuth_deg=float(azimuth),
                    elevation_rad=maximum_elevation,
                    controlling_distance_m=controlling_distance,
                    coverage_status="complete" if coverage_complete else "incomplete",
                    sample_count=int(len(distances)),
                    nodata_count=nodata_count,
                ))
            else:
                bins.append(HorizonBin(
                    azimuth_deg=float(azimuth), elevation_rad=None,
                    controlling_distance_m=None, coverage_status="none",
                    sample_count=int(len(distances)), nodata_count=nodata_count,
                ))

    horizon = TerrainHorizon(
        reference_radius_m=reference_radius_m,
        observer_radius_m=reference_radius_m + site_ground_elevation + observer_height_m,
        observer_height_m=observer_height_m,
        max_range_m=max_range_m,
        bins=tuple(bins),
    )
    metadata = {
        "manifest_sha256": sha256_file(dem_manifest_path),
        "site_ground_elevation_m": site_ground_elevation,
        "assets": [
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
                "raster_nodata": ds.nodata,
                "raster_scales": tuple(float(v) for v in ds.scales),
                "raster_offsets": tuple(float(v) for v in ds.offsets),
                "elevation_units": item.asset.elevation_units,
                "transform": tuple(ds.transform)[:6],
                "samples_used_total": asset_sample_counts.get(item.asset.asset_id, 0),
            }
            for item, ds, _transformer in open_assets
        ],
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


HORIZON_ALGORITHM_VERSION = "terrain-horizon-1.5-valid-sample-nested-fallback"


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
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, DEMManifestError) as exc:
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
