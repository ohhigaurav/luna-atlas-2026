# Luna Atlas deployment guide — 0.7.0-dev

This release is an **engineering prototype** that can be run locally or packaged in Docker. It is not a scientifically validated mission-operations service. A publicly reachable URL is not supplied by this repository; you must deploy it into an account/environment you control after eligibility, security, licensing and scientific-release gates have been reviewed.

## Local Linux deployment

```bash
./scripts/run_local.sh
```

Then visit `http://127.0.0.1:8000`. The first start creates `.venv/` and installs pinned direct dependencies (and development tools) unless `uv` is available, in which case `uv sync` is used. After dependency installation, offline launch is:

```bash
./scripts/run_local.sh --offline
```

Use `Ctrl+C` in the server terminal to stop it. The synthetic UX preview is illustrative only and is not a stored/ exportable scientific analysis.

## Docker deployment

```bash
docker compose up --build
```

Docker requires access to the Python package registry during the first image build. The service listens on port 8000. The compose file keeps kernel/DEM/manifests mounted from the host and mounts cache/run folders for persistence.

For a local demo only, leave the service on loopback or a trusted private network. **Do not publish this prototype directly to the public Internet.** It does not include user authentication, tenant isolation, request quotas, a security review or a TLS termination layer. If you later expose it beyond your machine, put it behind a maintained HTTPS reverse proxy and an authentication/access-control layer, restrict inbound access, rate-limit expensive analysis calls, and audit the threat model first. Do not imply NASA endorsement.

## Scientific input setup

From the project root on a machine with internet access:

```bash
./scripts/bootstrap_public_reference.sh
```

This stages a reference-only kernel/DEM set from allowlisted public sources. It does **not** ingest the official 2026 challenge site catalogue and does **not** verify DEM CRS/vertical-datum compatibility. Follow `README.md` and `docs/data_acquisition.md` after download. Never set a verification flag without retaining the supporting evidence and a reviewer note.

The official 2026 site catalogue must come from the challenge's official resource page; keep the raw source unchanged, record retrieval time/size/SHA-256 and run `tools/import_official_sites.py` only after validating the data schema. Literature landmarks remain a separate reference catalogue.

## Release block criteria

Do not call an image or deployment “validated” until all of these are evidenced:

- a reviewed source catalogue and licence/provenance record;
- coherent LSK/SPK/PCK/BPC/FK bundle with hash and requested-epoch coverage checks;
- verified lunar body-fixed frame/radii chain and explicit aberration convention;
- registered DEMs with file hashes, source metadata, CRS/axis/pixel registration, NoData, scale/offset/unit, elevation datum and coverage review;
- a JPL Horizons comparison at multiple sites/epochs, including a near-horizon case, with the query, raw response, and tolerances archived;
- event-step convergence plus DEM resolution/clone-ensemble sensitivity on an appropriate real candidate region;
- independent re-computation of exported metrics and saved-run provenance;
- clean environment test, dependency lock, performance test and uncoached usability test;
- Local Lead confirmation that the project work complies with the rules for the registered Space Apps event.

The current release does not pass all of these gates. `validation/evidence/local_verification_2026-10-26_v0.7-atlas.md` separates completed software checks from pending scientific validation.
