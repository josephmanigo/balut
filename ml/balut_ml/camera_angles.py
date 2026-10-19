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
    return import_records(BASE, CAPTURE, DATA, 3, partial)


def import_records(base, capture, data, views_per_egg, partial=False, reject_plan=None):
    if views_per_egg not in (3, 50):
        raise ValueError("Supported collections contain three or 50 views per egg")
    protocol = "three-paused-views-v1" if views_per_egg == 3 else "fifty-paused-views-v1"
    baseline = base / "manifest.jsonl"
    old_audit = json.loads((base / "audit.json").read_text())
    if sha(baseline) != old_audit["manifest_sha256"]:
        raise ValueError("Original retained camera manifest changed")
    rejection = json.loads(reject_plan.read_text()) if reject_plan else None
    reject_splits = {"R1": "train", "R2": "validation", "R3": "test"}
    if reject_plan is not None and (not isinstance(rejection, dict) or views_per_egg != 50 or rejection.get("egg_partitions") != reject_splits
            or rejection.get("base_manifest_sha256") != sha(baseline)
            or rejection.get("label_authority") != "Vendor labeled Reject; rejection reason not supplied or independently confirmed"
            or rejection.get("shell_marks") != "operator_reports_unmarked_shells"
            or rejection.get("uncooked") is not True):
        raise ValueError("Reject collection plan changed")
    old_rows = [json.loads(line) for line in baseline.read_text().splitlines() if line.strip()]
    records = sorted(capture.glob("*/record.json"))
    contents = {path: json.loads(path.read_text()) for path in records}
    expected = set(reject_splits) if rejection else {f"{age}-{index}" for age in (16, 18) for index in range(1, 16)}
    completed = [path for path, record in contents.items() if len(record["views"]) == views_per_egg]
    complete = {path.parent.name for path in completed} == expected and len(records) == len(expected)
    if not records or not partial and not complete:
        raise ValueError(f"Complete all {len(expected)} numbered eggs before finalizing the dataset")
    policy = json.loads((ROOT / "ml/runs/selective-v2/gate-policy.json").read_text())
    identities = {row[key] for row in old_rows for key in ("source_sha256", "pixel_sha256")}
    egg_splits = {row["physical_egg_id"]: row["partition"] for row in old_rows if row.get("physical_egg_id")}
    incoming, copies = [], []
    for path in records:
        record = contents[path]
        egg = path.parent.name
        if rejection:
            if egg not in reject_splits:
                raise ValueError("Unexpected Reject egg ID")
            partition, label = reject_splits[egg], "REJECT"
            identity = f"physical-reject-20261019:{egg}"
            if (record.get("reject_plan_sha256") != sha(reject_plan) or record.get("source_label") != label
                    or record.get("label_authority") != rejection["label_authority"]
                    or record.get("label_reference") != rejection["label_authority"]
                    or record.get("defect_independently_confirmed") is not False or record.get("uncooked") is not True
                    or record.get("capture_session_id") != capture.name
                    or identity in egg_splits):
                raise ValueError("Reject identity or label provenance changed")
        else:
            age, partition = partition_for(egg)
            label = f"DAY_{age}"
            original = ROOT / "output/physical-pilot-20261018" / f"{egg}.json"
            identity = f"physical-camera-20261018:{egg}"
            if record["reported_age_days"] != age or record["original_record_sha256"] != sha(original) or egg_splits.get(identity) != partition:
                raise ValueError("Multiangle original egg identity changed")
        if (record["egg_id"] != egg or record["partition"] != partition or record["physical_egg_id"] != identity
                or record["model_used_for_label"] is not False or record["capture_protocol"] != protocol):
            raise ValueError("Multiangle egg identity, label, partition, or original record changed")
        count = len(record["views"])
        if (not 1 <= count <= views_per_egg or not partial and count != views_per_egg
                or views_per_egg == 3 and count != 3
                or {view["view_index"] for view in record["views"]} != set(range(1, count + 1))):
            raise ValueError("Each egg requires distinct sequential numbered views")
        if views_per_egg == 50:
            if (record.get("target_views") != 50 or record.get("steps_per_revolution") != 2048
                    or type(record.get("angle_origin_steps")) is not int
                    or not 0 <= record["angle_origin_steps"] <= 0xffffffff
                    or record.get("angles_verified") is not False or record.get("completed") != (count == 50)
                    or record.get("shell_marks") != "operator_reports_unmarked_shells"
                    or any(type(view.get("motor_steps")) is not int or not 0 <= view["motor_steps"] <= 0xffffffff
                           or view.get("angles_verified") is not False for view in record["views"])):
                raise ValueError("Missing fifty-view rotation contract")
            bins = [((view["motor_steps"] - record["angle_origin_steps"]) & 0xffffffff) % 2048 * 50 // 2048
                    for view in record["views"]]
            if len(set(bins)) != count or any(view.get("angle_bin") != slot for view, slot in zip(record["views"], bins, strict=True)):
                raise ValueError("Repeated or inconsistent commanded angle bins")
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
            if views_per_egg == 50 and view.get("pixel_sha256") != pixels:
                raise ValueError("Fifty-view decoded image identity changed")
            if view["sha256"] in identities or pixels in identities:
                raise ValueError("Duplicate image in the retained dataset")
            identities.update((view["sha256"], pixels))
            destination = data / "images" / f'{egg}-{view["view_index"]}-{view["sha256"][:12]}.jpg'
            if destination.exists() and sha(destination) != view["sha256"]:
                raise ValueError("Previously copied camera image changed")
            copies.append((source, destination, view["sha256"]))
            incoming.append({"image_path": str(destination.resolve()), "source_sha256": view["sha256"],
                "pixel_sha256": pixels, "source_label": label, "source_dataset": capture.name,
                "partition": partition, "physical_egg_id": identity, "duplicate_group": identity,
                "batch_id": None, "capture_session_id": record["capture_session_id"], "verified_incubation_hours": None,
                "label_authority": record["label_authority"], "label_reference": record["label_reference"],
                "capture_record": {**{key: value for key, value in record.items() if key != "views"}, **view},
                "dimensions": [600, 800], "quality_measurements": quality, "quality_flags": flags,
                "training_eligible": partition == "train" and not flags,
                "test_status": ("closed_reject_collection_test" if rejection else "closed_original_pilot_test") if partition == "test" else None})
    combined = old_rows + incoming
    groups = {}
    for row in combined:
        for key in ("source_sha256", "pixel_sha256", "duplicate_group"):
            identity = (key, row[key])
            if identity in groups and groups[identity] != row["partition"]:
                raise ValueError("An egg or image crosses dataset partitions")
            groups[identity] = row["partition"]
    (data / "images").mkdir(parents=True, exist_ok=True)
    for source, destination, digest in copies:
        if not destination.exists():
            shutil.copyfile(source, destination)
        if sha(destination) != digest:
            raise ValueError("Camera dataset copy failed checksum verification")
    content = "".join(json.dumps(row, allow_nan=False) + "\n" for row in combined).encode()
    digest = hashlib.sha256(content).hexdigest()
    snapshots = data / "snapshots"
    snapshots.mkdir(exist_ok=True)
    snapshot = snapshots / f"manifest-{len(incoming)}-{digest[:12]}.jsonl"
    if not snapshot.exists():
        snapshot.write_bytes(content)
    temporary = data / "manifest.pending"
    temporary.write_bytes(content)
    temporary.replace(data / "manifest.jsonl")
    final_status = "EXPLORATORY_RETAINED_MULTIANGLE_DATASET" if views_per_egg == 3 else "EXPLORATORY_RETAINED_50_VIEW_DATASET"
    if rejection:
        final_status = "EXPLORATORY_RETAINED_REJECT_DATASET"
    audit = {"status": final_status if complete else "COLLECTION_IN_PROGRESS",
        "manifest_sha256": digest, "base_manifest_sha256": old_audit["manifest_sha256"],
        "base_rows_preserved": len(old_rows), "new_views": len(incoming), "total_rows": len(combined),
        "captured_eggs": len(records), "completed_eggs": len(completed), "views_per_egg_target": views_per_egg,
        "target_views": len(expected) * views_per_egg, "target_eggs": len(expected), "physical_eggs_in_original_collection": 30,
        "captured_ids": [path.parent.name for path in records],
        "new_view_partitions": dict(Counter(row["partition"] for row in incoming)),
        "training_eligible_new_views": sum(row["training_eligible"] for row in incoming),
        "independent_new_eggs": len(records) if rejection else 0, "test_reopened": False, "active_release_changed": False,
        "operational_use_authorized": False,
        "claim_99_percent_supported": False,
        "limitations": ["Repeat views of the same 30 user-identified eggs are not independent new eggs",
                        "Original test eggs stay excluded from fitting and model selection",
                        "Cohort ages refer to the original collection; elapsed incubation records are not supplied",
                        "Motor step spacing is approximate; no physical position encoder"]}
    if rejection:
        audit.update(reject_label_authority=rejection["label_authority"], reject_plan_sha256=sha(reject_plan),
                     physical_eggs_total=30 + len(records))
        audit["limitations"].append("The three new Reject labels are vendor reports without independently confirmed rejection reasons")
    temporary = data / "audit.pending"
    temporary.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    temporary.replace(data / "audit.json")
    if sha(baseline) != old_audit["manifest_sha256"]:
        raise ValueError("Original retained manifest changed during import")
    return audit


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--partial", action="store_true", help="Save an explicitly incomplete collection without enabling training")
    args = parser.parse_args()
    print(json.dumps(build_dataset(args.partial)), flush=True)
