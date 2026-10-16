import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from balut_ml.local_photo_data import COLLECTION, frame_image, import_photos, load_local_rows
from balut_ml.public_data import sha256
from balut_ml.adapt_local_photos import validate_disjoint


def audited_local(tmp_path):
    photo = tmp_path / "photo.jpg"
    Image.new("RGB", (80, 90), "red").save(photo)
    row = {"image_path": str(photo), "source_sha256": sha256(photo), "original_path": str(photo),
           "original_sha256": sha256(photo), "pixel_sha256": "known-pixels", "partition": "train",
           "duplicate_group": COLLECTION + ":unknown-egg-batch", "source_label": "DAY_16"}
    manifest = tmp_path / "manifest.jsonl"
    save_manifest(manifest, row)
    return manifest, photo, row


def save_manifest(manifest, row):
    manifest.write_text(json.dumps(row) + "\n")
    manifest.with_name("audit.json").write_text(json.dumps({"status": "EXPLORATORY_USER_DATA_ONLY", "manifest_sha256": sha256(manifest)}))


def test_changed_photo_and_manifest_fail_closed(tmp_path):
    manifest, photo, row = audited_local(tmp_path)
    assert len(load_local_rows(manifest)[0]) == 1
    Image.new("RGB", (80, 90), "blue").save(photo)
    with pytest.raises(ValueError, match="Changed local photo"):
        load_local_rows(manifest)
    manifest.write_text("{}\n")
    with pytest.raises(ValueError, match="changed local dataset"):
        load_local_rows(manifest)


def test_unknown_egg_photos_cannot_move_into_holdout(tmp_path):
    manifest, _, row = audited_local(tmp_path)
    row["partition"] = "test"
    save_manifest(manifest, row)
    with pytest.raises(ValueError, match="remain together in training"):
        load_local_rows(manifest)


def test_overlap_checks_originals_even_when_crop_is_different():
    incoming = [{"source_sha256": "crop", "pixel_sha256": "crop-pixels", "original_sha256": "original", "partition": "train"}]
    existing = [{"source_sha256": "original", "pixel_sha256": "old-pixels"}]
    with pytest.raises(ValueError, match="overlaps"):
        validate_disjoint(incoming, existing)


def test_conflicting_duplicate_labels_rejected_before_copy(tmp_path):
    photo = tmp_path / "photo.jpeg"
    Image.new("RGB", (80, 90), "red").save(photo)
    rows = [{"path": str(photo), "sha256": sha256(photo), "pixel_sha256": "same", "label": label} for label in ("16", "18")]
    inventory = tmp_path / "inventory.jsonl"
    inventory.write_text("".join(json.dumps(r) + "\n" for r in rows))
    with pytest.raises(ValueError, match="conflicting labels"):
        import_photos(inventory, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_framing_preserves_pixels_without_exposure_editing():
    image = Image.new("RGB", (100, 100), (30, 40, 50))
    framed, box = frame_image(image)
    assert box == (8, 18, 92, 94)
    assert framed.size == (84, 76)
    assert np.all(np.asarray(framed) == [30, 40, 50])
