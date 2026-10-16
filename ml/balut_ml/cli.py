from __future__ import annotations

import argparse
import json
from pathlib import Path

from .dataset import audit_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Balut ML research utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser("audit-manifest", help="Validate dataset provenance and split isolation")
    audit.add_argument("manifest", type=Path)
    audit.add_argument("--skip-file-check", action="store_true")
    audit.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "audit-manifest":
        report = audit_manifest(args.manifest, require_files=not args.skip_file_check)
        output = json.dumps(report.as_dict(), indent=2, sort_keys=True)
        if args.output:
            args.output.write_text(output + "\n", encoding="utf-8")
        print(output)
        return 0 if report.valid else 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
