# Location-sensitivity scans: LOLA Site 004 and Site 001 (2026-10-28)

Run by the team on the project laptop (Python 3.14.7, `.venv`) at commit `7b86d24`, immediately
after `./scripts/verify_project.sh` passed (163 tests, ruff, mypy --strict, JS, catalogue).

Command: `python tools/location_scan.py reference-lola-site-004 reference-lola-site-001`

Settings: 2027-01-01T00:00Z .. 2027-01-31T00:00Z, 30 min coarse step, 1 s event tolerance,
terrain horizon (0.5° azimuth, 200 km, 5 m near step to 8 km, 240 m beyond), observer and
antenna 2 m, Earth clearance 0°. Grid: 300 m radius, 100 m spacing, 29 points.
Every point: certified discovery, complete horizon coverage.

| | Site 004 (scan `83fad0f2-e345-491f-a9da-5a6de4626c57`, 293 s) | Site 001 (scan `1fba6d63-14ef-4d66-b56c-6511d09d15dd`, 287 s) |
|---|---|---|
| Sunlit %: published point | **0.0** (lowest of all 29) | 69.3 (above 38 % of points) |
| Sunlit %: min / median / max | 0.0 / 59.6 / 100.0 | 46.6 / 77.4 / 100.0 |
| Earth-visible %: published point | **0.0** | 34.0 (above 10 %) |
| Earth-visible %: min / median / max | 0.0 / 42.4 / 44.8 | 0.0 / 44.6 / 46.8 |
| Sun + Earth %: published / median | 0.0 / 19.0 | 21.2 / 33.2 |
| Ground: published / range (m) | 1728.5 / 1666.2 .. 1735.9 | 1954.6 / 1932.6 .. 1957.4 |

Site 004 sunlit map (north up, east right, 100 m cells, centre bracketed):

```
              -300  -200  -100    +0  +100  +200  +300
      +300                        68
      +200            48    97    97    60    57
      +100            51    98   100    73    63
        +0      50    52    96 [  0]   100    59    53
      -100            53    49    77    69    63
      -200            49    50   100    39    47
      -300                        82
```

## Findings (facts from these runs)

1. At Site 004 every point 100 m from the published coordinate on the four axes is 96-100 %
   sunlit and ~7 m higher (1735 m vs 1728.5 m); the published point is 0 %. This matches the
   horizon diagnostic: a 6-8 m rim at ~100 m surrounds the published point.
2. Earth visibility falls to 0 % on the western side of both sites, where the ground drops by
   20-60 m; Earth is in the south-east (azimuth ~130-145° at Site 001), so the slope blocks it.
3. Points on the local crest exceed the flat-sphere Earth fraction (44.8 % vs 41.8 % flat at
   Site 004) because an elevated observer sees below the 0° geometric horizon.
4. A single-coordinate result is not representative at 100 m scale at either site.

## Not established

- Whether the ~7 m, ~200 m-wide depression at Site 004 is real topography or an interpolation
  product: ~90 % of Product 78 5 m pixels contain no LOLA spot. `tools/dem_quality.py` (LDEC
  spot counts and TOTERR uncertainty) is the check; not yet run on real files.
- Grid convergence: 100 m spacing is comparable to the features. A 50 m scan is pending.
- Sensitivity to azimuth step and radial step on real data (Gate D).
- Malapert was excluded: it is covered only by the 240 m DEM, whose near-field sampling
  underestimates the northern horizon by ~2° until D-19 is decided.
