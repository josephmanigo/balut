import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from balut_ml import camera_pilot, retained_camera


@pytest.fixture
def camera_dataset(tmp_path, monkeypatch):
    pilot, base = tmp_path / "pilot", tmp_path / "base"
    pilot.mkdir()
    base.mkdir()
    run = pilot / "candidate"
    run.mkdir()
    (run / "selection-lock.json").write_text("{}")
    (run / "test-report.json").write_text("{}")
    history = tmp_path / "historical.jsonl"
    old = {"source_sha256": "old-file", "pixel_sha256": "old-pixels", "duplicate_group": "old-group",
           "partition": "train", "source_label": "REJECT"}
    history.write_text(json.dumps(old) + "\n")
    (base / "config.json").write_text(json.dumps({"manifest_sha256": retained_camera.sha256(history)}))
    (base / "gate-policy.json").write_text(json.dumps({"quality": {
        "minimum_short_side": 64, "minimum_grayscale_std": 8, "minimum_edge_variance": 20, "maximum_clipped_fraction": .85}}))
    split = {}
    for age in (16, 18):
        for index in range(1, 16):
            egg = f"{age}-{index}"
            partition = "train" if index in (1, 2, 3, 6, 7) else "test" if index in (5, 12, 13, 14, 15) else "validation"
            split[egg] = partition
            photo = pilot / f"{egg}.jpg"
            Image.new("RGB", (600, 800), (age * 5, index * 10, 90)).save(photo)
            record = {"egg_id": egg, "reported_age_days": age, "partition": partition, "image": photo.name,
                      "sha256": retained_camera.sha256(photo), "freshness": "live_stream_refreshed",
                      "model_used_for_label": False, "label_authority": "User reports farm incubation date"}
            (pilot / f"{egg}.json").write_text(json.dumps(record))
    (pilot / "capture-plan.json").write_text(json.dumps({"split": split}))
    monkeypatch.setattr(camera_pilot, "DATA", pilot)
    monkeypatch.setattr(camera_pilot, "RUN", run)
    monkeypatch.setattr(retained_camera, "BASE", base)
    monkeypatch.setattr(retained_camera, "HISTORY", history)
    monkeypatch.setattr(retained_camera, "DATA", tmp_path / "dataset")
    return pilot, history, old


def test_import_adds_30_original_images_without_changing_history_or_roles(camera_dataset):
    pilot, history, old = camera_dataset
    history_hash = retained_camera.sha256(history)
    audit = retained_camera.build_dataset()
    rows, local, _ = retained_camera.load_dataset()
    assert len(rows) == 31 and rows[0] == old
    assert audit["camera_partitions"] == {"train": 10, "validation": 10, "test": 10}
    assert retained_camera.sha256(history) == history_hash
    for row in local:
        original = pilot / row["capture_record"]["image"]
        assert retained_camera.sha256(original) == retained_camera.sha256(Path(row["image_path"]))
        assert row["verified_incubation_hours"] is None
        if row["partition"] == "test":
            assert not row["training_eligible"] and row["test_status"] == "closed_original_pilot_test"
    with pytest.raises(FileExistsError):
        retained_camera.build_dataset()


def test_import_rejects_duplicate_before_writing_dataset(camera_dataset):
    pilot, _, _ = camera_dataset
    (pilot / "18-1.jpg").write_bytes((pilot / "16-1.jpg").read_bytes())
    record = retained_camera.read(pilot / "18-1.json")
    record["sha256"] = retained_camera.sha256(pilot / "18-1.jpg")
    (pilot / "18-1.json").write_text(json.dumps(record))
    with pytest.raises(ValueError, match="duplicate"):
        retained_camera.build_dataset()
    assert not retained_camera.DATA.exists()


def test_loader_rejects_test_egg_moved_to_training_even_with_new_manifest_hash(camera_dataset):
    retained_camera.build_dataset()
    manifest = retained_camera.DATA / "manifest.jsonl"
    rows = retained_camera.rows_from(manifest)
    next(r for r in rows if r.get("test_status"))["partition"] = "train"
    manifest.write_text("".join(json.dumps(r) + "\n" for r in rows))
    audit = retained_camera.read(retained_camera.DATA / "audit.json")
    audit["manifest_sha256"] = retained_camera.sha256(manifest)
    (retained_camera.DATA / "audit.json").write_text(json.dumps(audit))
    with pytest.raises(ValueError, match="partitions changed"):
        retained_camera.load_dataset()


def test_training_arrays_exclude_validation_test_and_bad_quality():
    rows = [{"source_label": label, "partition": partition, "training_eligible": eligible}
            for label, partition, eligible in [("DAY_16", "train", True), ("DAY_18", "train", True),
                ("DAY_16", "validation", True), ("DAY_18", "test", True), ("DAY_16", "train", False)]]
    features = np.arange(10).reshape(5, 2)
    x, y, eligible = retained_camera.training_arrays(np.array([[99, 99]]), np.array([2]), rows, features)
    np.testing.assert_array_equal(x, [[99, 99], [0, 1], [2, 3]])
    np.testing.assert_array_equal(y, [2, 0, 1])
    assert eligible.tolist() == [True, True, False, False, False]


def test_training_preserves_completed_run(tmp_path, monkeypatch):
    monkeypatch.setattr(retained_camera, "RUN", tmp_path)
    with pytest.raises(FileExistsError, match="preserve"):
        retained_camera.train()
