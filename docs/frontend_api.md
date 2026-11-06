# Backend calls for the new 3D app

For whoever builds `frontend/app`. Use these five calls. The expert endpoints (`/api/analysis`,
`/api/finder`) stay available for the expert drawer, but a visitor should never see their settings.

| need | call |
|---|---|
| sites for the globe pins | `GET /api/reference-sites` (official sites at `GET /api/sites` from 13 Nov) |
| Sun/Earth direction for lighting the globe | `POST /api/sky-geometry` `{start_utc, end_utc, step_min}` |
| **"When can I land here?"** (the main question) | `POST /api/landing-windows` `{site_id, search_start_utc, search_days, mission_days}` |
| **"Check this site"** for a chosen date | `POST /api/check` `{site_id, start_utc, days, panel_height_m}` |
| **compare 2–6 sites/points side by side** (challenge core) | `POST /api/compare` `{places, at_utc, days}` |
| full time series for the surface sky view and time dock | `GET /api/runs/{run_id}` (the check returns `run_url`) |

## `POST /api/sky-geometry`: stars and Earth's face (new 6 Nov)

Two fields were added to `series`; everything else is unchanged.

- **`series.j2000_to_frame`**: one row-major 3×3 matrix per sample, SPICE
  `pxform("J2000", "MOON_ME", et)`.
  - For a star at J2000 RA α, Dec δ, take `v = [cos δ cos α, cos δ sin α, sin δ]` and draw it at
    `M @ v`. This is the same Moon-fixed frame as the Sun and Earth vectors.
  - Stars are at infinity, so no observer offset applies.
  - Stellar aberration (up to 20″) is not applied.
  - In three.js, put the rows into a `Matrix3` with `.set(m[0][0], m[0][1], m[0][2], m[1][0], …)`
    and apply it to the star-field group. Between samples, slerp or just step: the Moon turns about
    0.27° per 30 min.
- **`series.earth.sub_moon_lat_deg` / `sub_moon_lon_east_deg`** (`sub_moon_frame: "IAU_EARTH"`):
  the point on Earth where the Moon is overhead, so it is the centre of the face Earth shows the
  Moon.
  - Rotate the Earth texture so this lat/lon faces the camera on the Moon.
  - Latitude is planetocentric (map latitude differs by ≤ 0.19°, invisible at globe size).
  - It moves west about 15° per hour, so interpolate the longitude with wrap at 360.

Checked by `tools/check_sky_orientation.py`: orthonormal matrices, agreement with SPICE vectors, the
Moon's pole and spin rate, and the sub-Moon point vs JPL Horizons. The limits were fixed before
the first run. Until that run passes, label Earth's face "illustrative".

## Any point on the Moon (new 6 Nov)

`/api/landing-windows` and `/api/check` accept a clicked point instead of a site:

```json
{"latitude_deg": -89.38, "longitude_deg": 201.5, "search_start_utc": "2027-01-01T00:00:00Z"}
```

- Send either `site_id`, or `latitude_deg` and `longitude_deg`. Sending both, or neither, is a 422.
- Latitude is planetocentric. Longitude is east, in −180 to <360; it is folded to [0, 360) and
  rounded to 1e-6°.
- The response's `site` is `{"site_id": "custom-point", "origin": "custom", "name": "Point 89.380° S,
  201.500° E", ...}`.
- Terrain comes from the 240 m regional map only (no 5 m tiles), and a caveat says so. Outside the
  regional map, the response falls back to a flat horizon with its note, as for catalogue sites.
- Results are cached per point. The first answer for a new point takes as long as for a site
  (seconds to about a minute for 90 days); a repeat is instant.
- Suggested UI: click → drop a pin → ask landing windows. Show the caveat chip "240 m terrain".

## "Verify with NASA JPL ↗" (new 6 Nov)

- `/api/check` returns `verify`, for the first sample of the run.
- `/api/landing-windows` returns `verify` on each opportunity (at `best_touchdown_utc`) and on
  `closest_miss`.

```json
"verify": {"utc": "2027-01-03T14:00:00Z", "note": "...",
  "sun":   {"ours_azimuth_deg": 151.2, "ours_elevation_deg": 1.83, "observer_altitude_m": 1952.0,
            "horizons_url": "https://ssd.jpl.nasa.gov/api/horizons.api?format=text&..."},
  "earth": {...}}
```

Suggested UI: a small "Verify with NASA JPL ↗" link next to the Sun height. It opens
`horizons_url` in a new tab: JPL's own plain-text table for that point and second. Next to the
link, show "ours: 1.83°" so a judge can compare the two numbers. Horizons has no lunar hills,
so the matching numbers are the sky position above the level horizon, not sunrise times; `note`
says this in one line.

