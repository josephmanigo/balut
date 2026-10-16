"""Extract a downloaded dataset ZIP into a fresh directory and record its hash."""
from __future__ import annotations

import argparse
import hashlib
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath


def extract_archive(archive: Path, output: Path) -> dict:
    if output.exists():
        raise ValueError("Choose a fresh export directory; existing datasets are not overwritten")
    with zipfile.ZipFile(archive) as source:
        members = source.infolist()
        total_bytes = sum(member.file_size for member in members)
        if len(members) > 100000 or total_bytes > 20 * 1024**3:
            raise ValueError("Unexpected dataset archive size")
        for member in members:
            normalized = member.filename.replace("\\", "/")
            parts = PurePosixPath(normalized)
            if parts.is_absolute() or ".." in parts.parts or ":" in normalized:
                raise ValueError(f"Unsafe archive path: {member.filename}")
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ValueError("Dataset archive contains a symbolic link")
            if not (output / normalized).resolve().is_relative_to(output.resolve()):
                raise ValueError("Archive member escapes export directory")
        output.mkdir(parents=True)
        source.extractall(output)
    report = {"archive": str(archive.resolve()), "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
              "archive_bytes": archive.stat().st_size, "extracted_directory": str(output.resolve()),
              "member_count": len(members), "uncompressed_bytes": total_bytes}
    (output / "archive-audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(extract_archive(args.archive, args.output), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
