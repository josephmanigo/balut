import hashlib
import json

import pytest
from PIL import Image

from balut_ml import camera_angles
from test_camera_angles import angles_dataset
from test_retained_camera import camera_dataset


@pytest.fixture
def reject_dataset(angles_dataset, monkeypatch):
    camera_angles.build_dataset(partial=True)
    base = camera_angles.DATA
    capture = camera_angles.ROOT / "output/physical-reject-20261019"
    capture.mkdir()
    data = camera_angles.ROOT / "reject-dataset"
    plan = capture / "collection-plan.json"
    authority = "Vendor labeled Reject; rejection reason not supplied or independently confirmed"
    splits = {"R1": "train", "R2": "validation", "R3": "test"}
    plan.write_text(json.dumps({"egg_partitions": splits, "base_manifest_sha256": camera_angles.sha(base / "manifest.jsonl"),
                               "label_authority": authority, "shell_marks": "operator_reports_unmarked_shells", "uncooked": True}))
    for number, (egg, split) in enumerate(splits.items()):
        folder = capture / egg
        folder.mkdir()
        views = []
        for index in range(50):
            path = folder / f"view-{index+1}.jpg"
            Image.new("RGB", (600, 800), (30+number*10, 40+index*3, 55)).save(path)
            with Image.open(path) as image:
                rgb = image.convert("RGB")
                pixels = hashlib.sha256(str(rgb.size).encode() + rgb.tobytes()).hexdigest()
            views.append({"view_index": index+1, "image": path.name, "sha256": camera_angles.sha(path),
                          "pixel_sha256": pixels, "motor_steps": 100+(index*2048+49)//50,
                          "angle_bin": index, "angles_verified": False})
        record = {"egg_id": egg, "partition": split, "source_label": "REJECT", "physical_egg_id": f"physical-reject-20261019:{egg}",
                  "model_used_for_label": False, "reject_plan_sha256": camera_angles.sha(plan),
                  "label_authority": authority, "label_reference": authority, "defect_independently_confirmed": False, "uncooked": True,
                  "capture_protocol": "fifty-paused-views-v1", "capture_session_id": capture.name, "target_views": 50,
                  "steps_per_revolution": 2048, "angle_origin_steps": 100, "angles_verified": False,
                  "completed": True, "shell_marks": "operator_reports_unmarked_shells", "views": views}
        (folder / "record.json").write_text(json.dumps(record))
    monkeypatch.setattr(camera_angles, "image_quality", lambda image, policy: ({}, []))
    return base, capture, data, plan


def test_reject_import_preserves_original_data_and_vendor_provenance(reject_dataset):
    base, capture, data, plan = reject_dataset
    previous = (base / "manifest.jsonl").read_bytes()
    audit = camera_angles.import_records(base, capture, data, 50, reject_plan=plan)
    assert audit["new_views"] == 150 and audit["completed_eggs"] == 3 and audit["physical_eggs_total"] == 33
    assert audit["new_view_partitions"] == {"train": 50, "validation": 50, "test": 50}
    assert audit["status"] == "EXPLORATORY_RETAINED_REJECT_DATASET" and not audit["test_reopened"]
    rows = list(map(json.loads, (data / "manifest.jsonl").read_text().splitlines()))
    original = list(map(json.loads, previous.splitlines()))
    assert rows[:len(original)] == original and (base / "manifest.jsonl").read_bytes() == previous
    for row in rows[len(original):]:
        assert row["source_label"] == "REJECT" and "Vendor labeled" in row["label_authority"]
        assert row["training_eligible"] == (row["partition"] == "train")
        assert row["capture_record"]["defect_independently_confirmed"] is False
        if row["partition"] == "test": assert row["test_status"] == "closed_reject_collection_test"
    assert camera_angles.import_records(base, capture, data, 50, reject_plan=plan)["manifest_sha256"] == audit["manifest_sha256"]


@pytest.mark.parametrize("mutation", ["partition", "label", "plan", "bin", "pixels"])
def test_reject_import_rejects_changed_identity_or_capture(reject_dataset, mutation):
    base, capture, data, plan = reject_dataset
    path = capture / "R3/record.json"
    record = json.loads(path.read_text())
    if mutation == "partition": record["partition"] = "train"
    if mutation == "label": record["source_label"] = "DAY_16"
    if mutation == "plan": record["reject_plan_sha256"] = "0"*64
    if mutation == "bin": record["views"][1].update(angle_bin=0, motor_steps=100)
    if mutation == "pixels": record["views"][1]["pixel_sha256"] = "0"*64
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        camera_angles.import_records(base, capture, data, 50, reject_plan=plan)
    assert not data.exists()


def test_partial_reject_capture_cannot_be_finalized(reject_dataset):
    base, capture, data, plan = reject_dataset
    path = capture / "R2/record.json"
    record = json.loads(path.read_text())
    record.update(completed=False, views=record["views"][:1])
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="3 numbered"):
        camera_angles.import_records(base, capture, data, 50, reject_plan=plan)
    audit = camera_angles.import_records(base, capture, data, 50, partial=True, reject_plan=plan)
    assert audit["new_views"] == 101 and audit["completed_eggs"] == 2 and audit["status"] == "COLLECTION_IN_PROGRESS"
