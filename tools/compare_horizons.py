#!/usr/bin/env python3
"""Compare a saved SPICE run against manually normalised JPL Horizons reference observations.

Reference CSV columns:
  site_id,target,utc,azimuth_deg,elevation_deg,range_km,source_url,query_sha256,near_horizon

The CSV is a normalisation of the *saved* Horizons response, not a replacement for that raw
response. Archive the raw response and the exact Horizons query with every golden set. The
comparison refuses to run until D-10 tolerances are approved and predeclared in the config.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from lunar_core.provenance import sha256_file  # noqa: E402

REQUIRED = {"site_id", "target", "utc", "azimuth_deg", "elevation_deg", "range_km", "source_url", "query_sha256", "near_horizon"}


def canonical_utc(value: str) -> str:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError(f"timestamp must be explicit UTC: {value}")
    return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def angular_difference_deg(actual: float, expected: float) -> float:
    """Signed shortest difference in degrees, handling the 0/360 wrap."""
    return (actual - expected + 180.0) % 360.0 - 180.0


def load_reference(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = REQUIRED - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"reference CSV is missing columns: {', '.join(sorted(missing))}")
        for line, raw in enumerate(reader, start=2):
            target = raw["target"].strip().upper()
            if target not in {"SUN", "EARTH"}:
                raise ValueError(f"line {line}: target must be SUN or EARTH")
            query_sha = raw["query_sha256"].strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", query_sha):
                raise ValueError(f"line {line}: query_sha256 must be 64 lowercase/uppercase hex characters")
            source_url = raw["source_url"].strip()
            if not source_url.startswith("https://"):
                raise ValueError(f"line {line}: source_url must use HTTPS")
            rows.append({
                "site_id": raw["site_id"].strip(), "target": target,
                "utc": canonical_utc(raw["utc"]),
                "azimuth_deg": float(raw["azimuth_deg"]),
                "elevation_deg": float(raw["elevation_deg"]),
                "range_km": float(raw["range_km"]), "source_url": source_url,
                "query_sha256": query_sha,
                "near_horizon": raw["near_horizon"].strip().lower() in {"1", "true", "yes", "y"},
            })
            if not all(math.isfinite(rows[-1][key]) for key in ("azimuth_deg", "elevation_deg", "range_km")):
                raise ValueError(f"line {line}: numeric reference values must be finite")
    if not rows:
        raise ValueError("reference CSV is empty")
    return rows


def compare_run(run_path: Path, reference_path: Path, tolerance_path: Path, output_path: Path) -> dict[str, Any]:
    tolerances = json.loads(tolerance_path.read_text(encoding="utf-8"))
    if tolerances.get("status") != "approved_before_run" or not tolerances.get("predeclared_utc") or not tolerances.get("approved_by"):
        raise ValueError("D-10 tolerances are not approved/predeclared; update validation/horizons_tolerances.json before comparison")
    for field in ("azimuth_tolerance_arcsec", "elevation_tolerance_arcsec"):
        if not isinstance(tolerances.get(field), (int, float)) or tolerances[field] <= 0:
            raise ValueError(f"{field} must be a positive, approved value")
    range_tol = tolerances.get("range_tolerance_km")
    if range_tol is not None and (not isinstance(range_tol, (int, float)) or range_tol <= 0):
        raise ValueError("range_tolerance_km must be null or a positive value")

    run = json.loads(run_path.read_text(encoding="utf-8"))
    try:
        declared_at = datetime.fromisoformat(str(tolerances["predeclared_utc"]).replace("Z", "+00:00"))
        run_created = datetime.fromisoformat(str(run["created_utc"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("predeclared_utc and run.created_utc must be explicit ISO-8601 timestamps") from exc
    if declared_at.tzinfo is None or declared_at.utcoffset() != timezone.utc.utcoffset(declared_at):
        raise ValueError("predeclared_utc must be an explicit UTC timestamp")
    if run_created.tzinfo is None or run_created.utcoffset() != timezone.utc.utcoffset(run_created):
        raise ValueError("run.created_utc must be an explicit UTC timestamp")
    if declared_at >= run_created:
        raise ValueError(
            "tolerances were not declared before this run; record a new approved config and rerun analysis before comparison"
        )
    if run.get("analysis_kind") != "spice_backed_analysis":
        raise ValueError("run JSON must be a real spice_backed_analysis output, not a preview or finder")
    if run.get("validation_status") == "preview_not_scientific_output":
        raise ValueError("UX preview cannot be used as a validation result")
    series_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    site_ids: set[str] = set()
    for site in run.get("sites", []):
        site_id = site.get("site", {}).get("site_id", "")
        site_ids.add(site_id)
        for record in site.get("series", []):
            key_utc = canonical_utc(record["utc"])
            for target in ("SUN", "EARTH"):
                series_by_key[(site_id, target, key_utc)] = record

    reference = load_reference(reference_path)
    ref_sites = {item["site_id"] for item in reference}
    if len(ref_sites) < int(tolerances.get("minimum_site_count", 2)):
        raise ValueError("reference set does not meet the predeclared minimum distinct-site count")
    epochs_per_site: dict[str, set[str]] = defaultdict(set)
    if tolerances.get("requires_near_horizon_epoch", True) and not any(row["near_horizon"] for row in reference):
        raise ValueError("reference set must include a reviewer-labelled near-horizon epoch")

    observations: list[dict[str, Any]] = []
    for row in reference:
        key = (row["site_id"], row["target"], row["utc"])
        series = series_by_key.get(key)
        if series is None:
            raise ValueError(f"no exact matching output sample for {key}; create golden epochs at exact run sample times")
        prefix = row["target"].lower()
        actual_az = float(series[f"{prefix}_azimuth_deg"])
        actual_el = float(series[f"{prefix}_elevation_deg"])
        actual_range_km = float(series[f"{prefix}_range_m"]) / 1000.0
        az_error_arcsec = abs(angular_difference_deg(actual_az, row["azimuth_deg"])) * 3600.0
        el_error_arcsec = abs(actual_el - row["elevation_deg"]) * 3600.0
        range_error_km = abs(actual_range_km - row["range_km"])
        epochs_per_site[row["site_id"]].add(row["utc"])
        observations.append({
            "site_id": row["site_id"], "target": row["target"], "utc": row["utc"],
            "near_horizon": row["near_horizon"],
            "actual_azimuth_deg": actual_az, "reference_azimuth_deg": row["azimuth_deg"],
            "azimuth_error_arcsec": az_error_arcsec,
            "actual_elevation_deg": actual_el, "reference_elevation_deg": row["elevation_deg"],
            "elevation_error_arcsec": el_error_arcsec,
            "actual_range_km": actual_range_km, "reference_range_km": row["range_km"],
            "range_error_km": range_error_km, "source_url": row["source_url"],
            "query_sha256": row["query_sha256"],
            "pass_azimuth": az_error_arcsec <= tolerances["azimuth_tolerance_arcsec"],
            "pass_elevation": el_error_arcsec <= tolerances["elevation_tolerance_arcsec"],
            "pass_range": True if range_tol is None else range_error_km <= range_tol,
        })
    min_epochs = int(tolerances.get("minimum_epochs_per_site", 3))
    too_few = {site: len(epochs) for site, epochs in epochs_per_site.items() if len(epochs) < min_epochs}
    if too_few:
        raise ValueError(f"not enough distinct epochs per site; observed {too_few}, require >= {min_epochs}")
    result = {
        "schema_version": "1.0", "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "run_id": run.get("run_id"), "run_created_utc": run.get("created_utc"),
        "run_sha256": sha256_file(run_path), "output_path": str(output_path),
        "reference_sha256": sha256_file(reference_path), "reference_count": len(reference),
        "site_count": len(ref_sites), "tolerance_config_sha256": sha256_file(tolerance_path),
        "tolerances": tolerances,
        "max_azimuth_error_arcsec": max(item["azimuth_error_arcsec"] for item in observations),
        "max_elevation_error_arcsec": max(item["elevation_error_arcsec"] for item in observations),
        "max_range_error_km": max(item["range_error_km"] for item in observations),
        "passed": all(item["pass_azimuth"] and item["pass_elevation"] and item["pass_range"] for item in observations),
        "observations": observations,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(output_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_json", type=Path)
    parser.add_argument("reference_csv", type=Path)
    parser.add_argument("--tolerances", type=Path, default=ROOT / "validation/horizons_tolerances.json")
    parser.add_argument("--output", type=Path, default=ROOT / "validation/evidence/horizons_comparison.json")
    args = parser.parse_args()
    try:
        report = compare_run(args.run_json, args.reference_csv, args.tolerances, args.output)
        print(json.dumps({key: report[key] for key in (
            "passed", "reference_count", "site_count", "max_azimuth_error_arcsec",
            "max_elevation_error_arcsec", "max_range_error_km", "output_path",
        )}, indent=2))
        return 0 if report["passed"] else 1
    except Exception as exc:
        parser.exit(2, f"Horizons comparison could not be certified: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
