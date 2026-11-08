# Independent review, 2026-11-06

Requested by the team ("any independent NASA engineer type"). A fresh agent with no access to how
the project was built reviewed the repository at `cb9f696`, read-only, as a hostile design review
by a flight-dynamics / mission-design engineer. It read the code and evidence, ran the unit tests
(340 passed; only the rasterio-dependent bootstrap test failed) and throwaway scripts. It could
not run real kernels or DEMs.

The reviewer's summary: no show-stoppers; four major issues to fix before 13 Nov; the geometry
itself held up.

## Findings and status

| # | Finding | Severity | Reviewer's confidence | Our status |
|---|---|---|---|---|
| 1 | Terrain map chosen by site ID, not by location. Official sites and clicked points never get the 5 m tiles, so the same place can read 69% vs 100% sunlight; landing and check responses do not report resolution | major | confirmed | **fixed in code** 0.7.38: tiles chosen by location (`footprint_stereo_m`, `select_by_footprint`); `terrain.finest_resolution_m` and a 240 m caveat on every answer; event-day table shows it. **in effect** since footprints were written (6 Nov 19:30 IST): Site 001's coordinates as a clicked point now give 69% on 5 m, as Site 001 does |
| 2 | Cache keys miss site coordinates, `__version__` is inert, and manifests enter by timestamp | major | confirmed | **fixed** 0.7.37 (`cache_keys.py`) |
| 3 | At exactly 90°S the terrain rays collapse onto two meridians | major | confirmed (terrain side) | **fixed** 0.7.37: refused within about 15 m of the pole |
| 4 | "Sunlit %" counts any sliver of the Sun; Gate E validated mean disc fraction, a different quantity | major | confirmed | **fixed** 0.7.38: `sun_disc_percent` (mean visible disc fraction, the Gate E quantity) in check and compare; headline relabelled "some of the Sun is visible" |
| 5 | R5 off between 77.5° and about 84.5°S (IM-1, IM-2); "best" is the first sliver of sunrise; cutoff logic wrong; min ≥ max not refused | major | confirmed (synthetic) | **fixed** 0.7.37 (R5 v2) |
| 6 | Docs claim more than the evidence supports: C9 "validated", frontend ✅ rows checked only on the test backend, forecast "agrees with the site panel", manifest datum text | minor–major | confirmed | **fixed (docs)** 0.7.38: C9 rewritten with its limits; frontend-only ✅ rows now 🟢; manifest datum text corrected. Forecast wording handed to the frontend (PRD) |
| 7 | Terrain effectively starts at about 66.6°S, not 60°S (200 km rays leave the raster) | minor | confirmed (arithmetic) | **partly fixed:** honest text in 0.7.37. **Ray capping deliberately not done (decision 8 Nov):** capped rays would drop the distant terrain that matters most for a low Sun; 60–66.6°S keeps the flat fallback with a note, and the event-day check lists official sites in that band |
| 8 | Event-day distance sanity check covered polar sites only | minor | confirmed | **fixed** 0.7.37 |
| 9 | Expert API can request a horizon of about 73 million cells under the global lock | minor (local) / major (exposed) | confirmed by reading | **fixed** 0.7.37: 5 M sample budget |
| 10 | 0.5° azimuth bins: narrow ridges missed; "5 m" overstates the lateral detail used | minor | plausible, unmeasured | **measured:** 0.00-point difference at Sites 001 and 004 (Jan 2027); keep 0.5° (pre-registered rule) |
| 11 | Forecast Sun mask at 0 m, site panel at 2 m (2 m doubles Site 001's sunlight per WAC evidence) | minor | confirmed | **label handed to frontend** (PRD); a 2 m re-bake is optional (about 3.5 h) |

## Our assessment of the findings

We agree with all eleven. None was dismissed.
- **Most consequential:** findings 1 and 4. They decide whether two numbers shown side by side mean
  the same thing.
- **Finding 6:** fair. Several "✅" rows describe features built against the test backend that
  have not yet been seen working on real data in the app.

## Checked and found sound by the reviewer (summary)

- SPICE geometry: `azlcpo`, MOON_ME, LT+S, clockwise azimuth; the observer at 1737.4 km + DEM +
  height.
- Horizon geometry: the apparent-elevation formula includes curvature; great-circle rays are
  projected through the raster CRS.
- Datum agreement between the 5 m tiles and the 240 m map: about 0.3–0.4 m median.
- NoData handling; the 2.2 origin fix.
- Visibility rules: Sun by upper limb, Earth by centre, consistent everywhere; Earth's direction
  is computed per pixel.
- Event bisection and grazing handling; window merging across chunks; lower-bound flags.
- Compare, leaders, ellipse, verify-link parameters, `run_id` path check, importer sign
  safeguards, HTTPS allowlist.
- Pre-registration practice, with post-hoc changes disclosed.
- Malapert: a pipeline-wide east/west mirror is excluded by Gate E's Spearman 0.99.

## Follow-up run, a development machine, 2026-11-06 19:30 IST (raw: `review_followup_2026-11-06.log`)

- **Tests:** 383 passed, 0 failed. The full suite now passes on the real environment, including
  the bootstrap test.
- **Finding 1 takes effect:**
  - `set_dem_footprints.py` checked both 5 m tiles' projections and recorded their footprints
    (16 × 16 km each; Site 001 tile centre 89.463°S, 222.51°E; Site 004 tile centre 89.767°S,
    188.13°E).
  - Same compare as before (2027-01-10 + 30 d):

    | place | terrain | Sun | Earth | longest dark |
    |---|---|---|---|---|
    | Site 001 | 5 m | 69% | 36% | 8 d 21 h |
    | clicked point at Site 001's exact coordinates | **5 m** (was 240 m: 100%) | **69%** | **36%** | **8 d 21 h** |
    | clicked point 150 m east (forecast's brightest pixel) | **5 m** (was 240 m: 100% / 56%) | **74%** | 56% | ≥ 6 d 19 h |

  - The same place now gets the same answer whatever its origin.
  - On 5 m terrain the forecast's brightest pixel gets 74% Sun, not 100%. The forecast remains a
    240 m view, labelled as such.
- **Finding 10, measured:** Sites 001 and 004 at a 0.25° vs 0.5° azimuth step, Jan 2027:
  - sunlit, disc-averaged and Earth % are identical to two decimals (001: 69.35 / 65.94 / 33.99;
    004: 0 / 0 / 0);
  - pre-registered decision: **keep 0.5°**;
  - caveat: the report does not record the bin count of each run, so "the 0.25° run really used
    1,440 bins" rests on the code path (the horizon cache key includes the step), not on a recorded
    number.
