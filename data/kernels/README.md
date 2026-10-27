# SPICE kernel intake

Run from the project root:

```bash
uv run python tools/fetch_kernels.py
```

The script downloads the documented LSK, generic text PCK, lunar frame kernels, DE421 planetary SPK and DE421-associated lunar binary PCK from `naif.jpl.nasa.gov` over HTTPS. It writes the exact SHA-256, byte count, retrieval time, source URL, load order and BPC stored-frame contract to `data/manifests/kernels.json`. A reused kernel retains its original retrieval timestamp; the fetcher fails rather than fabricating one if the prior manifest lacks that field. Downloads remain outside Git.

A locally computed hash is an identity/reproducibility record, not a publisher signature. Inspect NAIF's kernel documentation, ensure temporal coverage for each requested epoch, and run the saved JPL Horizons comparison before considering geometry validated. The manifest records `coverage_frame` on each BPC: the supplied DE421 lunar BPC stores `MOON_PA_DE421` orientation, whereas this application requests `MOON_ME`. The runtime calls `pckcov` on the stored frame class and verifies `pxform("MOON_PA_DE421", "MOON_ME", ET)` at both interval endpoints; it does not incorrectly query PCK coverage using the derived `MOON_ME` frame ID. The selected MOON_ME/DE421 chain is a starting contract inherited from the PRD, not a substitute for closing D-07.
