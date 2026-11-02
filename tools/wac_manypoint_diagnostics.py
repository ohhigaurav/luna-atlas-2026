#!/usr/bin/env python3
"""Exploratory breakdown of a finished wac_manypoint run. POST HOC: this does not re-score.

The verdict of tools/wac_manypoint.py stands as recorded. This script only describes the
disagreement so the next test can be defined before it runs. It reads the run's report and its
checkpoint (per-point ground heights) and prints:

  * per stratum: mean WAC %, mean model % (limb, centre, best sub-point), model / WAC ratio;
  * a least-squares line model = a + b * WAC (shape of the bias: offset vs proportional);
  * how often the WAC value falls inside the range of the pixel's own sub-point values;
  * Spearman correlation of (model - WAC) with sub-pixel model spread and with sub-pixel
    ground relief (max - min DEM height of the 3 x 3 points). A strong negative link with
    relief would point at near-field terrain at 0 m observer height.

    .venv/bin/python tools/wac_manypoint_diagnostics.py [REPORT.json]
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from tools.wac_manypoint import STRATA, spearman  # noqa: E402


def least_squares(x: Sequence[float], y: Sequence[float]) -> tuple[float, float]:
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    if sxx == 0:
        raise ValueError("x has no spread")
    b = sum((a - mx) * (c - my) for a, c in zip(x, y, strict=True)) / sxx
    return my - b * mx, b


def relief_by_pixel(checkpoint: Path) -> dict[tuple[str, int, int], float]:
    heights: dict[tuple[str, int, int], list[float]] = defaultdict(list)
    for line in checkpoint.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        heights[(rec["site_id"], rec["row"], rec["col"])].append(float(rec["ground_m"]))
    return {key: max(v) - min(v) for key, v in heights.items()}


def describe(pixels: list[dict[str, Any]], relief: dict[tuple[str, int, int], float]) -> list[str]:
    out: list[str] = []
    out.append(f"{'stratum':10s} {'n':>3s} {'WAC':>6s} {'limb':>6s} {'centre':>7s} {'best pt':>8s} {'limb/WAC':>9s}")
    for k, (lo, hi) in enumerate(STRATA):
        group = [p for p in pixels if p["stratum"] == k]
        if not group:
            continue
        n = len(group)
        wac = sum(p["wac_pct"] for p in group) / n
        limb = sum(p["model_limb_pct"] for p in group) / n
        centre = sum(p["model_centre_pct"] for p in group) / n
        best = sum(p["model_point_max_pct"] for p in group) / n
        ratio = f"{limb / wac:9.2f}" if wac > 0 else f"{'-':>9s}"
        out.append(f"{lo:g}-{hi:g}".ljust(10) + f" {n:3d} {wac:6.1f} {limb:6.1f} {centre:7.1f} {best:8.1f} {ratio}")

    wac_all = [p["wac_pct"] for p in pixels]
    limb_all = [p["model_limb_pct"] for p in pixels]
    a, b = least_squares(wac_all, limb_all)
    out.append(f"\nfit: model_limb = {a:+.2f} + {b:.3f} x WAC   (pure offset -> slope ~1; proportional -> intercept ~0)")

    inside = sum(1 for p in pixels if p["model_point_min_pct"] <= p["wac_pct"] <= p["model_point_max_pct"])
    above = sum(1 for p in pixels if p["wac_pct"] > p["model_point_max_pct"])
    out.append(f"WAC inside the pixel's sub-point range: {inside}/{len(pixels)}; above every sub-point: {above}/{len(pixels)}")

    diffs = [p["model_limb_pct"] - p["wac_pct"] for p in pixels]
    spread = [p["model_point_max_pct"] - p["model_point_min_pct"] for p in pixels]
    rel = [relief.get((p["site_id"], p["row"], p["col"]), float("nan")) for p in pixels]
    out.append(f"spearman(model - WAC, sub-point model spread) = {spearman(diffs, spread):+.2f}")
    if all(r == r for r in rel):
        out.append(f"spearman(model - WAC, sub-pixel ground relief) = {spearman(diffs, rel):+.2f}")
        ordered = sorted(rel)
        out.append(f"sub-pixel ground relief (m): median {ordered[len(ordered) // 2]:.2f}, max {ordered[-1]:.2f}")
    # Within the lit strata only, where the bias is large.
    lit = [i for i, p in enumerate(pixels) if p["stratum"] >= 2]
    if len(lit) > 2 and all(r == r for r in rel):
        out.append(f"  WAC >= 20 % only (n={len(lit)}): spearman(diff, relief) = "
                   f"{spearman([diffs[i] for i in lit], [rel[i] for i in lit]):+.2f}")
    return out


def main() -> int:
    if len(sys.argv) > 1:
        report_path = Path(sys.argv[1])
    else:
        found = sorted((ROOT / "data/derived").glob("wac_manypoint_2*.json"))
        if not found:
            raise SystemExit("no wac_manypoint report found")
        report_path = found[-1]
    report = json.loads(report_path.read_text(encoding="utf-8"))
    relief = relief_by_pixel(ROOT / report["checkpoint"])
    print(f"POST HOC breakdown of {report_path.name} (recorded verdict: {report['pooled']['verdict']})\n")
    for name, group in [("ALL", report["pixels"]), *(
        (sid, [p for p in report["pixels"] if p["site_id"] == sid]) for sid in sorted({p["site_id"] for p in report["pixels"]})
    )]:
        print(f"== {name} ==")
        print("\n".join(describe(group, relief)))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
