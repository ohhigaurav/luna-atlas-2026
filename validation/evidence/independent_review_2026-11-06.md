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
| 1 | Terrain map chosen by site ID, not by location. Official sites and clicked points never get the 5 m tiles, so the same place can read 69% vs 100% sunlight; landing and check responses do not report resolution | major | confirmed | **open:** footprint-based selection planned; needs a real-DEM run |
| 2 | Cache keys miss site coordinates, `__version__` is inert, and manifests enter by timestamp | major | confirmed | **fixed** 0.7.37 (`cache_keys.py`) |
| 3 | At exactly 90°S the terrain rays collapse onto two meridians | major | confirmed (terrain side) | **fixed** 0.7.37: refused within about 15 m of the pole |
| 4 | "Sunlit %" counts any sliver of the Sun; Gate E validated mean disc fraction, a different quantity | major | confirmed | **open:** disc-weighted metric and relabel planned |
| 5 | R5 off between 77.5° and about 84.5°S (IM-1, IM-2); "best" is the first sliver of sunrise; cutoff logic wrong; min ≥ max not refused | major | confirmed (synthetic) | **fixed** 0.7.37 (R5 v2) |
| 6 | Docs claim more than the evidence supports: C9 "validated", frontend ✅ rows checked only on the test backend, forecast "agrees with the site panel", manifest datum text | minor–major | confirmed | **open:** wording fixes planned |
| 7 | Terrain effectively starts at about 66.6°S, not 60°S (200 km rays leave the raster) | minor | confirmed (arithmetic) | **partly fixed:** honest text in 0.7.37; ray capping not done |
| 8 | Event-day distance sanity check covered polar sites only | minor | confirmed | **fixed** 0.7.37 |
| 9 | Expert API can request a horizon of about 73 million cells under the global lock | minor (local) / major (exposed) | confirmed by reading | **fixed** 0.7.37: 5 M sample budget |
| 10 | 0.5° azimuth bins: narrow ridges missed; "5 m" overstates the lateral detail used | minor | plausible, unmeasured | **open:** sensitivity run planned |
| 11 | Forecast Sun mask at 0 m, site panel at 2 m (2 m doubles Site 001's sunlight per WAC evidence) | minor | confirmed | **open:** label now; re-bake at 2 m optional |

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
