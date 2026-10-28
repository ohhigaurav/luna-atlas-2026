#!/usr/bin/env python3
"""Fetch JPL Horizons reference geometry for a saved run and compare against it (Gate B).

For a saved ``spice_backed_analysis`` run this tool:

1. picks golden epochs from the run's own sample times (first, middle, last, plus the samples
   where the Sun and the Earth are closest to the horizon);
2. queries the JPL Horizons API for the apparent azimuth/elevation and range of the Sun and
   the Earth seen from the same lunar surface point (``coord@301``, geodetic east longitude,
   latitude and altitude above the 1737.4 km reference sphere), airless, extra precision;
3. archives every raw response together with its exact query and SHA-256;
4. writes the normalised reference CSV and runs ``tools/compare_horizons.py`` against the
   tolerances that were approved before the run (D-10).

Horizons is an independent reference, not ground truth: it uses its own ephemeris and lunar
orientation. Differences above tolerance mean "investigate frames, time scales, aberration
and observer position", never "loosen the tolerance".
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))
from tools.compare_horizons import compare_run  # noqa: E402

HORIZONS_API = "https://ssd.jpl.nasa.gov/api/horizons.api"
HORIZONS_DOC = "https://ssd-api.jpl.nasa.gov/doc/horizons.html"
TARGET_CODES = {"SUN": "10", "EARTH": "399"}
NEAR_HORIZON_DEG = 1.0
JD_UNIX_EPOCH = 2440587.5


def utc_to_jd(utc: str) -> float:
    """Julian Date (UTC-based, as Horizons interprets TIME_TYPE=UT) for an ISO UTC string."""
    parsed = datetime.fromisoformat(utc)
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError(f"epoch must be explicit UTC: {utc}")
    return JD_UNIX_EPOCH + parsed.timestamp() / 86_400.0


def build_query(target: str, east_lon_deg: float, lat_deg: float, alt_km: float, jd_ut: float) -> dict[str, str]:
    """Exact Horizons API parameters for one observer epoch. Values are quoted as the API expects."""
    if target not in TARGET_CODES:
        raise ValueError(f"unsupported target {target!r}")
    return {
        "format": "json",
        "COMMAND": f"'{TARGET_CODES[target]}'",
        "OBJ_DATA": "'NO'",
        "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'OBSERVER'",
        "CENTER": "'coord@301'",
        "COORD_TYPE": "'GEODETIC'",
        "SITE_COORD": f"'{east_lon_deg % 360.0:.9f},{lat_deg:.9f},{alt_km:.9f}'",
        "TLIST": f"'{jd_ut:.9f}'",
        "TLIST_TYPE": "'JD'",
        "TIME_TYPE": "'UT'",
        "QUANTITIES": "'4,20'",
        "ANG_FORMAT": "'DEG'",
        "APPARENT": "'AIRLESS'",
        "RANGE_UNITS": "'KM'",
        "EXTRA_PREC": "'YES'",
        "CSV_FORMAT": "'YES'",
    }


def query_url(params: dict[str, str]) -> str:
    return HORIZONS_API + "?" + urllib.parse.urlencode(sorted(params.items()))


def parse_observer_csv(result_text: str) -> dict[str, float]:
    """Extract azimuth, elevation (deg) and range (km) from a one-row Horizons CSV ephemeris."""
    lines = result_text.splitlines()
    try:
        soe = next(i for i, line in enumerate(lines) if line.strip() == "$$SOE")
        eoe = next(i for i, line in enumerate(lines) if line.strip() == "$$EOE")
    except StopIteration as exc:
        raise ValueError("Horizons result has no $$SOE/$$EOE ephemeris block; check the query") from exc
    header_line = next(
        (lines[i] for i in range(soe - 1, -1, -1) if "," in lines[i] and not set(lines[i].strip()) <= {"*"}),
        None,
    )
    data = [line for line in lines[soe + 1:eoe] if line.strip()]
    if header_line is None or len(data) != 1:
        raise ValueError(f"expected one header and one data row, got {len(data)} rows")
    header = [field.strip().lower() for field in header_line.split(",")]
    values = [field.strip() for field in data[0].split(",")]

    def column(predicate: Any, label: str) -> float:
        matches = [i for i, name in enumerate(header) if predicate(name)]
        if len(matches) != 1:
            raise ValueError(f"could not identify a unique {label} column in header {header}")
        return float(values[matches[0]])

    return {
        "azimuth_deg": column(lambda n: n.startswith("azi"), "azimuth"),
        "elevation_deg": column(lambda n: n.startswith("elev"), "elevation"),
        "range_km": column(lambda n: n == "delta", "range (delta)"),
    }


def select_epochs(series: list[dict[str, Any]]) -> list[tuple[int, bool]]:
    """(sample index, near_horizon) for first/middle/last and nearest-to-horizon Sun and Earth."""
    if len(series) < 3:
        raise ValueError("run series must contain at least three samples")
    chosen: dict[int, bool] = {0: False, len(series) // 2: False, len(series) - 1: False}
    for key in ("sun_elevation_deg", "earth_elevation_deg"):
        index = min(range(len(series)), key=lambda i, k=key: abs(float(series[i][k])))
        near = abs(float(series[index][key])) <= NEAR_HORIZON_DEG
        chosen[index] = chosen.get(index, False) or near
    return sorted(chosen.items())


def fetch_json(url: str, timeout_s: float = 60.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "luna-atlas-geometry-validation/0.7"})
    with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310 - fixed HTTPS host
        payload = json.loads(response.read().decode("utf-8"))
    if "error" in payload:
        raise ValueError(f"Horizons API error: {payload['error']}")
    if "result" not in payload:
        raise ValueError("Horizons API response has no 'result' field")
    return payload


def build_reference(run_path: Path, out_dir: Path, *, pause_s: float = 0.5, fetcher: Any = fetch_json) -> Path:
    run = json.loads(run_path.read_text(encoding="utf-8"))
    if run.get("analysis_kind") != "spice_backed_analysis":
        raise ValueError("run must be a saved spice_backed_analysis (Compare) result")
    settings = run["settings"]
    raw_dir = out_dir / "horizons_raw" / str(run["run_id"])
    raw_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for site_result in run["sites"]:
        site = site_result["site"]
        ground_m = float(site_result.get("terrain", {}).get("site_ground_elevation_m", 0.0) or 0.0)
        heights = {"SUN": float(settings["sun_observer_height_m"]), "EARTH": float(settings["antenna_height_m"])}
        for index, near in select_epochs(site_result["series"]):
            sample = site_result["series"][index]
            utc = datetime.fromisoformat(sample["utc"]).astimezone(UTC)
            utc_text = utc.isoformat(timespec="milliseconds").replace("+00:00", "Z")
            for target in ("SUN", "EARTH"):
                params = build_query(
                    target, float(site["longitude_deg"]), float(site["latitude_deg"]),
                    (ground_m + heights[target]) / 1000.0, utc_to_jd(utc_text),
                )
                url = query_url(params)
                query_sha = hashlib.sha256(url.encode("utf-8")).hexdigest()
                payload = fetcher(url)
                retrieved = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
                (raw_dir / f"{query_sha}.json").write_text(json.dumps({
                    "query_url": url, "query_params": params, "retrieved_utc": retrieved,
                    "site_id": site["site_id"], "target": target, "run_sample_utc": utc_text,
                    "response": payload,
                }, indent=2, sort_keys=True), encoding="utf-8")
                parsed = parse_observer_csv(str(payload["result"]))
                rows.append({
                    "site_id": site["site_id"], "target": target, "utc": utc_text,
                    "azimuth_deg": repr(parsed["azimuth_deg"]),
                    "elevation_deg": repr(parsed["elevation_deg"]),
                    "range_km": repr(parsed["range_km"]),
                    "source_url": HORIZONS_DOC, "query_sha256": query_sha,
                    "near_horizon": "true" if near else "false",
                })
                time.sleep(pause_s)
    reference = out_dir / f"horizons_reference_{run['run_id']}.csv"
    with reference.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return reference


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_json", type=Path, help="saved run, e.g. data/runs/<run_id>.json")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "validation" / "evidence")
    parser.add_argument("--tolerances", type=Path, default=ROOT / "validation" / "horizons_tolerances.json")
    args = parser.parse_args()
    try:
        reference = build_reference(args.run_json, args.out_dir)
        run_id = json.loads(args.run_json.read_text(encoding="utf-8"))["run_id"]
        output = args.out_dir / f"horizons_comparison_{run_id}.json"
        report = compare_run(args.run_json, reference, args.tolerances, output)
    except Exception as exc:  # noqa: BLE001 - report any failure as an uncertified comparison
        parser.exit(2, f"Horizons golden check could not be completed: {type(exc).__name__}: {exc}\n")
    print(f"reference CSV: {reference}")
    print(f"report:        {output}")
    print(f"{'site':32} {'target':6} {'utc':25} {'d_az_as':>9} {'d_el_as':>9} {'d_km':>8}  near")
    for item in report["observations"]:
        print(f"{item['site_id']:32} {item['target']:6} {item['utc']:25} "
              f"{item['azimuth_error_arcsec']:9.4f} {item['elevation_error_arcsec']:9.4f} "
              f"{item['range_error_km']:8.4f}  {'yes' if item['near_horizon'] else ''}")
    print(f"\nmax |d_az| {report['max_azimuth_error_arcsec']:.4f} arcsec, "
          f"max |d_el| {report['max_elevation_error_arcsec']:.4f} arcsec, "
          f"max |d_range| {report['max_range_error_km']:.4f} km")
    print("RESULT:", "PASS (within the D-10 tolerances approved before this run)" if report["passed"] else "FAIL")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
