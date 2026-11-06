#!/usr/bin/env python3
"""Check the two new sky-geometry fields on the real kernels: ``j2000_to_frame`` and Earth's sub-Moon point.

Pass limits fixed here (2026-11-06) before the first run:

A. Star rotation ``j2000_to_frame`` (no network), 2027 at a 6 h step:
   A1 orthonormal: max |M M^T - I| <= 1e-8
   A2 agrees with SPICE vectors: for 13 epochs (every 30 days), M @ (Sun and Earth apparent vector in
      J2000) vs the response's MOON_ME unit vectors, angle <= 1e-4 deg (payload rounding is ~1e-5 deg)
   A3 the Moon's north pole in J2000 (row 3 of M): RA within 1 deg of 270.0, Dec within 1 deg of 66.5
      (IAU 2015: alpha0 = 269.9949, delta0 = 66.5392, plus terms well under 1 deg)
   A4 mean spin rate of the frame's +X axis about that pole: 360 / 27.321661 deg/day within 0.5%

B. Earth's sub-Moon point vs JPL Horizons (network), the same 13 epochs:
   Horizons observer table, target 399 (Earth), observer 500@301 (Moon centre), quantity 14
   (sub-observer longitude/latitude; for Earth: east-positive, planetodetic, high-precision Earth
   rotation). Ours is planetocentric on IAU_EARTH; latitude is converted to planetodetic with the
   generic PCK Earth radii before comparing.
   Pass: every epoch |d lon| * cos(lat) <= 0.1 deg and |d lat| <= 0.1 deg. (0.1 deg is about 11 km
   on Earth; IAU_EARTH omits nutation, roughly 0.005 deg in longitude.)

The gate passes only if A1-A4 and B all pass.

    .venv/bin/python tools/check_sky_orientation.py
"""
from __future__ import annotations

import json
import math
import sys
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

YEAR_WINDOW = ("2027-01-01T00:00:00Z", "2027-12-31T00:00:00Z")
YEAR_STEP_MIN = 360
EPOCH_STEP_DAYS = 30
SIDEREAL_DAYS = 27.321661
EARTH_A_KM, EARTH_B_KM = 6378.1366, 6356.7519
LIMITS = {
    "A1_orthonormal": 1e-8, "A2_vector_deg": 1e-4, "A3_pole_deg": 1.0, "A4_rate_fraction": 0.005,
    "B_lon_deg": 0.1, "B_lat_deg": 0.1,
}


def centric_to_detic_deg(lat_c_deg: float, a_km: float = EARTH_A_KM, b_km: float = EARTH_B_KM) -> float:
    """Planetocentric -> planetodetic latitude for a point on the ellipsoid surface."""
    if abs(lat_c_deg) >= 90.0:
        return lat_c_deg
    return math.degrees(math.atan(math.tan(math.radians(lat_c_deg)) * (a_km / b_km) ** 2))


def wrap_deg(d: float) -> float:
    return (d + 180.0) % 360.0 - 180.0


def angle_deg(u: list[float], v: list[float]) -> float:
    """Angle between two vectors (atan2 form, accurate for tiny angles)."""
    cross = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
    dot = sum(a * b for a, b in zip(u, v, strict=True))
    return math.degrees(math.atan2(math.sqrt(sum(c * c for c in cross)), dot))


def matvec(m: list[list[float]], v: list[float]) -> list[float]:
    return [sum(m[i][k] * v[k] for k in range(3)) for i in range(3)]


def orthonormal_error(m: list[list[float]]) -> float:
    return max(abs(sum(m[i][k] * m[j][k] for k in range(3)) - (1.0 if i == j else 0.0)) for i in range(3) for j in range(3))


def pole_ra_dec(m: list[list[float]]) -> tuple[float, float]:
    """Frame +Z in J2000 is row 3 of M (v_frame = M v_J2000)."""
    x, y, z = m[2]
    return math.degrees(math.atan2(y, x)) % 360.0, math.degrees(math.asin(max(-1.0, min(1.0, z))))


