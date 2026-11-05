"""Copy the shadow-match pictures and report into the app (PRD F22, proof slider).

    python tools/export_proof.py

Reads data/derived/shadow_match/ (written by tools/shadow_match.py on the machine that ran it) and
writes frontend/app/public/proof/:
    {frame}_compare.png   unchanged; left LRO photo | our shadows | difference, 6 px white gaps
    report.json           the newest shadow_match_*.json, unchanged
These files are small and meant to be committed, so the judge bundle carries the proof.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data/derived/shadow_match"
DST = ROOT / "frontend/app/public/proof"


def main() -> int:
    pngs = sorted(SRC.glob("*_compare.png"))
    reports = sorted(SRC.glob("shadow_match_*.json"))
    if not pngs or not reports:
        print(f"nothing to export: run tools/shadow_match.py first ({SRC.relative_to(ROOT)} is empty)")
        return 1
    DST.mkdir(parents=True, exist_ok=True)
    for p in pngs:
        shutil.copy2(p, DST / p.name)
        print(f"{p.name}  {p.stat().st_size / 1e3:.0f} kB")
    shutil.copy2(reports[-1], DST / "report.json")
    print(f"report.json  <- {reports[-1].name}")
    print(f"done: {DST.relative_to(ROOT)} (commit it)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
