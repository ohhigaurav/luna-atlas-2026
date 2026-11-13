# Scientific validation status — 0.7.45 (8 Nov 2026)

Each gate's pass rule was fixed before its run; FAILs stay recorded. Evidence is in `validation/evidence/`.

| Gate | What was compared | Result | Evidence |
|---|---|---|---|
| B geometry | SPICE Sun/Earth azimuth, elevation, range vs JPL Horizons; 2 south-polar points, 20 epochs (8 near the horizon) | **PASS**: worst 0.021″ az, 0.041″ el, 0.011 km | `gate_b_geometry_2026-10-28.md` |
| D real missions | Our model vs reported events of 7 missions | **6/7 PASS.** Apollo 11/14/15 Sun and Earth at landing within 0.21° of NASA's Apollo Lunar Surface Journal; SLIM sunset; Chandrayaan-3 sunset and sunrise (terrain); Chang'e-4 Earth never up. **FAIL kept:** Blue Ghost 1 sunset +2.41 h on a flat horizon (limit ±2 h) | `mission_events_2026-11-02.md` |
| Shadows | Terrain shadows vs LRO WAC photos of the pole, 6 frames | **PASS** 5/6 frames (rule ≥ 2/3) | `shadow_match_2026-11-04.md` |
| E Goddard maps | Average Sun and Earth visibility and permanent shadow vs NASA Goddard PGDA 69, 48 points | **PASS**: Sun median −0.016, Earth −0.045 (fraction of time), PSR agreement 94% | `goddard_maps_2026-11-05.md` |
| Earth layer | Forecast Earth map vs the production answer at the same pixels | **PASS** 99.86% of 1,440 pixel-frames (100% of clear cases) | `earth_movie_2026-11-06.md` |
| Sky orientation | Frame checks; Earth's sub-Moon point vs Horizons | **FAIL kept** (A3: our limit ignored the 18.6-year pole term; the frame matches IAU 2015 to 0.001°, checked after the fact). Earth's face: PASS, within 0.1° at 13 dates | `sky_orientation_2026-11-06.md` |
| S slope | Our Horn slope vs PGDA's published slope maps, Sites 001/004, 1.5 km | **PASS**: median −0.002° / −0.004°, p95 0.70° / 0.92° (limit 1.5°) | `slope_check_2026-11-08.md` |
| P sunlight power | Sunlight on a panel (W/m², before panel efficiency) vs the Goddard-checked disc visibility and physical bounds; Sites 001/004, 3 × 30 days. **Consistency check, not independent validation** | **PASS** 6/6 rows: full-disc peak 1341–1415 W/m² (bounds 1300–1416), mean / (1361 × disc) within the distance factor, flat panel ≤ 2.8% of vertical, Site 004 zero | `power_check_2026-11-13.md` |