def spin_rate_deg_per_day(mats: list[list[list[float]]], et_s: list[float]) -> float:
    """Mean rate of the frame's +X axis (row 1) about the frame pole (row 3), unwrapped."""
    def phase(m: list[list[float]]) -> float:
        pole = m[2]
        # Fixed J2000 reference axis perpendicular to the pole: pole x J2000 +Z (or +X if the pole
        # is near +Z), normalised.
        e = [0.0, 0.0, 1.0] if abs(pole[2]) < 0.9 else [1.0, 0.0, 0.0]
        ref = [pole[1] * e[2] - pole[2] * e[1], pole[2] * e[0] - pole[0] * e[2], pole[0] * e[1] - pole[1] * e[0]]
        n = math.sqrt(sum(c * c for c in ref))
        ref = [c / n for c in ref]
        ref2 = [pole[1] * ref[2] - pole[2] * ref[1], pole[2] * ref[0] - pole[0] * ref[2], pole[0] * ref[1] - pole[1] * ref[0]]
        x = m[0]
        return math.degrees(math.atan2(sum(a * b for a, b in zip(x, ref2, strict=True)), sum(a * b for a, b in zip(x, ref, strict=True))))

    phases = [phase(m) for m in mats]
    total = sum(wrap_deg(b - a) for a, b in zip(phases, phases[1:], strict=False))
    days = (et_s[-1] - et_s[0]) / 86_400.0
    return total / days


def horizons_params(jds: list[float]) -> dict[str, str]:
    return {
        "format": "json", "COMMAND": "'399'", "OBJ_DATA": "'NO'", "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'OBSERVER'", "CENTER": "'500@301'",
        "TLIST": "\n".join(f"{jd:.9f}" for jd in jds),  # newline-separated, as astroquery sends it "TLIST_TYPE": "'JD'", "TIME_TYPE": "'UT'",
        "QUANTITIES": "'14'", "ANG_FORMAT": "'DEG'", "EXTRA_PREC": "'YES'", "CSV_FORMAT": "'YES'",
    }


def parse_sub_observer(result_text: str) -> list[tuple[float, float]]:
    """(east lon, planetodetic lat) rows from a Horizons quantity-14 CSV table."""
    lines = result_text.splitlines()
    try:
        soe = next(i for i, line in enumerate(lines) if line.strip() == "$$SOE")
        eoe = next(i for i, line in enumerate(lines) if line.strip() == "$$EOE")
    except StopIteration as exc:
        raise ValueError("Horizons result has no $$SOE/$$EOE block") from exc
    header_line = next(
        (lines[i] for i in range(soe - 1, -1, -1) if "," in lines[i] and not set(lines[i].strip()) <= {"*"}), None,
    )
    if header_line is None:
        raise ValueError("no CSV header above $$SOE")
    header = [f.strip().lower() for f in header_line.split(",")]
    lon_i = [i for i, n in enumerate(header) if n.endswith("-lon") or n == "obssub-lon"]
    lat_i = [i for i, n in enumerate(header) if n.endswith("-lat") or n == "obssub-lat"]
    if len(lon_i) != 1 or len(lat_i) != 1:
        raise ValueError(f"could not find one sub-observer lon/lat column in {header}")
    rows = []
    for line in lines[soe + 1:eoe]:
        if line.strip():
            values = [f.strip() for f in line.split(",")]
            rows.append((float(values[lon_i[0]]) % 360.0, float(values[lat_i[0]])))
    return rows


