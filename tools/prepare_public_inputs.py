#!/usr/bin/env python3
"""Fetch a reproducible public-reference input set for the Lunar South Pole Mission Planner.

This script intentionally does NOT populate the official 2026 challenge site catalogue and does
NOT mark a DEM CRS or vertical datum as reviewed. It stages the NAIF DE421 geometry kernel set and
public PGDA reference terrain for the literature reference point ``reference-lola-site-001``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from lunar_core.terrain import DEMAsset, DEMManifest  # noqa: E402
from lunar_core.provenance import sha256_file  # noqa: E402

PGDA_HOSTS = {"pgda.gsfc.nasa.gov"}
BODY_RADIUS_M = 1_737_400.0

DEM_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "asset_id": "pgda78-site01-surface",
        "filename": "Site01_final_adj_5mpp_surf.tif",
        "url": "https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/Site01/Site01_final_adj_5mpp_surf.tif",
        "product_id": "NASA PGDA Product 78 — Site 01 / Connecting Ridge region",
        "site_ids": ["reference-lola-site-001"],
        "metadata_site_ids": ["reference-lola-site-001"],
        "native_resolution_m": 5.0,
        "min_range_m": 0.0,
        "max_range_m": 8_000.0,
        "max_download_bytes": 1_000_000_000,
        "vertical_datum": (
            "PGDA Product 78 surface-elevation raster; compatibility between raster elevation, "
            "reference radius, and observer-point model remains unverified."
        ),
        "crs_contract": (
            "Publisher describes south-polar stereographic X/Y in metres and MOON_ME associated "
            "with DE421. Verify actual GeoTIFF CRS metadata, axis transform, sample coverage, "
            "and agreement with the selected lunar geographic source CRS before use."
        ),
    },
    {
        "asset_id": "pgda78-site04-surface",
        "filename": "Site04_final_adj_5mpp_surf.tif",
        "url": "https://pgda.gsfc.nasa.gov/data/LOLA_5mpp/Site04/Site04_final_adj_5mpp_surf.tif",
        "product_id": "NASA PGDA Product 78 — Site 04 / Shackleton region",
        "site_ids": ["reference-lola-site-004"],
        "metadata_site_ids": ["reference-lola-site-004"],
        "native_resolution_m": 5.0,
        "min_range_m": 0.0,
        "max_range_m": 8_000.0,
        "max_download_bytes": 1_000_000_000,
        "vertical_datum": (
            "PGDA Product 78 Site 04 surface-elevation raster; compatibility between raster elevation, "
            "reference radius, and observer-point model remains unverified."
        ),
        "crs_contract": (
            "Publisher describes south-polar stereographic X/Y in metres and MOON_ME associated "
            "with DE421. Verify actual GeoTIFF CRS metadata, axis transform, sample coverage, "
            "and agreement with the selected lunar geographic source CRS before use."
        ),
    },
    {
        "asset_id": "pgda90-60s-240m-regional",
        "filename": "LDEM_60S_240MPP_ADJ.TIF",
        "url": "https://pgda.gsfc.nasa.gov/data/LOLA_20mpp/LDEM_60S_240MPP_ADJ.TIF",
        "product_id": "NASA PGDA Product 90 — regional 240 m/pixel DEM (60°S–90°S)",
        "site_ids": ["*"],
        "metadata_site_ids": ["*"],
        "native_resolution_m": 240.0,
        "min_range_m": 0.0,
        "max_range_m": 200_000.0,
        "max_download_bytes": 300_000_000,
        "vertical_datum": (
            "PGDA Product 90 regional surface-elevation raster in metres; compatibility between "
            "raster elevation, reference radius, and observer-point model remains unverified."
        ),
        "crs_contract": (
            "Publisher describes COG south-polar stereographic X/Y in metres and MOON_ME associated "
            "with DE421. This 60S product gives sufficient latitude coverage for a 200 km polar-site "
            "horizon range. Verify actual GeoTIFF CRS, axis transform, source geographic CRS and datum "
            "contract before use. Quantitative sampling must read full-resolution pixels, not overviews."
        ),
    },
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _is_allowed_https(url: str, allowed_hosts: set[str]) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and (parsed.hostname or "").lower() in allowed_hosts


def download_atomic(
    url: str,
    destination: Path,
    *,
    allowed_hosts: set[str],
    max_bytes: int,
    force: bool = False,
    opener: Callable[..., Any] = urllib.request.urlopen,
    progress: Callable[[int, int | None], None] | None = None,
) -> dict[str, Any]:
    """Download to a sibling temporary file; validate HTTPS host/redirect and size before replace."""
    if not _is_allowed_https(url, allowed_hosts):
        raise ValueError(f"Refusing non-HTTPS or non-allowlisted source: {url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not force:
        raise FileExistsError(
            f"{destination} already exists. The importer will not invent provenance for existing bytes; "
            "verify its manifest entry or re-fetch explicitly with --force."
        )
    request = urllib.request.Request(url, headers={"User-Agent": "lunar-south-pole-planner/0.7.0-dev"})
    fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".part", dir=destination.parent)
    os.close(fd)
    temp = Path(temp_name)
    digest = hashlib.sha256()
    downloaded = 0
    expected: int | None = None
    try:
        with opener(request, timeout=180) as response:
            final_url = response.geturl()
            if not _is_allowed_https(final_url, allowed_hosts):
                raise ValueError(f"Refusing redirect to non-allowlisted host: {final_url}")
            raw_length = response.headers.get("Content-Length")
            expected = int(raw_length) if raw_length and raw_length.isdigit() else None
            if expected is not None and expected > max_bytes:
                raise ValueError(f"Remote file advertises {expected:,} bytes; cap is {max_bytes:,}")
            with temp.open("wb") as stream:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    downloaded += len(chunk)
                    if downloaded > max_bytes:
                        raise ValueError(f"Download exceeded configured size cap ({max_bytes:,} bytes)")
                    digest.update(chunk)
                    stream.write(chunk)
                    if progress:
                        progress(downloaded, expected)
                stream.flush()
                os.fsync(stream.fileno())
        if downloaded == 0:
            raise ValueError(f"Downloaded empty response from {url}")
        if expected is not None and downloaded != expected:
            raise ValueError(f"Truncated download: received {downloaded:,} bytes; expected {expected:,}")
        os.replace(temp, destination)
        return {
            "path": destination,
            "sha256": digest.hexdigest(),
            "size_bytes": downloaded,
            "retrieved_utc": utc_now(),
            "downloaded": True,
            "source_url": url,
        }
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    finally:
        temp.unlink(missing_ok=True)


def _metadata(path: Path, sites: list[dict[str, Any]]) -> dict[str, Any]:
    """Inspect raster metadata and prove each assigned reference point hits a non-NoData pixel."""
    try:
        import rasterio
        import numpy as np
        from pyproj import CRS, Transformer
    except ImportError as exc:
        raise RuntimeError("Install the project runtime dependencies before registering DEMs") from exc

    with rasterio.open(path) as ds:
        if not ds.crs:
            raise ValueError(f"DEM {path.name} has no CRS")
        source_crs = CRS.from_proj4(f"+proj=longlat +R={BODY_RADIUS_M:.3f} +no_defs +type=crs")
        transform = Transformer.from_crs(source_crs, ds.crs, always_xy=True)
        point_checks: list[dict[str, Any]] = []
        for site in sites:
            lon = (float(site["longitude_deg"]) + 180.0) % 360.0 - 180.0
            x, y = transform.transform(lon, float(site["latitude_deg"]))
            row, col = ds.index(x, y)
            if row < 0 or col < 0 or row >= ds.height or col >= ds.width:
                raise ValueError(
                    f"Reference point {site['site_id']} transforms outside {path.name}: "
                    f"pixel row={row}, col={col}; do not register this raster for this site."
                )
            value = next(ds.sample([(x, y)], masked=True))[0]
            if np.ma.is_masked(value) or not np.isfinite(float(value)) or (
                ds.nodata is not None and float(value) == float(ds.nodata)
            ):
                raise ValueError(
                    f"Reference point {site['site_id']} falls on a NoData cell in {path.name}; "
                    "refusing registration"
                )
            point_checks.append({
                "site_id": site["site_id"], "x": x, "y": y, "row": row, "col": col,
                "raw_value": float(value),
            })
        return {
            "driver": ds.driver,
            "width": ds.width,
            "height": ds.height,
            "band_count": ds.count,
            "crs": ds.crs.to_string(),
            "bounds": [float(v) for v in ds.bounds],
            "transform": [float(v) for v in tuple(ds.transform)[:6]],
            "nodata": ds.nodata,
            "dtype": ds.dtypes[0],
            "scales": [float(v) for v in ds.scales],
            "offsets": [float(v) for v in ds.offsets],
            "band_units": ds.units,
            "sampled_reference_points": point_checks,
            "coverage_check": "all assigned reference points lie inside raster and sampled value is not NoData",
            "datum_review": "NOT REVIEWED; sample presence does not prove height-datum compatibility",
        }


def _load_reference_sites(project_root: Path) -> dict[str, dict[str, Any]]:
    catalogue = json.loads((project_root / "data/reference/reference_sites.json").read_text(encoding="utf-8"))
    sites = catalogue.get("sites", [])
    by_id = {str(site.get("site_id")): site for site in sites if isinstance(site, dict)}
    required = {"reference-lola-site-001", "reference-lola-site-004"}
    missing = sorted(required - set(by_id))
    if missing:
        raise ValueError(f"Required literature reference site(s) are missing: {', '.join(missing)}")
    return by_id


def _load_prior_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": "1.0", "manifest_state": "not_configured",
            "body_radius_m": BODY_RADIUS_M,
            "coordinate_contract": "Spherical lunar latitude/longitude transformed to raster CRS; frame/radius/datum must be reviewed.",
            "assets": [], "notes": [],
        }
    return json.loads(path.read_text(encoding="utf-8"))


def prepare_dems(project_root: Path, *, include_regional: bool = True, force: bool = False) -> dict[str, Any]:
    sites_by_id = _load_reference_sites(project_root)
    manifest_path = project_root / "data/dems/manifest.json"
    raw = _load_prior_manifest(manifest_path)
    existing = {str(asset.get("asset_id")): asset for asset in raw.get("assets", []) if isinstance(asset, dict)}
    staged: list[tuple[dict[str, Any], Path, Path, dict[str, Any]]] = []
    reused_assets: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    assets_dir = project_root / "data/dems/assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    definitions = DEM_SOURCES if include_regional else tuple(
        spec for spec in DEM_SOURCES if spec["asset_id"] != "pgda90-60s-240m-regional"
    )
    stage_dir = Path(tempfile.mkdtemp(prefix=".public-inputs-", dir=assets_dir))
    committed: list[Path] = []
    try:
        for spec in definitions:
            asset_id = str(spec["asset_id"])
            destination = assets_dir / str(spec["filename"])
            existing_asset = existing.get(asset_id)
            relative_destination = destination.relative_to(project_root).as_posix()
            previous_path = (project_root / str(existing_asset.get("relative_path", ""))).resolve(strict=False) if existing_asset else None
            root_resolved = project_root.resolve(strict=True)
            reusable = (
                not force and destination.is_file() and existing_asset is not None
                and existing_asset.get("relative_path") == relative_destination
                and previous_path is not None and previous_path.is_relative_to(root_resolved)
                and existing_asset.get("source_url") == spec["url"]
                and existing_asset.get("sha256") == sha256_file(destination)
                and existing_asset.get("size_bytes") == destination.stat().st_size
            )
            if reusable:
                info = {
                    "path": destination,
                    "sha256": str(existing_asset["sha256"]),
                    "size_bytes": destination.stat().st_size,
                    "retrieved_utc": existing_asset.get("retrieved_utc"),
                    "downloaded": False,
                    "source_url": spec["url"],
                }
                check_ids = spec.get("metadata_site_ids", spec.get("site_ids", []))
                if "*" in check_ids:
                    check_sites = list(sites_by_id.values())
                else:
                    check_sites = [sites_by_id[site_id] for site_id in check_ids]
                metadata = _metadata(destination, check_sites)
                reused_assets[asset_id] = existing_asset
                results.append({"asset_id": asset_id, "downloaded": False, "sha256": info["sha256"],
                                "size_bytes": info["size_bytes"], "raster_metadata": metadata})
                continue
            stage_path = stage_dir / str(spec["filename"])
            print(f"Fetching {spec['product_id']} {spec['filename']} …", flush=True)
            info = download_atomic(
                str(spec["url"]), stage_path,
                allowed_hosts=PGDA_HOSTS, max_bytes=int(spec["max_download_bytes"]), force=True,
                progress=lambda done, total: print(
                    f"  {done / 1_000_000:.1f} MB" + (f" / {total / 1_000_000:.1f} MB" if total else ""),
                    end="\r", flush=True,
                ) if (done % (16 * 1024 * 1024) < 1024 * 1024 or (total and done == total)) else None,
            )
            print("", flush=True)
            check_ids = spec.get("metadata_site_ids", spec.get("site_ids", []))
            if "*" in check_ids:
                check_sites = list(sites_by_id.values())
            else:
                check_sites = [sites_by_id[site_id] for site_id in check_ids]
            metadata = _metadata(stage_path, check_sites)
            staged.append((spec, stage_path, destination, {**info, "metadata": metadata}))
            results.append({"asset_id": asset_id, "downloaded": True, "sha256": info["sha256"],
                            "size_bytes": info["size_bytes"], "raster_metadata": metadata})

        requested_ids = {str(spec["asset_id"]) for spec in definitions}
        next_assets = [asset for asset in raw.get("assets", []) if asset.get("asset_id") not in requested_ids]
        next_assets.extend(reused_assets.values())
        for spec, stage_path, destination, info in staged:
            # Replace only after all requested assets have downloaded and passed the raster/point checks.
            os.replace(stage_path, destination)
            committed.append(destination)
            next_assets.append(DEMAsset.model_validate({
                "asset_id": spec["asset_id"],
                "relative_path": destination.relative_to(project_root).as_posix(),
                "site_ids": spec["site_ids"],
                "source_url": spec["url"],
                "product_id": spec["product_id"],
                "sha256": info["sha256"],
                "retrieved_utc": info["retrieved_utc"],
                "size_bytes": info["size_bytes"],
                "native_resolution_m": spec["native_resolution_m"],
                "min_range_m": spec["min_range_m"],
                "max_range_m": spec["max_range_m"],
                "elevation_units": "m",
                "vertical_datum": spec["vertical_datum"],
                "crs_contract": spec["crs_contract"],
                "crs_contract_verified": False,
                "crs_verification_note": None,
                "vertical_datum_verified": False,
                "vertical_datum_verification_note": None,
                "nodata_policy": "unknown",
            }).model_dump(mode="json"))
        # Preserve hashes/metadata for successfully reused assets and append a current metadata snapshot.
        for result in results:
            raw.setdefault("notes", []).append(
                f"{utc_now()}: inspected public reference DEM {result['asset_id']}; metadata={json.dumps(result['raster_metadata'], sort_keys=True)}"
            )
        updated = {**raw, "manifest_state": "configured", "assets": next_assets,
                   "notes": list(dict.fromkeys(raw.get("notes", [])))}
        parsed = DEMManifest.model_validate(updated)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_manifest = manifest_path.with_suffix(".json.tmp")
        tmp_manifest.write_text(json.dumps(parsed.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
        tmp_manifest.replace(manifest_path)
        reference_site_ids = ("reference-lola-site-001", "reference-lola-site-004")
        terrain_allowed_by_site = {
            site_id: bool((applicable := [
                asset for asset in parsed.assets if site_id in asset.site_ids or "*" in asset.site_ids
            ])) and all(asset.crs_contract_verified and asset.vertical_datum_verified for asset in applicable)
            for site_id in reference_site_ids
        }
        return {
            "manifest": str(manifest_path),
            "reference_site_ids": sorted({site_id for asset in parsed.assets for site_id in asset.site_ids if site_id != "*"}),
            "asset_count": len(parsed.assets),
            "terrain_analysis_allowed": all(terrain_allowed_by_site.values()),
            "terrain_allowed_by_site": terrain_allowed_by_site,
            "assets": results,
            "warning": "CRS/frame/vertical datum are deliberately unverified. Terrain mode must remain blocked until a written review note verifies each contract.",
        }
    except BaseException:
        # Newly staged binaries are disposable; never leave unreferenced partial downloads as usable inputs.
        raise
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--kernels-only", action="store_true", help="fetch NAIF kernels but do not download DEM rasters")
    parser.add_argument("--skip-kernels", action="store_true", help="reuse existing kernels instead of fetching them")
    parser.add_argument("--skip-regional-dem", action="store_true", help="fetch the 5 m near DEM only; omit the ~210 MB regional raster")
    parser.add_argument("--force", action="store_true", help="re-fetch bytes even if existing manifest hashes match")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    output: dict[str, Any] = {"root": str(root), "started_utc": utc_now()}
    try:
        if not args.skip_kernels:
            from fetch_kernels import fetch as fetch_kernels
            output["kernels"] = fetch_kernels(root, force=args.force)
        if not args.kernels_only:
            output["dems"] = prepare_dems(root, include_regional=not args.skip_regional_dem, force=args.force)
        output["completed_utc"] = utc_now()
        output["overall_status"] = "inputs_staged_review_required"
        print(json.dumps(output, indent=2, default=str))
        print("\nInputs staged. Official sites are still a separate catalogue; DEM datum approval and Horizons validation are NOT inferred from downloads.")
    except Exception as exc:
        parser.exit(2, f"Public input preparation failed: {type(exc).__name__}: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
