# Terrain resolution changes the answer at Site 001 (5 m tile vs 240 m map), 2026-11-06

Found by the team's `tools/try_compare.py` runs (`compare.log`, `compare2.log`) at `080a8d8`, when a
clicked point was compared with the catalogue site. The window is 2027-01-10 + 30 days, with the
panel and antenna at 2 m.

| place | terrain | ground | Sun now: horizon | Sun 30 d | longest dark | Earth 30 d | Earth now: horizon |
|---|---|---|---|---|---|---|---|
| Site 001 (89.45°S, 222.69°E) | **5 m** tile + regional | 1954.6 m | −2.51° | **69%** | 8 d 21 h | 36% | +1.56° (down) |
| same coordinates as a clicked point | **240 m** only | 1950.5 m | −1.72° | **100%** | 0 h | 53% | −1.08° (down) |
| 150 m east (forecast's brightest pixel) | 240 m only | 1950.0 m | −0.08° | 100% | 0 h | 56% | −1.84° (up) |

**At the same coordinates, only the terrain map differs, and Site 001 goes from 69% to 100%
sunlight and from 36% to 53% Earth.** The 150 m move hardly matters on the 240 m map (100%
vs 100%, Earth 53% vs 56%). The gap is resolution, not position.

**Consistent with earlier evidence.** In `dem_quality_2026-10-28.md`, Site 001's horizon at
az 135–210° is set by terrain only 20–30 m away (horizon 1.0–1.8°). A 240 m grid averages that
bump away. The 5 m ground is also 4 m higher than the 240 m ground at the same point: the ridge
crest is flattened.

**Which is right?** Neither is checked against images at this scale. The 5 m tile is about 90%
interpolated (PGDA), and Site 001 is sensitive to its height error (`dem_quality`, point 3).
The 240 m map passed the 15 km-scale LRO shadow match and the Goddard comparison, but those
cannot see 20–30 m bumps. The WAC many-point test found the brightest pixels modelled *low*
(−16.7 points), so 240 m is not simply optimistic everywhere.

## Consequences (acted on)

- **Clicked points, the forecast, the Earth layer and the light map all use 240 m.** At Site 001
  the forecast shows the pixel lit all of January while the site panel (5 m) says 69%. The app
  must label which terrain each number uses. Compare rows now carry `terrain.finest_resolution_m`.
- **Correction to `shadow_movie_2027-01_2026-11-05.md` and `earth_movie_2026-11-06.md`:**
  - "the brightest pixel is Site 001" is true only on the 240 m map;
  - at 5 m, Site 001 has 8 d 21 h of darkness from 10 Jan;
  - claims about Site 001 must quote the 5 m result.
- `tools/resolution_check.py` measures the size of this effect over 2 × ~49 points (definition
  fixed before its run). The custom-point caveat and the forecast label will quote its numbers.
