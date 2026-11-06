# Backend calls for the new 3D app

For whoever builds `frontend/app`. Use these five calls. The expert endpoints (`/api/analysis`,
`/api/finder`) stay available for the expert drawer, but a visitor should never see their settings.

| need | call |
|---|---|
| sites for the globe pins | `GET /api/reference-sites` (official sites at `GET /api/sites` from 13 Nov) |
| Sun/Earth direction for lighting the globe | `POST /api/sky-geometry` `{start_utc, end_utc, step_min}` |
| **"When can I land here?"** (the main question) | `POST /api/landing-windows` `{site_id, search_start_utc, search_days, mission_days}` |
| **"Check this site"** for a chosen date | `POST /api/check` `{site_id, start_utc, days, panel_height_m}` |
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
