import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from balut_ml.public_data import discover_images, source_stem
from balut_ml.train_public import load_audited_rows


def test_archive_rejects_traversal_before_writing(tmp_path):
    from balut_ml.extract_public import extract_archive
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as source:
        source.writestr("../escape.txt", "bad")
    with pytest.raises(ValueError, match="Unsafe archive path"):
        extract_archive(archive, tmp_path / "output")
    assert not (tmp_path / "output").exists()
    assert not (tmp_path / "escape.txt").exists()


def test_archive_preserves_license_and_hash(tmp_path):
    from balut_ml.extract_public import extract_archive
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as source:
        source.writestr("README.dataset.txt", "Source and licence")
    report = extract_archive(archive, tmp_path / "output")
    assert (tmp_path / "output" / "README.dataset.txt").read_text() == "Source and licence"
    assert report["archive_sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()


def test_csv_does_not_convert_multiple_labels_to_single_ground_truth(tmp_path):
    (tmp_path / "_classes.csv").write_text("filename, fertile, infertile, abnormal\na.jpg,1,0,0\nb.jpg,1,1,0\nc.jpg,0,0,0\n")
    samples, excluded = discover_images(tmp_path)
    assert samples == [((tmp_path / "a.jpg").resolve(), "fertile")]
    assert [e["reason"] for e in excluded] == ["ambiguous_or_missing_label"] * 2


def test_csv_path_escape_is_rejected(tmp_path):
    (tmp_path / "_classes.csv").write_text("filename,fertile\n../external.jpg,1\n")
    with pytest.raises(ValueError, match="escapes"):
        discover_images(tmp_path)


def test_export_variants_share_original_image_identity():
    assert source_stem(Path("egg_16_jpg.rf.abc123.jpg")) == source_stem(Path("egg_16_jpg.rf.def456.jpg"))


def test_source_holdouts_exclude_related_training_augmentations():
    from balut_ml.public_data import preserve_source_partitions
    rows = [{"image_path": f"{label}-{p}", "source_label": label, "source_partition": p, "duplicate_group": f"{label}-{p}"} for label in ("fertile", "infertile") for p in ("train", "validation", "test")]
    rows.append({"image_path": "train-augmentation", "source_label": "fertile", "source_partition": "train", "duplicate_group": "fertile-test"})
    kept, excluded = preserve_source_partitions(rows)
    assert len(kept) == 6
    assert excluded[0]["path"] == "train-augmentation"
    assert all(r["partition"] == r["source_partition"] for r in kept)


def test_multiple_egg_crops_keep_source_photo_group_identity():
    assert source_stem(Path("tray.rf.aaaa__crop-1.png")) == source_stem(Path("tray.rf.bbbb__crop-2.png"))


def test_same_silhouette_with_different_color_is_not_a_duplicate():
    np = pytest.importorskip("numpy")
    from balut_ml.public_data import near_duplicate
    dark = np.full((32, 32, 3), 30, dtype=np.int16)
    bright = np.full((32, 32, 3), 180, dtype=np.int16)
    assert not near_duplicate(123, 123, dark, bright)
    assert near_duplicate(123, 123, dark, dark + 2)


def test_coco_crop_preserves_box_label_and_provenance(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    from balut_ml.crop_public_coco import crop_source
    source = tmp_path / "source" / "train"
    source.mkdir(parents=True)
    Image.new("RGB", (120, 90), "red").save(source / "tray.png")
    data = {"images": [{"id": 1, "file_name": "tray.png", "width": 120, "height": 90}],
            "categories": [{"id": 1, "name": "Reject"}, {"id": 2, "name": "Fertilized"}],
            "annotations": [{"id": 1, "image_id": 1, "category_id": 1, "bbox": [10, 5, 40, 50]},
                            {"id": 2, "image_id": 1, "category_id": 2, "bbox": [60, 5, 40, 50]}]}
    (source / "_annotations.coco.json").write_text(json.dumps(data))
    output = tmp_path / "crops"
    report = crop_source(source.parent, output, ["Reject"])
    assert report["class_counts"] == {"Reject": 1}
    lineage = json.loads((output / "crop-lineage.jsonl").read_text())
    assert lineage["annotation_id"] == 1
    assert lineage["original_bbox_xywh"] == [10, 5, 40, 50]
    assert lineage["physical_egg_id"] is None
    with Image.open(output / lineage["crop_path"]) as crop:
        assert crop.size == (40, 50)


def write_manifest(tmp_path, rows):
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text("".join(json.dumps(r) + "\n" for r in rows))
    (tmp_path / "audit.json").write_text(json.dumps({"status": "EXPLORATORY_PUBLIC_DATA_ONLY", "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest()}))
    return manifest


def test_changed_manifest_is_rejected_before_loading_training_dependencies(tmp_path):
    manifest = write_manifest(tmp_path, [])
    manifest.write_text("{}\n")
    with pytest.raises(ValueError, match="Manifest changed"):
        load_audited_rows(manifest)


def test_image_group_cannot_cross_train_and_test(tmp_path):
    path = tmp_path / "fake.jpg"
    path.write_bytes(b"fixture; decoded-image audit is tested separately")
    rows = [{"image_path": str(path), "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "pixel_sha256": "pixel", "duplicate_group": "same-egg-image", "partition": p, "source_label": "fertile"} for p in ("train", "test")]
    with pytest.raises(ValueError, match="Leakage"):
        load_audited_rows(write_manifest(tmp_path, rows))


def test_changed_image_is_rejected(tmp_path):
    path = tmp_path / "fake.jpg"
    path.write_bytes(b"changed image")
    rows = [{"image_path": str(path), "source_sha256": "0" * 64, "pixel_sha256": "pixel", "duplicate_group": "group1", "partition": "train", "source_label": "fertile"}]
    with pytest.raises(ValueError, match="changed image"):
        load_audited_rows(write_manifest(tmp_path, rows))


def test_grouped_split_keeps_all_variants_together():
    pytest.importorskip("sklearn")
    from balut_ml.public_data import assign_partitions
    rows = [{"source_label": label, "duplicate_group": f"{label}-{group}"} for label in ("fertile", "infertile") for group in range(20) for variant in range(2)]
    assign_partitions(rows)
    for group in {r["duplicate_group"] for r in rows}:
        assert len({r["partition"] for r in rows if r["duplicate_group"] == group}) == 1
    for partition in ("train", "validation", "test"):
        assert {r["source_label"] for r in rows if r["partition"] == partition} == {"fertile", "infertile"}


def test_small_source_cannot_create_misleading_holdout():
    pytest.importorskip("sklearn")
    from balut_ml.public_data import assign_partitions
    with pytest.raises(ValueError, match="10 independent image groups"):
        assign_partitions([{"source_label": "fertile", "duplicate_group": "one"}])


def test_audit_decodes_images_removes_duplicates_and_excludes_conflicts(tmp_path):
    pytest.importorskip("sklearn")
    np = pytest.importorskip("numpy")
    Image = pytest.importorskip("PIL.Image")
    from balut_ml.public_data import audit_source
    root = tmp_path / "source"
    rng = np.random.default_rng(72)
    for label in ("fertile", "infertile"):
        (root / label).mkdir(parents=True)
        for i in range(30):
            Image.fromarray(rng.integers(0, 256, (48, 48, 3), dtype=np.uint8)).save(root / label / f"{label}-{i}.png")
    original = root / "fertile" / "fertile-0.png"
    (root / "fertile" / "same.png").write_bytes(original.read_bytes())
    (root / "infertile" / "conflict.png").write_bytes((root / "fertile" / "fertile-1.png").read_bytes())
    (root / "fertile" / "bad.jpg").write_bytes(b"not an image")
    result = audit_source(root, tmp_path / "audit", {"name": "synthetic software test only", "url": "https://example.com/fixture", "license": "test", "species": "none", "label_limitations": "synthetic fixture; never model evidence"})
    assert result["retained_images"] == 59
    assert result["exclusion_counts"] == {"invalid_image": 1, "identical_decoded_image": 1, "identical_image_conflicting_labels": 2}
    assert result["unique_physical_eggs"] is None
    assert (tmp_path / "audit" / "contact-sheet.jpg").is_file()
    load_audited_rows(tmp_path / "audit" / "manifest.jsonl")
