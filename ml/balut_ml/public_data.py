"""Audit public image-classification exports without inventing physical metadata.

The manifest produced here is deliberately incompatible with DatasetFrame.
Source labels are exploratory annotations, not the project's operational labels.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
PARTITIONS = {"train", "valid", "validation", "val", "test"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_stem(path: Path) -> str:
    # Roboflow generated variants retain a shared prefix before .rf.<hash>.
    return re.split(r"[._]rf[._]", path.stem, maxsplit=1)[0].split("__crop-")[0]


def near_duplicate(hash_a: int, hash_b: int, thumbnail_a, thumbnail_b) -> bool:
    import numpy as np
    # Egg silhouettes often have the same grayscale hash despite different
    # contents/colors. Require close RGB pixels too; otherwise whole datasets
    # can falsely collapse through chains of look-alike eggs.
    return (hash_a ^ hash_b).bit_count() <= 3 and float(np.abs(thumbnail_a - thumbnail_b).mean()) <= 6.0


def discover_images(root: Path) -> tuple[list[tuple[Path, str]], list[dict]]:
    """Read Roboflow single-label CSV or class-directory exports; reject ambiguity."""
    samples, excluded = [], []
    csvs = sorted(root.rglob("_classes.csv"))
    if csvs:
        for path in csvs:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    row = {k.strip(): v.strip() for k, v in row.items()}
                    filename = row.pop("filename", None)
                    if not filename:
                        raise ValueError(f"CSV requires filename: {path}")
                    selected = [key for key, val in row.items() if float(val) == 1]
                    image_path = (path.parent / filename).resolve()
                    if not image_path.is_relative_to(root.resolve()):
                        raise ValueError("Image path escapes source directory")
                    if len(selected) != 1:
                        excluded.append({"path": str(image_path), "reason": "ambiguous_or_missing_label", "labels": selected})
                    else:
                        samples.append((image_path, selected[0]))
        return samples, excluded
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        if path.parent == root or path.parent.name.lower() in PARTITIONS:
            raise ValueError(f"No class-directory label for {path}; export classification folders or _classes.csv")
        samples.append((path, path.parent.name))
    return samples, excluded


def assign_partitions(rows: list[dict], seed: int = 42) -> None:
    from sklearn.model_selection import StratifiedGroupKFold

    labels = sorted({r["source_label"] for r in rows})
    groups_by_label = {label: {r["duplicate_group"] for r in rows if r["source_label"] == label} for label in labels}
    if len(labels) < 2 or any(len(groups) < 10 for groups in groups_by_label.values()):
        raise ValueError("Training requires at least two classes with 10 independent image groups each")
    folds = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=seed)
    for fold, (_, indexes) in enumerate(folds.split(rows, [r["source_label"] for r in rows], [r["duplicate_group"] for r in rows])):
        for index in indexes:
            rows[int(index)]["partition"] = "test" if fold == 0 else "validation" if fold == 1 else "train"
    for partition in ("train", "validation", "test"):
        if {r["source_label"] for r in rows if r["partition"] == partition} != set(labels):
            raise ValueError(f"Partition {partition} lacks classes; collect more independent image groups")


def preserve_source_partitions(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Keep original holdouts; remove related images from lower-priority splits.

    Roboflow applies its export augmentations to train only. Reassigning those
    images to a holdout would make the evaluation depend on augmented frames.
    """
    priority = {"train": 0, "validation": 1, "test": 2}
    groups = defaultdict(list)
    for row in rows:
        if row.get("source_partition") not in priority:
            raise ValueError("Preserving source splits requires train/valid/test export directories")
        groups[row["duplicate_group"]].append(row)
    kept, excluded = [], []
    for matches in groups.values():
        selected = max((r["source_partition"] for r in matches), key=priority.get)
        for row in matches:
            if row["source_partition"] == selected:
                row["partition"] = selected
                kept.append(row)
            else:
                excluded.append({"path": row["image_path"], "reason": "image_group_overlaps_higher_priority_holdout", "source_partition": row["source_partition"], "held_out_partition": selected})
    classes = {r["source_label"] for r in kept}
    if len(classes) < 2:
        raise ValueError("Need at least two classes")
    for partition in priority:
        if {r["source_label"] for r in kept if r["partition"] == partition} != classes:
            raise ValueError(f"No class-complete {partition} after removing overlapping image groups")
    return kept, excluded


