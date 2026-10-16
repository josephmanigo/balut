"""Convert selected public COCO egg boxes to source-labelled classification crops."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path


def crop_source(root: Path, output: Path, selected_labels: list[str]) -> dict:
    from PIL import Image
    if output.exists():
        raise ValueError("Crop output already exists")
    files = sorted(root.rglob("_annotations.coco.json"))
    if not files:
        raise ValueError("No COCO annotations found")
    output.mkdir(parents=True)
    lineage, excluded = [], []
    for annotation_file in files:
        data = json.loads(annotation_file.read_text(encoding="utf-8"))
        categories = {item["id"]: item["name"] for item in data["categories"]}
        images = {item["id"]: item for item in data["images"]}
        for annotation in data["annotations"]:
            label = categories[annotation["category_id"]]
            if label not in selected_labels:
                continue
            if Path(label).name != label or any(c in label for c in '/\\:'):
                raise ValueError("Category name is not safe for a class directory")
            source_image = images[annotation["image_id"]]
            path = (annotation_file.parent / source_image["file_name"]).resolve()
            if not path.is_relative_to(root.resolve()):
                raise ValueError("COCO image path escapes source directory")
            x, y, width, height = annotation["bbox"]
            with Image.open(path) as original:
                if original.size != (source_image["width"], source_image["height"]):
                    raise ValueError("COCO dimensions disagree with image")
                if not all(math.isfinite(v) for v in (x, y, width, height)) or min(width, height) < 32 or x < 0 or y < 0 or x + width > original.width + 1 or y + height > original.height + 1:
                    excluded.append({"source_image": str(path), "annotation_id": annotation["id"], "reason": "invalid_or_small_bbox", "bbox": annotation["bbox"]})
                    continue
                box = [max(0, math.floor(x)), max(0, math.floor(y)), min(original.width, math.ceil(x + width)), min(original.height, math.ceil(y + height))]
                relative = Path(annotation_file.parent.name) / label / f"{path.stem}__crop-{annotation['id']}.png"
                target = output / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    raise ValueError("Duplicate crop identity")
                original.convert("RGB").crop(box).save(target)
            lineage.append({"crop_path": relative.as_posix(), "source_image_path": str(path), "source_image_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            "annotation_file": str(annotation_file.resolve()), "annotation_id": annotation["id"], "source_label": label,
                            "original_bbox_xywh": annotation["bbox"], "crop_box_xyxy": box,
                            "source_image_id": source_image["id"], "original_filename": source_image.get("extra", {}).get("name"),
                            "physical_egg_id": None, "verified_incubation_hours": None})
    (output / "crop-lineage.jsonl").write_text("".join(json.dumps(row) + "\n" for row in lineage), encoding="utf-8")
    report = {"source_root": str(root.resolve()), "selected_labels": selected_labels, "crop_count": len(lineage),
              "class_counts": dict(Counter(row["source_label"] for row in lineage)), "excluded": excluded,
              "note": "COCO date_captured in these exports is not verified incubation/capture metadata. Crops retain source annotations without biological relabelling."}
    (output / "crop-audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--labels", nargs="+", required=True)
    args = parser.parse_args()
    print(json.dumps(crop_source(args.source, args.output, args.labels), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
