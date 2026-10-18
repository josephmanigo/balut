import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image

from balut_ml import camera_angles
from test_camera_angles import angles_dataset
from test_retained_camera import camera_dataset


@pytest.fixture
def sweep_dataset(angles_dataset):
    camera_angles.build_dataset(partial=True)
    root = camera_angles.ROOT
    capture, data = root / "output/physical-50views-20261019", root / "sweep-dataset"
    for egg, count in (("16-1", 50), ("18-4", 1), ("16-5", 1)):
        record = json.loads((angles_dataset / egg / "record.json").read_text())
        folder = capture / egg
        folder.mkdir(parents=True)
        views = []
        for index in range(count):
            path = folder / f"view-{index+1}.jpg"
            Image.new("RGB", (600, 800), (90+int(egg[-1]), index*2, int(egg[:2])*10)).save(path)
            with Image.open(path) as image:
                rgb = image.convert("RGB")
                pixels = hashlib.sha256(str(rgb.size).encode() + rgb.tobytes()).hexdigest()
            views.append({"view_index": index+1, "image": path.name, "sha256": camera_angles.sha(path),
                          "pixel_sha256": pixels, "motor_steps": 100 + (index*2048+49)//50,
                          "angle_bin": index, "angles_verified": False})
        record.update(views=views, capture_protocol="fifty-paused-views-v1", target_views=50,
                      steps_per_revolution=2048, angle_origin_steps=100, angles_verified=False,
                      completed=count == 50, shell_marks="operator_reports_unmarked_shells")
        (folder / "record.json").write_text(json.dumps(record))
    return capture, data


def test_fifty_views_extend_the_preserved_dataset_without_crossing_egg_partitions(sweep_dataset):
    capture, data = sweep_dataset
    base = camera_angles.DATA
    before = (base / "manifest.jsonl").read_bytes()
    audit = camera_angles.import_records(base, capture, data, 50, partial=True)
    assert audit["new_views"] == 52 and audit["completed_eggs"] == 1 and audit["target_views"] == 1500
    assert audit["status"] == "COLLECTION_IN_PROGRESS" and not audit["test_reopened"]
    rows = [json.loads(line) for line in (data / "manifest.jsonl").read_text().splitlines()]
    original = [json.loads(line) for line in before.splitlines()]
    assert rows[:len(original)] == original
    for egg, split, count in (("16-1", "train", 54), ("18-4", "validation", 5), ("16-5", "test", 5)):
        family = [r for r in rows if r.get("physical_egg_id") == f"physical-camera-20261018:{egg}"]
        assert len(family) == count and {r["partition"] for r in family} == {split}
        if split != "train": assert not any(r["training_eligible"] for r in family)
    assert (base / "manifest.jsonl").read_bytes() == before
    assert camera_angles.import_records(base, capture, data, 50, partial=True)["manifest_sha256"] == audit["manifest_sha256"]
    with pytest.raises(ValueError, match="30 numbered"):
        camera_angles.import_records(base, capture, data, 50)


@pytest.mark.parametrize("mutation", ["repeated_bin", "pixels", "partition", "image"])
def test_tampered_or_repeated_sweep_data_is_rejected_before_import(sweep_dataset, mutation):
    capture, data = sweep_dataset
    path = capture / "16-1/record.json"
    record = json.loads(path.read_text())
    if mutation == "repeated_bin":
        record["views"][1].update(motor_steps=100, angle_bin=0)
    if mutation == "pixels": record["views"][1]["pixel_sha256"] = "0" * 64
    if mutation == "partition": record["partition"] = "validation"
    if mutation == "image": (capture / "16-1/view-2.jpg").write_bytes(b"corrupt")
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        camera_angles.import_records(camera_angles.DATA, capture, data, 50, partial=True)
    assert not data.exists()
