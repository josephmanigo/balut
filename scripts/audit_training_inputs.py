"""Verify the three supplied public archives and the audited training images."""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ml"))
from balut_ml.public_data import sha256 as file_sha256
from balut_ml.train_public import load_audited_rows

SOURCES = [
    ("age", "Egg Candling.v6i.coco.zip", "thesis-egg-candling", "Egg Candling.v6i.coco.zip", "audit-v1"),
    ("pat", "Balut Eggs Project -Unfertilized- Fertilized- and Reject-.v8-dataset-v5-yolov8.coco.zip", "pat-balut", "pat-balut-v8.coco.zip", "audit-v2"),
    ("duck", "Duck Egg Candling.v2i.folder.zip", "duck-egg-candling", "Duck Egg Candling.v2i.folder.zip", "audit-v2"),
]


def audit(downloads: Path) -> dict:
    sources = []
    for name, supplied, folder, imported, version in SOURCES:
        archive = downloads / supplied
        root = ROOT / "data/public" / folder
        digest = file_sha256(archive)
        if digest != file_sha256(root / imported):
            raise ValueError(f"The supplied {name} archive differs from the imported dataset; re-audit before training")
        with zipfile.ZipFile(archive) as bundle:
            if bundle.testzip() is not None:
                raise ValueError(f"Corrupt {name} archive")
            members = len(bundle.infolist())
        rows, report = load_audited_rows(root / version / "manifest.jsonl")
        sources.append({"source": name, "archive": str(archive), "archive_sha256": digest,
                        "already_imported": True, "zip_members": members, "verified_images": len(rows),
                        "source_label_counts": dict(Counter(row["source_label"] for row in rows)),
                        "partition_counts": dict(Counter(row["partition"] for row in rows)),
                        "manifest_sha256": report["manifest_sha256"]})
    return {"passed": True, "sources": sources, "new_independent_data": False,
            "physical_ground_truth_verified": False, "operational_use_authorized": False,
            "duck_source_use": "Auxiliary fertility/abnormal research only; never remapped to Day 16, Day 18, or Reject",
            "scope": "Archive CRC, original/archive identity, manifest and image hashes, existing group/decoded-hash split isolation"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--downloads", type=Path, default=Path.home() / "Downloads")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.downloads)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
