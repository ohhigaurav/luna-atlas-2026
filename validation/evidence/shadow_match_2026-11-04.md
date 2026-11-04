# Shadow match vs LRO WAC photos, 2026-11-04

Run by the team with `tools/shadow_match.py` at `c64cbaf` (horizon fix included). Frames, scoring disc
and pass rules were fixed in the tool at `b2ae4e4`, before the first run.

**Gate:** 4/4 agree with the production horizon. Site 001 +2.00°, Site 004 +2.72°, Shackleton floor
−21.84° (dark), rim area +3.46°. The first attempt stopped at this gate and exposed the 0 m horizon
bug (`horizon_origin_bug_2026-11-04.md`). Nothing was scored before the fix.

**Result: PASS. 5 of 6 frames pass** (rule: at least two thirds).

| frame (UTC) | Sun toward | Sun height at pole | Otsu | agreement | shadow IoU | verdict |
|---|---|---|---|---|---|---|
| 2009-09-20 08:50 | 164.7° E | +1.33° | 97 | 99.1% | 0.99 | PASS |
| 2009-09-24 07:07 | 116.7° E | +1.39° | 109 | 94.0% | 0.94 | PASS |
| 2009-09-28 00:01 | 71.5° E | +1.45° | 91 | 95.7% | 0.95 | PASS |
| 2009-10-02 00:15 | 22.7° E | +1.49° | 84 | 82.7% | 0.74 | FAIL |
| 2009-10-10 00:42 | 285.1° E | +1.51° | 76 | 93.7% | 0.92 | PASS |
| 2009-10-15 01:24 | 223.8° E | +1.51° | 59 | 99.7% | 1.00 | PASS |

Disc: 15 km around the pole, observer 0 m, 200 m band at modelled shadow edges excluded (240 m DEM).

## Read with care

* Most of the disc is in shadow at a ~1.4° Sun, so high agreement is partly easy. The post hoc
  diagnostics added after this run report the photo's shadow fraction (what an "everything dark"
  guess would score), the IoU of the lit areas, and the scores including the excluded edge band.
  To be added from the next run's output. Until then, quote the verdict and the table, not
  "99% accurate".
* The one failure (2 Oct) has the Sun coming from the Earth-facing side (22.7° E). Where it fails
  will show in its difference picture (red = we say lit, blue = we say dark).
* Resolution: the 240 m DEM sets what can match. Edges within 200 m are not scored.
