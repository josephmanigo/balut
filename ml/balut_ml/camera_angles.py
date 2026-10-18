"""Append numbered multiangle captures while preserving the original egg partitions."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil

from PIL import Image
from balut_api.selective_gate import image_quality
from scripts.camera_egg_ids import partition_for

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "data/local/retained-camera-20261018"
CAPTURE = ROOT / "output/physical-multiangle-20261019"
DATA = ROOT / "data/local/retained-camera-angles-20261019"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_dataset(partial=False):
    baseline = BASE / "manifest.jsonl"
    old_audit = json.loads((BASE / "audit.json").read_text())
    if sha(baseline) != old_audit["manifest_sha256"]:
        raise ValueError("Original retained camera manifest changed")
    old_rows = [json.loads(line) for line in baseline.read_text().splitlines() if line.strip()]
    records = sorted(CAPTURE.glob("*/record.json"))
    expected = {f"{age}-{index}" for age in (16, 18) for index in range(1, 16)}
    if not records or not partial and {path.parent.name for path in records} != expected:
        raise ValueError("Complete all 30 numbered eggs before finalizing the dataset")
    policy = json.loads((ROOT / "ml/runs/selective-v2/gate-policy.json").read_text())
    identities = {row[key] for row in old_rows for key in ("source_sha256", "pixel_sha256")}
    egg_splits = {row["physical_egg_id"]: row["partition"] for row in old_rows if row.get("physical_egg_id")}
    incoming, copies = [], []
    for path in records:
        record = json.loads(path.read_text())
        egg = path.parent.name
        age, partition = partition_for(egg)
        original = ROOT / "output/physical-pilot-20261018" / f"{egg}.json"
        identity = f"physical-camera-20261018:{egg}"
        if (record["egg_id"] != egg or record["reported_age_days"] != age or record["partition"] != partition
                or record["physical_egg_id"] != identity or record["model_used_for_label"] is not False
                or record["original_record_sha256"] != sha(original) or egg_splits.get(identity) != partition
                or record["capture_protocol"] != "three-paused-views-v1"):
            raise ValueError("Multiangle egg identity, label, partition, or original record changed")
        if len(record["views"]) != 3 or {view["view_index"] for view in record["views"]} != {1, 2, 3}:
            raise ValueError("Each egg requires three distinct numbered views")
        for view in record["views"]:
            name = f'view-{view["view_index"]}.jpg'
            source = path.parent / name
            if view["image"] != name or sha(source) != view["sha256"]:
                raise ValueError("Multiangle source image changed")
            with Image.open(source) as image:
                rgb = image.convert("RGB")
                if image.format != "JPEG" or rgb.size != (600, 800):
                    raise ValueError("Multiangle frame format changed")
                pixels = hashlib.sha256(str(rgb.size).encode() + rgb.tobytes()).hexdigest()
                quality, flags = image_quality(rgb, policy)
            if view["sha256"] in identities or pixels in identities:
                raise ValueError("Duplicate image in the retained dataset")
            identities.update((view["sha256"], pixels))
            destination = DATA / "images" / f'{egg}-{view["view_index"]}-{view["sha256"][:12]}.jpg'
            if destination.exists() and sha(destination) != view["sha256"]:
                raise ValueError("Previously copied camera image changed")
            copies.append((source, destination, view["sha256"]))
            incoming.append({"image_path": str(destination.resolve()), "source_sha256": view["sha256"],
                "pixel_sha256": pixels, "source_label": f"DAY_{age}", "source_dataset": "physical-multiangle-20261019",
                "partition": partition, "physical_egg_id": identity, "duplicate_group": identity,
                "batch_id": None, "capture_session_id": record["capture_session_id"], "verified_incubation_hours": None,
                "label_authority": record["label_authority"], "label_reference": record["label_reference"],
                "capture_record": {**{key: value for key, value in record.items() if key != "views"}, **view},
                "dimensions": [600, 800], "quality_measurements": quality, "quality_flags": flags,
                "training_eligible": partition == "train" and not flags,
                "test_status": "closed_original_pilot_test" if partition == "test" else None})
    combined = old_rows + incoming
    groups = {}
    for row in combined:
        for key in ("source_sha256", "pixel_sha256", "duplicate_group"):
            identity = (key, row[key])
            if identity in groups and groups[identity] != row["partition"]:
                raise ValueError("An egg or image crosses dataset partitions")
            groups[identity] = row["partition"]
    (DATA / "images").mkdir(parents=True, exist_ok=True)
    for source, destination, digest in copies:
        if not destination.exists():
            shutil.copyfile(source, destination)
        if sha(destination) != digest:
            raise ValueError("Camera dataset copy failed checksum verification")
    content = "".join(json.dumps(row, allow_nan=False) + "\n" for row in combined).encode()
    digest = hashlib.sha256(content).hexdigest()
    snapshots = DATA / "snapshots"
    snapshots.mkdir(exist_ok=True)
    snapshot = snapshots / f"manifest-{len(incoming)}-{digest[:12]}.jsonl"
    if not snapshot.exists():
        snapshot.write_bytes(content)
    temporary = DATA / "manifest.pending"
    temporary.write_bytes(content)
    temporary.replace(DATA / "manifest.jsonl")
    audit = {"status": "EXPLORATORY_RETAINED_MULTIANGLE_DATASET" if len(records) == 30 else "COLLECTION_IN_PROGRESS",
        "manifest_sha256": digest, "base_manifest_sha256": old_audit["manifest_sha256"],
        "base_rows_preserved": len(old_rows), "new_views": len(incoming), "total_rows": len(combined),
        "captured_eggs": len(records), "target_eggs": 30, "physical_eggs_in_original_collection": 30,
        "captured_ids": [path.parent.name for path in records],
        "new_view_partitions": dict(Counter(row["partition"] for row in incoming)),
        "training_eligible_new_views": sum(row["training_eligible"] for row in incoming),
        "independent_new_eggs": 0, "test_reopened": False, "active_release_changed": False,
        "operational_use_authorized": False,
        "claim_99_percent_supported": False,
        "limitations": ["Repeat views of the same 30 user-identified eggs are not independent new eggs",
                        "Original test eggs stay excluded from fitting and model selection",
                        "Cohort ages refer to the original collection; elapsed incubation records are not supplied",
                        "Motor step spacing is approximate; no physical position encoder"]}
    temporary = DATA / "audit.pending"
    temporary.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    temporary.replace(DATA / "audit.json")
    if sha(baseline) != old_audit["manifest_sha256"]:
        raise ValueError("Original retained manifest changed during import")
    return audit


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--partial", action="store_true", help="Save an explicitly incomplete collection without enabling training")
    args = parser.parse_args()
    print(json.dumps(build_dataset(args.partial)), flush=True)
