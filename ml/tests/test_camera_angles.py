import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

from balut_ml import camera_angles, retained_camera
from test_retained_camera import camera_dataset


@pytest.fixture
def angles_dataset(camera_dataset, tmp_path, monkeypatch):
    pilot, _, _ = camera_dataset
    retained_camera.build_dataset()
    root = tmp_path / "project"
    originals = root / "output/physical-pilot-20261018"
    originals.mkdir(parents=True)
    capture = root / "output/physical-multiangle-20261019"
    policy = root / "ml/runs/selective-v2/gate-policy.json"
    policy.parent.mkdir(parents=True)
    shutil.copyfile(retained_camera.BASE / "gate-policy.json", policy)
    for egg in ("16-1", "18-4", "16-5"):
        shutil.copyfile(pilot / f"{egg}.json", originals / f"{egg}.json")
        original = json.loads((pilot / f"{egg}.json").read_text())
        folder = capture / egg
        folder.mkdir(parents=True)
        views = []
        for index in range(1, 4):
            image = folder / f"view-{index}.jpg"
            Image.new("RGB", (600, 800), (int(egg[:2]) * 10, index * 35, int(egg[-1]) * 20)).save(image)
            views.append({"view_index": index, "image": image.name, "sha256": camera_angles.sha(image)})
        record = {"egg_id": egg, "reported_age_days": int(egg[:2]), "partition": original["partition"],
                  "physical_egg_id": f"physical-camera-20261018:{egg}", "model_used_for_label": False,
                  "original_record_sha256": camera_angles.sha(originals / f"{egg}.json"),
                  "capture_protocol": "three-paused-views-v1", "capture_session_id": "new-session",
                  "label_authority": original["label_authority"], "label_reference": "Original cohort", "views": views}
        (folder / "record.json").write_text(json.dumps(record))
    monkeypatch.setattr(camera_angles, "ROOT", root)
    monkeypatch.setattr(camera_angles, "BASE", retained_camera.DATA)
    monkeypatch.setattr(camera_angles, "CAPTURE", capture)
    monkeypatch.setattr(camera_angles, "DATA", root / "dataset")
    return capture


def test_repeat_views_keep_physical_egg_groups_and_closed_test_roles(angles_dataset):
    before = camera_angles.sha(camera_angles.BASE / "manifest.jsonl")
    audit = camera_angles.build_dataset(partial=True)
    assert audit["new_views"] == 9 and audit["captured_eggs"] == 3 and audit["independent_new_eggs"] == 0
    assert audit["status"] == "COLLECTION_IN_PROGRESS"
    rows = [json.loads(line) for line in (camera_angles.DATA / "manifest.jsonl").read_text().splitlines()]
    assert len(rows) == 40
    for egg, split in (("16-1", "train"), ("18-4", "validation"), ("16-5", "test")):
        family = [row for row in rows if row.get("physical_egg_id") == f"physical-camera-20261018:{egg}"]
        assert len(family) == 4 and {row["partition"] for row in family} == {split}
        if split != "train": assert not any(row["training_eligible"] for row in family)
        if split == "test": assert all(row["test_status"] == "closed_original_pilot_test" for row in family)
    assert camera_angles.sha(camera_angles.BASE / "manifest.jsonl") == before
    assert camera_angles.build_dataset(partial=True)["manifest_sha256"] == audit["manifest_sha256"]
    assert len(list((camera_angles.DATA / "snapshots").glob("*.jsonl"))) == 1


def test_incomplete_collection_cannot_be_finalized(angles_dataset):
    with pytest.raises(ValueError, match="30 numbered"):
        camera_angles.build_dataset()
    assert not camera_angles.DATA.exists()


def test_test_egg_cannot_be_relabelled_as_training(angles_dataset):
    path = angles_dataset / "16-5/record.json"
    record = json.loads(path.read_text())
    record["partition"] = "train"
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="partition"):
        camera_angles.build_dataset(partial=True)
    assert not camera_angles.DATA.exists()


def test_modified_view_is_rejected_before_dataset_write(angles_dataset):
    (angles_dataset / "16-1/view-1.jpg").write_bytes(b"changed")
    with pytest.raises(ValueError, match="image changed"):
        camera_angles.build_dataset(partial=True)
    assert not camera_angles.DATA.exists()
