"""Developer CLI for preparation-time integrity checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lunar_core.catalogue import load_default_catalogue
from lunar_core.provenance import sha256_file


def main() -> int:
    parser = argparse.ArgumentParser(prog="lunar-planner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate-catalogue", help="validate default official-site catalogue")
    hash_parser = subparsers.add_parser("hash-file", help="calculate SHA-256 for a file")
    hash_parser.add_argument("path", type=Path)
    args = parser.parse_args()

    if args.command == "validate-catalogue":
        catalogue = load_default_catalogue()
        print(json.dumps({
            "valid": True,
            "catalogue_state": catalogue.catalogue_state,
            "official_site_count": len(catalogue.sites),
        }, indent=2))
        return 0

    if args.command == "hash-file":
        if not args.path.is_file():
            parser.error(f"not a file: {args.path}")
        print(sha256_file(args.path))
        return 0

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