## `GET /api/site-index`: every site, official first (new 6 Nov; needed from 13 Nov)

`{"official_state": "awaiting_official_source" | "loaded", "official_count": 0, "reference_count": 27,
  "sites": [...official (origin "official", kind "official_challenge_site", group "Official challenge sites")...,
            ...reference (origin "reference")...], "unplaced_official": [], "note": "..."}`

Static bundle: `data/site-index.json`. Until 13 Nov it holds the reference points only.

Some sites carry `analysis_note: {text, evidence, suggested_point?}`: our measured findings, kept
apart from the citation. Show the text in the site panel under the name, in small type, with an
"evidence" link. If `suggested_point` is present, add a button "Try {label}" that opens that
point as a clicked point. Malapert: its published point gets 0% Earth, and the button opens the
crest, which gets 70%. That is the challenge's "small location changes matter" in one click. **Switch
the site loader to this now** (fall back to `/api/reference-sites`), so the official sites appear
on event day without a code change. Labels and banner: an internal document (not published) → Frontend.

## Landing rule R5, minimum Sun height (new 6 Nov)

`/api/landing-windows` takes `min_sun_elevation_deg`: `"auto"` (default), a number, or `null`
(off).
- **auto** = 5° where the Sun can climb past 14°. That is Apollo's lower bound (Apollo landed with
  the Sun 5–14° up). It covers every site within 77.5° of the equator. Near the poles the Sun never
  gets that high, so R5 is off there.
- The response's `rules.min_sun_elevation_deg` is the value used (`null` = off), and
  `rules.min_sun_reference` gives the sources.
- A miss caused by it shows as `sun_high` in `closest_miss.failed_rules`. Text: "Sun high enough to
  light the ground".
- **Effect:** the Apollo 11 site no longer offers "best touchdown with the Sun at −0.22°". Its best
  touchdown now has the Sun at 5° or higher.
- Each opportunity also has `sun_above_horizon_at_best_deg`: the Sun's height above the **local
  horizon**, as opposed to `sun_elevation_at_best_deg`, its height above the level horizontal.
  They differ on ridges and summits. At the Malapert crest the Sun is at −2.9° from the level
  horizontal but above the dipped horizon of a 5 km peak. Show "Sun 1.2° above the horizon" as
  the main number and the level-horizontal elevation as a detail. `closest_miss` has
  `sun_above_horizon_deg`.
- The frontend need not send anything; to expose it, add "Min Sun height: auto / 0° / 5° / 10°"
  to the landing settings.

## `POST /api/compare`: sites and dates side by side (new 6 Nov; challenge core)

```json
{"places": [{"site_id": "reference-lola-site-001"}, {"site_id": "reference-lola-site-004"},
            {"latitude_deg": -89.45, "longitude_deg": 223.2}],
 "at_utc": "2027-01-10T00:00:00Z", "days": 30, "panel_height_m": 2}
```

Send 1–6 places: catalogue sites or clicked points. Each runs the cached one-button check, so
repeated questions are instant. Response:

```json
{"kind": "site_comparison", "at_utc": "...", "days": 30,
 "rows": [{"key": "reference-lola-site-001", "site": {...}, "horizon_mode": "terrain",
   "now": {"sun": {"up": true, "elevation_deg": 1.21, "azimuth_deg": 312.4, "horizon_deg": 0.35},
           "earth": {"up": true, "elevation_deg": 2.9, "azimuth_deg": 2.1, "horizon_deg": 0.8}},
   "sun_next":   {"up": true,  "event": "sunset",   "utc": "...", "in_h": 412.5, "lower_bound": false},
   "earth_next": {"up": true,  "event": "earthset", "utc": "...", "in_h": 330.0, "lower_bound": false},
   "period": {"sunlit_percent": 98.0, "earth_percent": 47.0, "both_percent": 46.0,
              "longest_darkness_h": 12.0, "longest_darkness_lower_bound": false,
              "longest_earth_gap_h": 360.0, "longest_earth_gap_lower_bound": true},
   "limits_all_pass": false, "caveats": [...], "verify": {...}, "run_id": "..."}],
 "leaders": {"most_sunlight": ["reference-lola-site-001"], "longest_until_earthset": [...], ...}}
```

- `sun_next` / `earth_next` give the **time to sunset or sunrise, and to Earthset or
  Earthrise**. The challenge asks for these by name.
