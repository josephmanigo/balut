"""Retain annotated Reject/Unfertilized crops; exclude every old age image."""
import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.capture_emeet_egg import sha, write


def retain_reject(dataset, source):
    manifest = source / "manifest.jsonl"
    audit = json.loads((source / "audit.json").read_text())
    if sha(manifest) != audit["manifest_sha256"]:
        raise ValueError("Reject source manifest checksum mismatch")
    target = dataset / "reject"
    target.mkdir(parents=True, exist_ok=True)
    (target / "images").mkdir(exist_ok=True)
    rows = []
    groups = {}
    for row in [json.loads(line) for line in manifest.read_text().splitlines()]:
        if row["source_label"] not in {"Reject", "Unfertilized"}:
            continue
        group = "pat:" + row["duplicate_group"]
        if groups.setdefault(group, row["partition"]) != row["partition"]:
            raise ValueError("Reject source family crosses partitions")
        original = Path(row["image_path"])
        if sha(original) != row["source_sha256"]:
            raise ValueError("Reject source image checksum mismatch")
        copy = target / "images" / (row["source_sha256"] + original.suffix.lower())
        if not copy.exists():
            shutil.copy2(original, copy)
        if sha(copy) != row["source_sha256"]:
            raise ValueError("Retained Reject copy differs from source")
        rows.append({**row, "image_path": str(copy.resolve()), "source_annotation": row["source_label"],
                     "source_label": "REJECT", "source_dataset": "pat-balut-retained-reject",
                     "duplicate_group": group, "original_source_path": str(original),
                     "label_authority": "Public source annotation; biological subtype unverified"})
    if not rows:
        raise ValueError("No Reject source images found")
    content = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    output = target / "manifest.jsonl"
    if output.exists() and output.read_text() != content:
        raise ValueError("Preserve the frozen Reject manifest")
    output.write_text(content)
    report = {"source_manifest_sha256": sha(manifest), "manifest_sha256": sha(output),
              "images": len(rows), "original_labels": dict(Counter(r["source_annotation"] for r in rows)),
              "partition_counts": dict(Counter(r["partition"] for r in rows)),
              "split_policy": "Original audited source-family split retained; historical public test is not a new field test",
              "physical_reject_eggs": 0, "confirmed_dead_embryo_samples": 0,
              "confirmed_spoiled_samples": 0, "old_age_images_included": 0,
              "limitations": ["Source Reject does not confirm a particular biological defect",
                              "Unfertilized is a source annotation, not independently verified embryo absence",
                              "Reject photographs come from another camera domain",
                              "Unknown physical egg and batch identities limit leakage guarantees"]}
    write(target / "audit.json", report)
    return report


def finalize(dataset):
    from ml.balut_ml.emeet_development import development_rows, validate_rows

    rows = development_rows(dataset, require_complete=True, include_test=True)
    if Counter(r["source_label"] for r in rows) != {"DAY_16": 1500, "DAY_18": 1500}:
        raise ValueError("Require exactly 1500 real captured images for each age")
    reject = dataset / "reject/manifest.jsonl"
    if sha(reject) != json.loads((dataset / "reject/audit.json").read_text())["manifest_sha256"]:
        raise ValueError("Retained Reject manifest changed")
    rows += [json.loads(line) for line in reject.read_text().splitlines()]
    validate_rows(rows, allow_test=True)
    content = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    manifest = dataset / "manifest.jsonl"
    if manifest.exists() and manifest.read_text() != content:
        raise ValueError("Preserve the finalized dataset manifest")
    manifest.write_text(content)
    report = {"manifest_sha256": sha(manifest), "class_order": ["DAY_16", "DAY_18", "REJECT"],
              "images": len(rows), "class_counts": dict(Counter(r["source_label"] for r in rows)),
              "partition_counts": {part: dict(Counter(r["source_label"] for r in rows if r["partition"] == part))
                                   for part in ("train", "validation", "test")},
              "physical_age_eggs": len({r["physical_egg_id"] for r in rows if r.get("physical_egg_id")}),
              "confirmed_physical_reject_eggs": 0, "old_age_images_used": 0,
              "augmentation_counted_as_new_photos": False, "warmup_frames_included": False,
              "known_cross_partition_group_or_exact_image_overlap": False, "unknown_public_egg_or_batch_overlap_ruled_out": False}
    write(dataset / "audit.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--source", type=Path, default=ROOT / "data/public/pat-balut/audit-v2")
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    print(json.dumps(finalize(args.dataset.resolve()) if args.finalize else retain_reject(args.dataset.resolve(), args.source)))