**Measured, no pass rule:** the app's "verify with NASA JPL" link at Apollo 11, 2027-01-13 17:00, Sun +0.1″ and Earth −0.2″ from Horizons, i.e. display rounding (`apollo11_verify_link_2026-11-08.md`); DEM quality at the horizon-controlling terrain (`dem_quality_2026-10-28.md`);
PGDA clone check and observer-height sweep (`clone_check_and_mast_height_2026-10-28.md`); 0.25° vs 0.5°
azimuth bins, 0.00-point difference at Sites 001/004 (independent review #10); 5 m vs 240 m terrain
at Site 001, 69% vs 100% sunlight (`resolution_site001_2026-11-06.md`); the Malapert published point
sits on the hidden flank (`malapert_earth_2026-11-06.md`).

**Independent review** (`independent_review_2026-11-06.md`, hostile design review, 11 findings):
9 fixed, 1 measured (#10), 1 deliberately not fixed (#7, below).

## Not established — say so wherever it matters

- **Landing rules R1–R5 are design choices** taken from Apollo and Blue Ghost practice, not measured
  quantities. The app shows them with every answer.
- **Flat horizon** (north of 60°S, or as a fallback): sunrise and sunset can be off by hours
  (Blue Ghost 1: +2.4 h). Every answer says 5 m / 240 m / flat.
- **Terrain resolution changes answers** (Site 001: 69% sunlight on 5 m, 100% on 240 m).
- **Times:** window edges to 30 min, event times to 10 s.
- **Uncertainty:** answers come from the nominal DEM, with no clone-ensemble spread on the percentages.
- **Slope** is not a hazard certification: features under ~10 m are not resolved, and it was compared
  only on the two 5 m tiles.
- **Earth in view is not a guaranteed radio link.** There is no thermal model, and the battery view is
  an illustrative power model.
- **60°–66.6°S (review #7, decision 8 Nov):** the 200 km terrain rays leave the 240 m map, so
  answers fall back to a flat horizon with a note. Capping the rays at the map edge would drop the
  distant terrain that matters most for a low Sun, so it was not done before submission. The event-day
  check lists any official site in that band.

---

## History: the initial checklist (0.7.2-dev, October 2026; superseded by the table above)

### What was verified in that checkout

- 119 unit/API tests pass, including synthetic numerical edge cases and mocked SPICE/API flows.
- FastAPI exposes the compare, finder, source/assumption, terrain-inventory, saved-run and export endpoints.
- Kernel and DEM manifests fail closed when real inputs or required review flags are missing.
- Provenance captures configuration/manifests/hashes for computed runs.
- The browser-local timestamp controls are converted to explicit UTC instants before API calls.
- Terrain horizons preserve missing/NoData semantics; incomplete horizons are not silently promoted to verified terrain.

### What was not verified then (most items closed since: see the table)

- No real SPICE kernels are present in the packaged checkout; the kernel manifest starts `not_configured`.
- No official 2026 challenge catalogue has been imported. Literature/reference points are a separate set.
- No real DEM raster is bundled/registered in the default checkout.
- No real SPICE frame/coverage preflight or JPL Horizons golden comparison has been run in this build environment.
- No real-terrain horizon result has passed CRS, frame, radial coverage, elevation-unit, vertical-datum or convergence review.
- Product 104 has been added to the source register as a potential supplement only. It has not been downloaded/registered or presumed to cover the 2026 official sites.
- DEM resolution sensitivity is a required open validation gate. Zhong et al. (2026) reported mean cumulative relative illumination increases of 27.5% (5 m) and 65.1% (20 m) versus a 1 m baseline for one Chang’e-7 study region; these are not universal correction factors. The current planner does not yet run clone ensembles or a complete multi-resolution sensitivity study.
- The scientific engine has not undergone an independent expert review. The test suite is necessary regression evidence, not scientific acceptance.

### Required pre-release gates (as written then)

1. Import the unmodified official challenge site file, preserving all original fields and SHA-256.
2. Fetch the pinned NAIF kernel candidates from NAIF over HTTPS and record exact versions, hashes, load order and coverage; verify the BPC stored frame and the transform to `MOON_ME` over every requested epoch.
3. Use explicit, pinned leap-seconds, SPK, PCK, frame and aberration conventions. Preserve raw Horizons queries/responses, settings and retrieval time.
4. Compare SPICE topocentric azimuth/elevation against JPL Horizons at predeclared epochs across at least two sites, including a near-horizon case, with a tolerance approved before viewing differences.
5. Verify raster CRS, lunar frame/radius, axis order, pixel registration, scale/offset, NoData, elevation units and vertical datum for every terrain asset. Do not infer datum equivalence from a non-NoData sample.
6. Confirm site-centred coverage along every azimuth to the configured range. Use near-field high-resolution DEM where available and far-field products only under their declared range/resolution contract.
7. Run terrain clones/uncertainty ensembles where available; report distributions and sensitivity of event times/metrics, not only a single best estimate.
8. Check event-time convergence by halving the coarse step; demonstrate tangent/grazing-event handling and report unresolved edge intervals.
9. Recompute exported metrics independently from event windows; include time boundaries and truncated-outage lower bounds.
10. Run clean-install, offline, performance and user usability tests. Keep open gates visible in the release report.

### Mathematical contracts in scope

The horizon equation and visibility definitions are in `docs/modelling_contract.md`. For each azimuth, terrain elevation is transformed to apparent angle on the declared spherical Moon; the horizon is the maximum valid apparent elevation. Missing/uncovered rays are incomplete. Sun visibility uses upper-limb margin `e_s + asin(R_sun/r_sun) - H(a_s)`; Earth-centre visibility uses `e_E - H(a_E) - m`. Events are roots of those margins with bracket/refinement and grazing-event diagnostics. Metrics are based on refined windows and the requested interval denominator; a boundary-truncated outage is a lower bound. The date finder clips candidate mission windows to `[start, start + duration]` and reports individual constraint violations. None of these definitions certifies safe landing, actual power generation, or RF link availability.

### Environment note (build container, October)

Outbound DNS/network access was unavailable in the build container, so this package did not acquire fresh NAIF binaries or NASA rasters. The repository scripts are prepared to fetch the pinned candidates from their official HTTPS publishers on a connected machine. The official challenge data release is separate and should be ingested only from its authoritative source.
