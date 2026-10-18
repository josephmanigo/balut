import json

import pytest

from balut_ml import camera_pilot


def test_development_loader_does_not_open_test_images_and_detects_tampering(tmp_path, monkeypatch):
    monkeypatch.setattr(camera_pilot, "DATA", tmp_path)
    split = {}
    for age in (16, 18):
        for index in range(1, 6):
            egg = f"{age}-{index}"
            split[egg] = "train"
            image = tmp_path / f"{egg}.jpg"
            image.write_bytes(egg.encode())
            camera_pilot.write_new(tmp_path / f"{egg}.json", {
                "egg_id": egg, "image": image.name, "reported_age_days": age,
                "partition": "train", "sha256": camera_pilot.sha(image), "freshness": "queued_frame_discarded"})
    # Missing test files must not be touched during fitting.
    split["16-12"] = "test"
    camera_pilot.write_new(tmp_path / "capture-plan.json", {"split": split})
    assert len(camera_pilot.records({"train"})) == 10
    (tmp_path / "16-1.jpg").write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        camera_pilot.records({"train"})


def test_fitting_and_test_refuse_overwrite_or_changed_locked_code(tmp_path, monkeypatch):
    monkeypatch.setattr(camera_pilot, "RUN", tmp_path)
    with pytest.raises(FileExistsError, match="never refit"):
        camera_pilot.run("fit")
    (tmp_path / "selection-lock.json").write_text(json.dumps({"evaluator_sha256": "changed"}))
    with pytest.raises(ValueError, match="evaluation code changed"):
        camera_pilot.run("test")
    (tmp_path / "test-report.json").write_text("{}")
    with pytest.raises(FileExistsError, match="already evaluated"):
        camera_pilot.run("test")