def audit_source(root: Path, output: Path, provenance: dict, labels: list[str] | None = None, seed: int = 42, preserve_splits: bool = False) -> dict:
    import numpy as np
    from PIL import Image, ImageOps

    for key in ("name", "url", "license", "species", "label_limitations"):
        if not provenance.get(key):
            raise ValueError(f"Provenance requires {key}")
    if output.exists():
        raise ValueError(f"Output already exists; choose a fresh audit directory: {output}")
    candidates, excluded = discover_images(root)
    lineage_file = root / "crop-lineage.jsonl"
    crop_lineage = {row["crop_path"]: row for row in (json.loads(line) for line in lineage_file.read_text(encoding="utf-8").splitlines())} if lineage_file.exists() else {}
    rows = []
    thumbnails = {}
    for path, label in candidates:
        if labels and label not in labels:
            excluded.append({"path": str(path), "source_label": label, "reason": "class_not_selected"})
            continue
        try:
            with Image.open(path) as original:
                rgb = ImageOps.exif_transpose(original).convert("RGB")
                rgb.load()
                if min(rgb.size) < 32:
                    raise ValueError("image smaller than 32 pixels")
                pixel_hash = hashlib.sha256(str(rgb.size).encode() + rgb.tobytes()).hexdigest()
                thumbnails[pixel_hash] = np.asarray(rgb.resize((32, 32)), dtype=np.int16)
                gray = rgb.convert("L").resize((9, 8)).tobytes()
                dhash = sum(int(gray[y * 9 + x] > gray[y * 9 + x + 1]) << (y * 8 + x) for y in range(8) for x in range(8))
                dimensions = list(rgb.size)
            source_partition = path.resolve().relative_to(root.resolve()).parts[0]
            source_partition = "validation" if source_partition in {"valid", "val", "validation"} else source_partition
            rows.append({"image_path": str(path.resolve()), "source_label": label, "source_sha256": sha256(path), "source_partition": source_partition,
                         "pixel_sha256": pixel_hash, "dhash": f"{dhash:016x}", "source_stem": source_stem(path),
                         "dimensions": dimensions, "physical_egg_id": None, "batch_id": None})
            if path.resolve().relative_to(root.resolve()).as_posix() in crop_lineage:
                rows[-1]["crop_provenance"] = crop_lineage[path.resolve().relative_to(root.resolve()).as_posix()]
        except (OSError, ValueError) as error:
            excluded.append({"path": str(path), "reason": "invalid_image", "detail": str(error)})
    by_pixels = defaultdict(list)
    for row in rows:
        by_pixels[row["pixel_sha256"]].append(row)
    deduped = []
    for matches in by_pixels.values():
        if len({r["source_label"] for r in matches}) > 1:
            excluded.extend({"path": r["image_path"], "reason": "identical_image_conflicting_labels"} for r in matches)
        else:
            deduped.append(matches[0])
            excluded.extend({"path": r["image_path"], "reason": "identical_decoded_image"} for r in matches[1:])
    rows = deduped
    parents = list(range(len(rows)))

    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    # Conservative image grouping: original filename and near-identical dHash.
    # This is NOT a claim that all images of the same physical egg were found.
    hashes = [int(row["dhash"], 16) for row in rows]
    for i, row in enumerate(rows):
        for j in range(i):
            if row["source_stem"] == rows[j]["source_stem"] or near_duplicate(hashes[i], hashes[j], thumbnails[row["pixel_sha256"]], thumbnails[rows[j]["pixel_sha256"]]):
                parents[find(i)] = find(j)
    for i, row in enumerate(rows):
        row["duplicate_group"] = f"image-group-{find(i):06d}"
    split_method = "5-fold stratification with shared filename and visually near-duplicate groups; folds 0=test, 1=validation, remaining=train"
    if preserve_splits:
        rows, overlap_exclusions = preserve_source_partitions(rows)
        excluded.extend(overlap_exclusions)
        split_method = "Preserve original export splits; image groups assigned priority test > validation > train, removing members in lower-priority splits. Export train augmentations never enter holdouts."
    else:
        assign_partitions(rows, seed)
    report = {"status": "EXPLORATORY_PUBLIC_DATA_ONLY", "provenance": provenance,
              "source_root": str(root.resolve()), "seed": seed, "discovered_images": len(candidates),
              "retained_images": len(rows), "class_counts": dict(Counter(r["source_label"] for r in rows)),
              "partition_counts": {p: dict(Counter(r["source_label"] for r in rows if r["partition"] == p)) for p in ("train", "validation", "test")},
              "image_group_count": len({r["duplicate_group"] for r in rows}),
              "image_group_algorithm": "shared original filename OR (dHash distance <=3 AND RGB 32x32 mean absolute difference <=6/255)",
              "unique_physical_eggs": None, "exclusion_counts": dict(Counter(r["reason"] for r in excluded)),
              "split_method": split_method,
              "limitations": ["Egg/batch identity is unavailable. Image grouping cannot guarantee physical-egg isolation.",
                              "Public source annotations are not verified chronological age, viability, or food-safety truth.",
                              "Test results describe this public source only; no prospective device or farm validation."]}
    output.mkdir(parents=True)
    manifest = output / "manifest.jsonl"
    manifest.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    report["manifest_sha256"] = sha256(manifest)
    (output / "audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (output / "excluded.jsonl").write_text("".join(json.dumps(r) + "\n" for r in excluded), encoding="utf-8")
    make_contact_sheet(rows, output / "contact-sheet.jpg")
    return report


def make_contact_sheet(rows: list[dict], path: Path, per_class: int = 12) -> None:
    import random
    from PIL import Image, ImageDraw, ImageOps
    labels = sorted({r["source_label"] for r in rows})
    sheet = Image.new("RGB", (6 * 180, len(labels) * 2 * 160), "white")
    draw = ImageDraw.Draw(sheet)
    for c, label in enumerate(labels):
        items, seen_groups = [], set()
        for partition in ("train", "validation", "test"):
            candidates = [r for r in rows if r["source_label"] == label and r["partition"] == partition]
            random.Random(42).shuffle(candidates)
            selected = 0
            for row in candidates:
                group = row.get("duplicate_group", row["image_path"])
                if group not in seen_groups:
                    items.append(row)
                    seen_groups.add(group)
                    selected += 1
                if selected >= per_class // 3:
                    break
        for i, row in enumerate(items):
            x, y = (i % 6) * 180, (c * 2 + i // 6) * 160
            with Image.open(row["image_path"]) as im:
                thumb = ImageOps.contain(ImageOps.exif_transpose(im).convert("RGB"), (174, 130))
            sheet.paste(thumb, (x, y))
            draw.text((x + 3, y + 133), label[:26], fill="black")
            draw.text((x + 3, y + 147), row["partition"], fill="black")
    sheet.save(path, quality=90)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--labels", nargs="+")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--preserve-source-splits", action="store_true")
    args = parser.parse_args()
    report = audit_source(args.source, args.output, json.loads(args.provenance.read_text(encoding="utf-8")), args.labels, args.seed, args.preserve_source_splits)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
