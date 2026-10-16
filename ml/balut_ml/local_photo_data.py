"""Import supplied day folders as an exploratory, training-only collection."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/edge_api"))
from balut_api.selective_gate import image_quality
from .public_data import make_contact_sheet, sha256

COLLECTION = "user-day16-day18-20261014"
# A framing crop, not an annotated egg boundary; identical for both age labels.
FRAMING = (0.08, 0.18, 0.92, 0.94)


def frame_image(image):
    image = ImageOps.exif_transpose(image).convert("RGB")
    box = tuple(round(v * (image.width if i % 2 == 0 else image.height)) for i, v in enumerate(FRAMING))
    framed = image.crop(box)
    if max(framed.size) > 640:
        framed = ImageOps.contain(framed, (640, 640), Image.Resampling.LANCZOS)
    return framed, box


def import_photos(inventory: Path, output: Path):
    if output.exists():
        raise FileExistsError("Choose a fresh dataset directory")
    inputs = [json.loads(line) for line in inventory.read_text(encoding="utf-8").splitlines() if line.strip()]
    unique, duplicates, hashes = [], [], {}
    for row in inputs:
        if row["label"] not in {"16", "18"}:
            raise ValueError("Only explicit day 16 and day 18 folder labels are supported")
        path = Path(row["path"])
        if sha256(path) != row["sha256"]:
            raise ValueError(f"Photo changed since inspection: {path}")
        key = row["pixel_sha256"]
        if key in hashes:
            if hashes[key]["label"] != row["label"]:
                raise ValueError("Identical photos have conflicting labels")
            duplicates.append({"path": str(path), "retained_path": hashes[key]["path"], "reason": "identical_decoded_image"})
        else:
            hashes[key] = row
            unique.append(row)
    required = sum(Path(row["path"]).stat().st_size for row in unique) + 80 * 1024**2
    if shutil.disk_usage(output.parent).free < required:
        raise OSError("Need space for original photos plus an 80 MiB working reserve")
    output.mkdir()
    policy_path = ROOT / "ml/runs/selective-v2/gate-policy.json"
    policy = json.loads(policy_path.read_text())
    rows = []
    for item in unique:
        label = "DAY_" + item["label"]
        name = f'{item["label"]}-{Path(item["path"]).stem}-{item["sha256"][:12]}'
        original = output / "originals" / label / f"{name}.jpeg"
        crop = output / "framed" / label / f"{name}.jpg"
        original.parent.mkdir(parents=True, exist_ok=True)
        crop.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item["path"], original)
        if sha256(original) != item["sha256"]:
            raise ValueError("Original copy failed integrity check")
        with Image.open(original) as source:
            framed, box = frame_image(source)
            framed.save(crop, quality=95, subsampling=0)
        with Image.open(crop) as source:
            rgb = source.convert("RGB")
            quality, flags = image_quality(rgb, policy)
            pixels = hashlib.sha256(str(rgb.size).encode() + rgb.tobytes()).hexdigest()
            dimensions = list(rgb.size)
        rows.append({"image_path": str(crop.resolve()), "source_sha256": sha256(crop), "pixel_sha256": pixels,
                     "source_label": label, "original_source_label": item["label"], "partition": "train",
                     "source_dataset": COLLECTION, "duplicate_group": COLLECTION + ":unknown-egg-batch",
                     "physical_egg_id": None, "batch_id": None, "verified_incubation_hours": None,
                     "label_authority": "User-supplied folder label; not independently verified",
                     "original_path": str(original.resolve()), "original_sha256": item["sha256"],
                     "download_path": item["path"], "crop_box_xyxy": box, "dimensions": dimensions,
                     "quality_measurements": quality, "quality_flags": flags, "training_eligible": not flags})
    manifest = output / "manifest.jsonl"
    manifest.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    report = {"status": "EXPLORATORY_USER_DATA_ONLY", "collection": COLLECTION,
              "manifest_sha256": sha256(manifest), "inventory_sha256": sha256(inventory),
              "images_supplied": len(inputs), "unique_images": len(rows), "duplicates_excluded": duplicates,
              "class_counts": dict(Counter(r["source_label"] for r in rows)),
              "training_eligible_counts": dict(Counter(r["source_label"] for r in rows if r["training_eligible"])),
              "quality_exclusion_counts": dict(Counter(flag for r in rows for flag in r["quality_flags"])),
              "preprocessing": {"framing_fraction_xyxy": FRAMING, "maximum_side": 640, "jpeg_quality": 95,
                                "description": "Fixed framing crop, not a verified egg bounding box; no brightness or contrast editing"},
              "quality_policy_sha256": sha256(policy_path), "operational_use_authorized": False,
              "unique_physical_eggs": None, "verified_age_labels": False, "publication_permission": "not established",
              "partition_policy": "Entire incoming collection is training-only. No local validation/test score is independent after fitting.",
              "limitations": ["Folder labels are unverified source labels.", "No egg IDs, batch IDs, incubation records or capture metadata.",
                              "No new reject-labelled examples.", "Framing crops require visual inspection; quality flags do not establish egg visibility."]}
    (output / "audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    # Display diverse frames; all share one conservative partition group.
    preview_rows = [{**r, "duplicate_group": str(i)} for i, r in enumerate(rows)]
    make_contact_sheet(preview_rows, output / "contact-sheet.jpg", per_class=24)
    print(json.dumps(report, indent=2), flush=True)


def load_local_rows(manifest: Path):
    audit = json.loads(manifest.with_name("audit.json").read_text(encoding="utf-8"))
    if audit.get("status") != "EXPLORATORY_USER_DATA_ONLY" or sha256(manifest) != audit["manifest_sha256"]:
        raise ValueError("Invalid or changed local dataset manifest")
    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
    seen = {}
    for row in rows:
        if row["partition"] != "train" or row["duplicate_group"] != COLLECTION + ":unknown-egg-batch":
            raise ValueError("Unidentified local eggs must remain together in training")
        if row["source_label"] not in {"DAY_16", "DAY_18"}:
            raise ValueError("Unsupported local source label")
        for path_key, hash_key in (("image_path", "source_sha256"), ("original_path", "original_sha256")):
            if sha256(Path(row[path_key])) != row[hash_key]:
                raise ValueError(f"Changed local photo: {row[path_key]}")
        if row["pixel_sha256"] in seen:
            raise ValueError("Duplicate framed images need audit")
        seen[row["pixel_sha256"]] = row["source_label"]
    return rows, audit


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    import_photos(args.inventory, args.output)
