"""Build explicit Day 16 / Day 18 / Unfertilized data without relabelling Reject."""
from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLASSES = ["DAY_16", "DAY_18", "UNFERTILIZED"]
DATA = ROOT / "data/local/retained-camera-unfertilized-20261019"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def combine(age_rows, public_rows):
    rows = [dict(r) for r in age_rows if r["source_label"] in CLASSES[:2]]
    excluded = [r for r in age_rows if (r.get("physical_egg_id") or "").startswith("physical-reject-20261019:")]
    if len(excluded) != 150 or {r["physical_egg_id"].split(":")[-1] for r in excluded} != {"R1", "R2", "R3"}:
        raise ValueError("Expected all 150 vendor-labelled R1/R2/R3 images")
    for index, row in enumerate(public_rows):
        if row["source_label"] != "Unfertilized":
            continue
        if row.get("crop_provenance", {}).get("source_label") != "Unfertilized":
            raise ValueError("Unfertilized annotation provenance changed")
        rows.append({**row, "source_label": "UNFERTILIZED", "original_source_label": "Unfertilized",
                     "source_dataset": "pat-unfertilized", "original_row_index": index,
                     "duplicate_group": "pat:" + row["duplicate_group"],
                     "label_authority": "Explicit public Pat v8 COCO Unfertilized annotation; not independently verified",
                     "training_eligible": row["partition"] == "train"})
    identities, groups = {}, {}
    for row in rows:
        if row["source_label"] not in CLASSES or (row.get("physical_egg_id") or "").startswith("physical-reject"):
            raise ValueError("Reject data cannot enter the Unfertilized task")
        for key in ("source_sha256", "pixel_sha256"):
            identity = (row["partition"], row["source_label"])
            prior = identities.setdefault((key, row[key]), identity)
            if prior != identity:
                raise ValueError("Conflicting label or cross-partition duplicate")
        group = row.get("physical_egg_id") or row["duplicate_group"]
        if groups.setdefault(group, row["partition"]) != row["partition"]:
            raise ValueError("An image family or physical egg crosses partitions")
    for partition in ("train", "validation", "test"):
        if {r["source_label"] for r in rows if r["partition"] == partition} != set(CLASSES):
            raise ValueError("Every partition requires all three explicit classes")
    return rows


def main():
    if DATA.exists():
        raise FileExistsError("Preserve the prepared Unfertilized dataset")
    parent = ROOT / "data/local/retained-camera-rejects-20261019/manifest.jsonl"
    public = ROOT / "data/public/pat-balut/audit-v2/manifest.jsonl"
    assert sha(parent) == "2ce212014705768fbf4978e00e37cc9dff24daa08d851df7e5be086ba07c61d1"
    source = [json.loads(line) for line in parent.read_text().splitlines()]
    annotations = [json.loads(line) for line in public.read_text().splitlines()]
    rows = combine(source, annotations)
    for row in rows:
        if sha(Path(row["image_path"])) != row["source_sha256"]:
            raise ValueError("Source image bytes changed")
    DATA.mkdir()
    content = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows)
    (DATA / "manifest.jsonl").write_bytes(content.encode("utf-8"))
    counts = {part: dict(Counter(r["source_label"] for r in rows if r["partition"] == part))
              for part in ("train", "validation", "test")}
    audit = {"status": "EXPLORATORY_EXPLICIT_UNFERTILIZED_DATASET", "class_order": CLASSES,
             "manifest_sha256": sha(DATA / "manifest.jsonl"), "parent_manifest_sha256": sha(parent),
             "public_manifest_sha256": sha(public), "total_rows": len(rows), "partition_counts": counts,
             "excluded_vendor_eggs": ["R1", "R2", "R3"], "excluded_vendor_views": 150,
             "all_reject_rows_excluded": sum(r["source_label"] == "REJECT" for r in source),
             "reject_rows_relabelled_as_unfertilized": 0,
             "age_camera_views_preserved": sum(bool(r.get("physical_egg_id")) for r in rows),
             "original_photos_or_training_runs_deleted": False, "test_inference_performed": False,
             "limitations": ["Unfertilized means the explicit source annotation, not verified embryo absence",
                             "Public image families lack physical egg or farm batch identities",
                             "Repeated camera views are correlated; physical test eggs already used in live checks remain excluded from fitting and selection"]}
    (DATA / "audit.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
