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

## Next test (defined, not yet run)

`tools/wac_manypoint.py` implements the many-point test above. Its pixel selection, gate and pass
criterion are written in the tool's docstring and were committed before any run; see
CHANGELOG 0.7.6-dev. Results will be added here whether they pass or fail.
