# Model vs LROC observed illumination (WAC_POLE_ILL_PCT_SOUTH_100M) — 2026-11-01

Run by the team on a development machine, `site-catalogue-import` at `6a3f104`, with
`tools/compare_wac_illumination.py` (terrain mode, 30 min step, observer 2 m).

Reference map: `WAC_POLE_ILL_PCT_SOUTH_100M.IMG`, SHA-256
`30b35ae2de695198f62afe2845c3a67cbc4975dca199be3c848d931414aced5f`; PDS, 1214 x 1214 float32,
south-polar stereographic on a 1737.4 km sphere, 100 m pixels, corner (-60700, 60700) m, values
0-71.6 %. Observed fraction of 3807 WAC images (2010-02-15 to 2011-02-05) in which each pixel
was lit (Speyerer & Robinson 2013). Model period: same dates, six 59-day chunks.

Criterion fixed in the tool before the run: score a site only if the WAC 3x3 (300 m) spread is
<= 10 percentage points; pass if |model upper-limb % - WAC centre-pixel %| <= 10 pp.

| site | WAC % | WAC 3x3 range | model limb % | model centre % | diff (pp) | verdict |
|---|---|---|---|---|---|---|
| LOLA Site 001 (5 m DEM) | 28.1 | 20.0-39.2 | 56.3 | 51.7 | +28.2 | UNSCORED |
| LOLA Site 004 (5 m DEM) | 35.0 | 31.2-57.4 | 0.0 | 0.0 | -35.0 | UNSCORED |
| Shackleton reference point | 0.0 | 0.0-0.0 | 0.0 | 0.0 | +0.0 | PASS |
| de Gerlache reference point | 0.1 | 0.0-0.1 | 0.1 | 0.0 | +0.0 | PASS |
| Sverdrup reference point | 0.0 | 0.0-0.0 | 0.0 | 0.0 | +0.0 | PASS |
| Henson reference point | 0.1 | 0.0-0.4 | 1.0 | 0.2 | +0.9 | PASS |

Report: `data/derived/wac_comparison_terrain_20261101T152904Z.json` (on that machine).

## What this shows

* The four passes are permanently or nearly permanently dark points. They show the model does
  not invent sunlight in deep shadow; they are weak tests of lit terrain.
* **Lit-site illumination is not validated by this run.** Both lit sites were unscored by the
  pre-set rule because illumination varies by 19-26 pp within 300 m there.
* Site 004: the model point is 0 % for the whole year. This matches the 28 Oct finding that the
  published point sits in a ~7 m deep, ~200 m wide depression in the 5 m DEM, with 96-100 %
  sunlit points 100 m away (`location_scan_2026-10-28.md`, January 2027). A 100 m WAC pixel
  averages the depression with its rims, so the gap is consistent with point vs pixel; it is
  not shown to be a model error, nor shown not to be.
* Site 001: the model is about twice the observation (56 % vs 28 %; the whole 3x3 is 20-39 %).
  Even "Sun centre visible" (51.7 %) exceeds every neighbouring pixel. This is an unexplained
  discrepancy.

## Candidate causes for Site 001, in test order

1. Observer height: the model looks from 2 m; WAC sees the surface. With the Sun grazing the
   horizon, metres of height change illumination strongly (Mazarico et al. 2011 note that
   ~10 m gains can dramatically improve average illumination). Test: rerun at 0 m
   (`--observer-height 0`, added after this run). Same criterion.
2. Definition of "lit": a WAC pixel needs enough light to appear lit; the model counts any
   sliver of the solar disk. Partly bounded by the centre-visible column.
3. WAC sampling: LROC states the percentage map may be biased by non-uniform image timing and
   provides a time-weighted product (`WAC_POLE_ILL_TWI_SOUTH`). Test against that too.
4. Point vs area: compare the model averaged over the 100 m pixel (or 300 m window) instead of
   one point.
5. DEM height error near Site 001, where the horizon is 1.0-1.8 deg and controlled 20-30 m away
   (`dem_quality_2026-10-28.md`).

Until these are run, do not claim agreement with observed illumination at lit sites.

## Rerun at observer height 0 m (same day, after the table above)

Command: `tools/compare_wac_illumination.py --observer-height 0 --sites reference-lola-site-001 reference-lola-site-004`
(commit `986577b`). Same period, map, step and criterion. Report:
`data/derived/wac_comparison_terrain_h0m_20261101T153739Z.json` (on that machine).

| site | WAC % | WAC 3x3 range | model limb % at 2 m | model limb % at 0 m | model centre % at 0 m | diff at 0 m (pp) | verdict |
|---|---|---|---|---|---|---|---|
| LOLA Site 001 | 28.1 | 20.0-39.2 | 56.3 | 28.7 | 25.9 | +0.6 | UNSCORED |
| LOLA Site 004 | 35.0 | 31.2-57.4 | 0.0 | 0.0 | 0.0 | -35.0 | UNSCORED |

### What this shows

