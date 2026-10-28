# Gate B — SPICE geometry vs JPL Horizons (2026-10-28)

**Result: PASS.** Maximum differences 0.0212 arcsec azimuth, 0.0413 arcsec elevation, 0.0107 km range, against tolerances of 1 arcsec / 1 arcsec / 1 km approved and committed before the run (D-10, `validation/horizons_tolerances.json`, commit `a3acb57`).

## Setup

| Item | Value |
| --- | --- |
| Command | `./scripts/validate_geometry.sh` (fresh run, then `tools/horizons_golden.py`) |
| Runs | `b387fa81-97c7-45d7-b633-b37874e9849b` (archived here); `77a5ce81-4291-4f0b-837e-d90b26b6fcde` gave identical residuals to 4 decimals |
| Sites | `reference-malapert-massif` (85.99 S, 357.07 E), `reference-lola-site-001` (89.45 S, 222.69 E) — literature reference points, flat horizon, observer 2 m above the 1737.4 km sphere |
| Interval | 2027-01-01 to 2027-01-31 UTC, 30-minute samples |
| Kernels | naif0012.tls, pck00011.tpc, moon_080317.tf, moon_assoc_me.tf, de421.bsp, moon_pa_de421_1900-2050.bpc (hashes in `data/manifests/kernels.json`) |
| Our geometry | SPICE `azlcpo`, frame MOON_ME, aberration LT+S, azimuth clockwise from north |
| Reference | JPL Horizons API, observer `coord@301` geodetic, quantities 4 (apparent az/el) and 20 (range), AIRLESS, extra precision, UT |
| Epochs per site | first, middle, last sample, plus the samples with the Sun and the Earth nearest the horizon (flagged near-horizon) |
| Comparisons | 20 (2 sites × 5 epochs × Sun and Earth), 8 near-horizon |
| Host | Python 3.14.7, EndeavourOS laptop |

## Residuals (arcsec, arcsec, km)

| Site | Target | UTC | d_az | d_el | d_range | Near horizon |
| --- | --- | --- | --- | --- | --- | --- |
| Malapert | SUN | 2027-01-01T00:00:00Z | 0.0173 | 0.0281 | 0.0080 | |
| Malapert | EARTH | 2027-01-01T00:00:00Z | 0.0209 | 0.0275 | 0.0041 | |
| Malapert | SUN | 2027-01-07T21:00:00Z | 0.0129 | 0.0227 | 0.0032 | yes |
| Malapert | EARTH | 2027-01-07T21:00:00Z | 0.0170 | 0.0223 | 0.0000 | yes |
| Malapert | SUN | 2027-01-16T00:30:00Z | 0.0118 | 0.0093 | 0.0094 | |
| Malapert | EARTH | 2027-01-16T00:30:00Z | 0.0141 | 0.0357 | 0.0035 | |
| Malapert | SUN | 2027-01-30T14:00:00Z | 0.0159 | 0.0273 | 0.0053 | yes |
| Malapert | EARTH | 2027-01-30T14:00:00Z | 0.0202 | 0.0232 | 0.0041 | yes |
| Malapert | SUN | 2027-01-31T00:00:00Z | 0.0154 | 0.0242 | 0.0007 | |
| Malapert | EARTH | 2027-01-31T00:00:00Z | 0.0199 | 0.0227 | 0.0039 | |
| Site 001 | SUN | 2027-01-01T00:00:00Z | 0.0151 | 0.0294 | 0.0063 | |
| Site 001 | EARTH | 2027-01-01T00:00:00Z | 0.0212 | 0.0273 | 0.0041 | |
| Site 001 | SUN | 2027-01-11T03:30:00Z | 0.0115 | 0.0309 | 0.0060 | yes |
| Site 001 | EARTH | 2027-01-11T03:30:00Z | 0.0149 | 0.0260 | 0.0013 | yes |
| Site 001 | SUN | 2027-01-16T00:30:00Z | 0.0111 | 0.0102 | 0.0107 | |
| Site 001 | EARTH | 2027-01-16T00:30:00Z | 0.0135 | 0.0359 | 0.0035 | |
| Site 001 | SUN | 2027-01-20T14:00:00Z | 0.0128 | 0.0269 | 0.0059 | yes |
| Site 001 | EARTH | 2027-01-20T14:00:00Z | 0.0141 | 0.0413 | 0.0007 | yes |
| Site 001 | SUN | 2027-01-31T00:00:00Z | 0.0136 | 0.0253 | 0.0021 | |
| Site 001 | EARTH | 2027-01-31T00:00:00Z | 0.0201 | 0.0226 | 0.0039 | |

(Two sample labels print as `13:59:59.999Z` in the raw files: a floating-point ET-to-UTC labelling artefact, not a different epoch.)

## Physics plausibility (same 30 days, flat horizon)

| Quantity | Expected before running | Computed |
| --- | --- | --- |
| Malapert Sun elevation | within about ±5.5° | −3.11° to +4.50° |
| Malapert Earth elevation | about −3° to +11° | −3.14° to +10.51° |
| Site 001 Sun elevation | within ±2.1° | +0.05° to +1.52° |
| Site 001 Earth elevation | about −7.5° to +7.5° (libration + colatitude + parallax) | −7.54° to +6.15° |
| Site 001 Earth azimuth | 137.3° ± ~7.5° (spherical azimuth to 0°E, longitude libration) | 129.58° to 144.69° |
| Event discovery | certified, no grazes | certified, 0 grazes |

## What this does and does not establish

- Establishes: time conversion, frame chain (DE421 / MOON_ME), aberration convention, observer-point construction and azimuth convention match an independent reference to better than 0.05 arcsec at two south-polar points, including near-horizon cases.
- Does not establish: terrain horizons (Gate C), event and metric correctness on real data (Gate D), or anything about power or communications. Horizons is an independent reference, not ground truth.

Archived alongside this note: the run JSON, the reference CSV, the comparison report and every raw Horizons response (`horizons_raw/<run_id>/<query_sha256>.json`).
