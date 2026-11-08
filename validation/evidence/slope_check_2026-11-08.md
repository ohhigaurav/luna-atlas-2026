# Gate S: computed slope vs PGDA published slope — PASS

Run 2026-11-08T05:48:23Z, commit 4aba13c42079d2eaa2754164d07b171447f0de03 (dirty). Pass rule `validation/slope_tolerances.json` (sha256 b22d1a735d6a5f45…, predeclared 2026-11-07T14:12:20Z, status at run: approved_before_run).

Rule: same grid; coverage ≥ 99%; |median diff| ≤ 0.25°; p95 |diff| ≤ 1.5°; ≤ 5% disagreement at 8.0°. Domain: pixels within 1500 m of the site point.

| Site | S1 grid | coverage | median diff | p95 abs diff | disagree at limit | checks |
|---|---|---|---|---|---|---|
| reference-lola-site-001 | True | 1.000 | -0.002° | 0.696° | 0.012 | S2:ok S3:ok S4:ok S5:ok |
| reference-lola-site-004 | True | 1.000 | -0.004° | 0.921° | 0.004 | S2:ok S3:ok S4:ok S5:ok |

Diagnostics (not part of the verdict): central differences and whole-tile statistics are in the .json.

Meaning: the computed slope may be shown with 'checked against the NASA PGDA slope map at Sites 001 and 004'.