* At Site 001, putting the observer on the ground (as the camera sees it) instead of 2 m above
  it halves the modelled sunlight, from 56.3 % to 28.7 %, which lands within 0.6 percentage points
  of the observed 28.1 %. Observer height was candidate cause 1; it accounts for essentially all
  of the earlier gap at this site.
* A 2 m height difference doubling the sunlit fraction is itself a strong, mission-relevant result:
  at grazing sun angles, a lander's panel height changes power availability as much as its
  location does.
* Site 004 does not change (0 % at 0 m and 2 m): the point is inside the depression described in
  `location_scan_2026-10-28.md`, so the gap there is point vs pixel, not height.

### What this does not show

* It is still **not a validation by the pre-set rule**: Site 001 stays UNSCORED (3x3 spread 19 pp).
  The criterion is unchanged after seeing results.
* One site agreeing, after a cause was chosen to test, can be coincidence. A test with many
  points across the two 5 m tiles (model at 0 m averaged over each WAC pixel vs that pixel) is
  needed before claiming agreement with observed illumination. Its criterion must be fixed before
  it runs.

## Many-point test — FAIL (2026-11-01)

Run by the team with `tools/wac_manypoint.py` at `2b0e1de` (criterion committed there before the run).
Report `data/derived/wac_manypoint_20261101T171954Z.json`; checkpoint
`data/derived/wac_manypoint_cbf7fcf8080eaf57.jsonl` (on that machine). The run used 900 production
terrain horizons at 0 m, about 4.3 s each.

**Gate (fast path vs production at the published points): PASS.** Site 001: 28.71 % vs 28.720 %.
Site 004: 0.00 % vs 0.0 %.

Pixels: 50 per tile (10 per stratum) from 2823 (Site 001) and 2800 (Site 004) candidates.

| group | n | median (model − WAC) | mean | share within 10 pp | Spearman |
|---|---|---|---|---|---|
| **ALL (scored)** | 100 | **−12.0** | −15.2 | **41 %** | **0.89** |
| Site 001 tile | 50 | −12.3 | −14.7 | 36 % | 0.91 |
| Site 004 tile | 50 | −11.5 | −15.6 | 46 % | 0.89 |
| WAC 0–5 % | 20 | −1.5 | −1.8 | 100 % | 0.29 |
| WAC 5–20 % | 20 | −6.5 | −7.5 | 80 % | 0.68 |
| WAC 20–35 % | 20 | −12.1 | −13.9 | 20 % | 0.51 |
| WAC 35–50 % | 20 | −18.4 | −18.2 | 5 % | 0.31 |
| WAC ≥ 50 % | 20 | −33.0 | −34.4 | 0 % | 0.10 |

Criterion: median within ±5 pp **fails** (−12.0); ≥ 70 % within 10 pp **fails** (41 %);
Spearman ≥ 0.80 passes (0.89); n ≥ 30 passes. **Verdict: FAIL.** This stands; the thresholds are
not revisited.

### What this shows

* **Ranking is right; the level is not.** The model orders ground from dark to bright much as LROC
  saw it (Spearman 0.89 on both tiles), but at 0 m observer height it **under-predicts sunlight**,
  and the shortfall grows with brightness: about −2 pp in near-permanent shadow and about −33 pp
  where LROC saw ≥ 50 %. Both tiles behave the same way, so this is not one site's DEM.
* **The single-site agreement at Site 001 (28.7 % vs 28.1 %) was not representative.** Across 100
  pixels the 0 m model is biased low. Taken together with the 2 m run (56.3 % at Site 001),
  the camera-equivalent result lies between 0 m and 2 m at that site. That is a sensitivity
  statement, not a calibration. **Do not present "the model matches LROC" anywhere.**
* Within-stratum Spearman values are low because each stratum covers a narrow WAC range. They
  are not evidence on their own.

### Candidate causes, to be tested with criteria fixed before each run

1. **Near-field terrain at 0 m.** With the Sun within ~1.5° of the horizon, a 0.3 m bump
   10 m away subtends 1.7°. At exactly 0 m the horizon is set by sub-metre DEM detail and
   interpolation within tens of metres. Earlier, the Site 001 horizon was found to be
   controlled 20–30 m away (`dem_quality_2026-10-28.md`). That would bias the model low, most
   where the Sun grazes, i.e. at the brightest polar ground. Test: relief vs bias (diagnostics
   script); then a height or near-field sensitivity run, reported as sensitivity, not as a fit.
2. **WAC "lit" is photometric and pixel-wide.** A 100 m pixel can count as lit when only part
   of it is lit, while the model averages its points. Test: compare WAC with the best sub-point
   and with "any sub-point lit" (needs per-time output).
3. **WAC timing bias.** LROC notes that irregular image timing can bias the percentage map and
   publishes a time-weighted product. Test: the same tool with `--map` set to the time-weighted
   map (`tools/wac_manypoint.py` now refuses maps whose pixels are not 100 m).

The post hoc breakdown (`tools/wac_manypoint_diagnostics.py`) is descriptive only. It will be
added below when run.