- `lower_bound: true` means the event is beyond the analysed days: show "≥ 30 d".
- `none_in_period: true` means it never rises in the period.
- `leaders` names the best key per metric; ties are listed together. There is no combined score.
  Highlight the leader's cell in each row.
- Changing the date or a place means asking again.

## `POST /api/check`

Request: `site_id` (required); `start_utc` (ISO, must end in `Z`); `days` (1 to 60, default
30); `panel_height_m` (0 to 10, default 2). Nothing else is accepted. The server chooses terrain
or flat, the time step and the precision, and reports its choices in `chosen_settings`.

Response (abridged):

```json
{
  "kind": "site_check",
  "site": {"site_id": "...", "name": "...", "latitude_deg": -89.45, "longitude_deg": 222.69},
  "chosen_settings": {"horizon_mode": "terrain", "coarse_step_min": 30, "event_tolerance_s": 10,
                      "sun_observer_height_m": 2, "antenna_height_m": 2, "why": "..."},
  "summary": {
    "headline": "Sunlight reaches a panel 2 m above the ground 61% of the time. Earth is above ...",
    "lines": ["...", "Longest stretch of darkness: 11 d 19 h.", "..."],
    "numbers": {"sunlit_percent": 60.6, "earth_percent": 60.8, "both_percent": 39.8},
    "limits": {"source": "default mission profile ...", "all_pass": false,
               "checks": [{"key": "darkness", "label": "Longest darkness", "text": "11 d 19 h",
                           "value_h": 283.7, "limit_h": 50, "status": "fail", "lower_bound": false}]},
    "bands": {"sun": [{"start_utc": "...", "end_utc": "..."}], "earth": [...]},
    "terrain_status": "terrain-verified",
    "caveats": ["Reference site from published sources, ...", "..."]
  },
  "run_id": "...", "run_url": "/api/runs/...",
  "cache_hit": false, "compute_seconds": 12.3
}
```

How to show it:
* The **headline** is the result card's first line. **lines** come next.
* Each **limits.checks** entry is a chip: `pass` green, `fail` red, `unknown` grey. `unknown`
  means a lower bound: the check window cut the outage, so it may be longer than shown.
* **bands** are the time dock's sunlight and Earth stripes.
* **caveats** are always visible, small, under the result. Never hide them.
* Mast slider: call `/api/check` with `panel_height_m` 0, 1, 2, 5 and 10. Repeats are served from
  the run cache (`cache_hit: true`), so moving the slider back is instant.

Errors: 422 = bad input (`detail` is a list from validation or a string); 503 = the backend is
not configured (no kernels). Show the message; never fall back to made-up numbers.

Responses are gzip-compressed when the browser accepts it.

## `POST /api/landing-windows`

Request: `site_id`, `search_start_utc` (ending in `Z`). Optional, with these defaults:
`search_days` 90 (max 180), `mission_days` 10, `panel_height_m` 2,
`require_earth_at_landing` true, `max_sun_elevation_deg` 20 (null turns that rule off).

Cached (5 Nov): an identical request with the same software, horizon algorithm and kernel/DEM
manifests is answered from `data/cache/landing/` with `"cache_hit": true`. The app asks this for
every site on opening (green pins), so the first opening is slow and later ones are instant.

Response (abridged):

```json
{
  "kind": "landing_opportunities",
  "summary": ["Next landing opportunity at Apollo 11: touch down between 2027-01-14 06:00 and 2027-01-17 12:00 UTC. Landing at ... gives 13.2 days of sunlight; Earth is in view 100% of the mission."],
  "opportunities": [{"touchdown_from_utc": "...", "touchdown_until_utc": "...", "best_touchdown_utc": "...",
                     "daylight_after_best_h": 317.0, "daylight_is_lower_bound": false, "sunset_utc": "...",
                     "sun_elevation_at_best_deg": 1.2, "earth_in_view_during_mission_pct": 100.0}],
  "opportunity_count": 3,
  "closest_miss": null,
  "candidates_failing": {"sun_up": 2100, "daylight": 1650, "earth_up": 0, "low_sun": 900},
  "longest_sunlit_window": {"start_utc": "...", "end_utc": "...", "hours": 341.2, "is_lower_bound": false},
  "rules": {"mission_days": 10, "text": {"sun_up": "Sun above the horizon at touchdown", "...": "..."}},
  "horizon_mode": "flat",
  "caveats": ["..."]
}
```

When there are no opportunities, `closest_miss` says which rules failed and by how much, and
`summary` explains it ("It would give 9.1 days of sunlight; you asked for 10."). Never show a bare
"not possible": show the summary, the closest miss and the rule chips.