def main() -> int:
    from horizons_golden import HORIZONS_API, fetch_json, utc_to_jd
    from lunar_core.analysis_service import _spice_runtime, run_sky_geometry
    from lunar_core.api_models import SkyGeometryRequest
    from lunar_core.spice_runtime import SPICE_LOCK

    sky = run_sky_geometry(SkyGeometryRequest(start_utc=YEAR_WINDOW[0], end_utc=YEAR_WINDOW[1], step_min=YEAR_STEP_MIN))
    s = sky["series"]
    mats, et_s = s["j2000_to_frame"], s["et_s"]
    every = EPOCH_STEP_DAYS * 24 * 60 // YEAR_STEP_MIN
    picks = list(range(0, len(et_s), every))
    results: dict[str, Any] = {}

    a1 = max(orthonormal_error(m) for m in mats)
    results["A1_orthonormal"] = {"value": a1, "pass": a1 <= LIMITS["A1_orthonormal"]}

    spice, geometry, _hash, _kernels = _spice_runtime()
    worst = 0.0
    with SPICE_LOCK:
        for i in picks:
            for target, track in (("SUN", s["sun"]), ("EARTH", s["earth"])):
                v_j2000, _lt = spice.spkpos(target, et_s[i], "J2000", geometry.aberration_correction, "MOON")
                worst = max(worst, angle_deg(matvec(mats[i], [float(c) for c in v_j2000]), track["unit"][i]))
    results["A2_vector_deg"] = {"value": worst, "pass": worst <= LIMITS["A2_vector_deg"]}

    ras, decs = zip(*(pole_ra_dec(m) for m in mats), strict=True)
    ra_err = max(abs(wrap_deg(r - 270.0)) for r in ras)
    dec_err = max(abs(d - 66.5) for d in decs)
    results["A3_pole_deg"] = {"value": {"max_ra_err": ra_err, "max_dec_err": dec_err,
                                        "ra_range": [min(ras), max(ras)], "dec_range": [min(decs), max(decs)]},
                              "pass": ra_err <= LIMITS["A3_pole_deg"] and dec_err <= LIMITS["A3_pole_deg"]}

    rate = spin_rate_deg_per_day(mats, et_s)
    expected = 360.0 / SIDEREAL_DAYS
    results["A4_rate_deg_per_day"] = {"value": rate, "expected": expected,
                                      "pass": abs(rate - expected) <= LIMITS["A4_rate_fraction"] * expected}

    jds = [utc_to_jd(s["utc"][i].replace("Z", "+00:00")) for i in picks]
    url = HORIZONS_API + "?" + urllib.parse.urlencode(sorted(horizons_params(jds).items()))
    ref = parse_sub_observer(str(fetch_json(url)["result"]))
    if len(ref) != len(picks):
        raise SystemExit(f"Horizons returned {len(ref)} rows for {len(picks)} epochs")
    rows = []
    for (h_lon, h_lat), i in zip(ref, picks, strict=True):
        o_lon = s["earth"]["sub_moon_lon_east_deg"][i]
        o_lat = centric_to_detic_deg(s["earth"]["sub_moon_lat_deg"][i])
        d_lon = wrap_deg(o_lon - h_lon) * math.cos(math.radians(h_lat))
        d_lat = o_lat - h_lat
        rows.append({"utc": s["utc"][i], "horizons": [h_lon, h_lat], "ours_detic": [round(o_lon, 4), round(o_lat, 4)],
                     "d_lon_cos_lat": round(d_lon, 4), "d_lat": round(d_lat, 4),
                     "pass": abs(d_lon) <= LIMITS["B_lon_deg"] and abs(d_lat) <= LIMITS["B_lat_deg"]})
    results["B_sub_moon_vs_horizons"] = {"rows": rows, "pass": all(r["pass"] for r in rows)}

    print(f"Sky orientation check — frame {sky['frame']}, {len(et_s)} samples over 2027, {len(picks)} test epochs")
    print(f"  A1 orthonormal       max err {a1:.1e}   {'PASS' if results['A1_orthonormal']['pass'] else 'FAIL'}")
    print(f"  A2 M @ J2000 vectors max {worst:.2e} deg   {'PASS' if results['A2_vector_deg']['pass'] else 'FAIL'}")
    print(f"  A3 Moon pole         RA {min(ras):.3f}..{max(ras):.3f}  Dec {min(decs):.3f}..{max(decs):.3f}   "
          f"{'PASS' if results['A3_pole_deg']['pass'] else 'FAIL'}")
    print(f"  A4 spin rate         {rate:.5f} deg/day (expected {expected:.5f})   "
          f"{'PASS' if results['A4_rate_deg_per_day']['pass'] else 'FAIL'}")
    print("  B  Earth sub-Moon point vs Horizons (deg)")
    for r in rows:
        print(f"     {r['utc'][:16]}  Horizons {r['horizons'][0]:9.4f} {r['horizons'][1]:8.4f}  "
              f"ours {r['ours_detic'][0]:9.4f} {r['ours_detic'][1]:8.4f}  "
              f"dlon {r['d_lon_cos_lat']:+.4f} dlat {r['d_lat']:+.4f}  {'PASS' if r['pass'] else 'FAIL'}")
    passed = all(v["pass"] for v in results.values())
    print(f"\nVERDICT (criteria fixed before the run): {'PASS' if passed else 'FAIL'}")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "data" / "derived" / f"sky_orientation_check_{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"created_utc": stamp, "pass": passed, "limits": LIMITS, "results": results,
                               "horizons_url": url, "provenance": sky["provenance"]}, indent=2), encoding="utf-8")
    print(f"report: {out.relative_to(ROOT)}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
