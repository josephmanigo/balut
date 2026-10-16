import hashlib

import pytest
from PIL import Image
from pydantic import ValidationError

from balut_ml.dataset import DatasetFrame, audit_rows


def make_frame(**overrides) -> DatasetFrame:
    data = {
        "frame_id": "FRAME-0001",
        "inspection_id": "INSPECTION-0001",
        "physical_egg_id": "EGG-001",
        "batch_id": "BATCH-001",
        "image_path": "images/frame-0001.jpg",
        "source_sha256": "a" * 64,
        "view_index": 0,
        "angle_degrees": 0,
        "label": "DAY_16_LIKE",
        "label_authority": "two_reviewer_adjudication",
        "partition": "train",
        "recorded_elapsed_hours": 384,
        "reviewer_disposition_ids": ["REVIEW-A", "REVIEW-B"],
    }
    data.update(overrides)
    return DatasetFrame.model_validate(data)


def test_detects_physical_egg_leakage() -> None:
    rows = [
        make_frame(),
        make_frame(
            frame_id="FRAME-0002",
            source_sha256="b" * 64,
            view_index=1,
            partition="validation",
        ),
    ]
    report = audit_rows(rows, require_batch_partition_isolation=False)
    assert not report.valid
    assert any("physical egg crosses partitions" in error for error in report.errors)


def test_detects_augmentation_outside_training() -> None:
    row = make_frame(
        partition="validation",
        is_augmented=True,
        parent_frame_id="FRAME-PARENT",
    )
    report = audit_rows([row], require_batch_partition_isolation=False)
    assert not report.valid
    assert any("augmented frame outside train" in error for error in report.errors)


def test_valid_eight_view_session_passes_contract() -> None:
    rows = [
        make_frame(
            frame_id=f"FRAME-{index:04d}",
            source_sha256=f"{index + 1:064x}",
            view_index=index,
            angle_degrees=index * 45,
        )
        for index in range(8)
    ]
    report = audit_rows(rows)
    assert report.valid
    assert report.row_count == 8
    assert report.physical_egg_count == 1
    assert not report.warnings


def test_files_must_match_declared_hash_and_decode(tmp_path):
    image = tmp_path / "egg.png"
    Image.new("RGB", (64, 64), "red").save(image)
    row = make_frame(image_path="egg.png", source_sha256=hashlib.sha256(image.read_bytes()).hexdigest())
    assert audit_rows([row], require_files=True, manifest_root=tmp_path).valid
    Image.new("RGB", (64, 64), "blue").save(image)
    report = audit_rows([row], require_files=True, manifest_root=tmp_path)
    assert not report.valid and any("SHA-256 mismatch" in error for error in report.errors)
    image.write_bytes(b"not an image")
    row = row.model_copy(update={"source_sha256": hashlib.sha256(image.read_bytes()).hexdigest()})
    assert not audit_rows([row], require_files=True, manifest_root=tmp_path).valid


def test_different_file_hashes_cannot_hide_identical_pixels_across_eggs(tmp_path):
    image = Image.new("RGB", (64, 64), "red")
    rows = []
    for index, compression in enumerate((0, 9)):
        path = tmp_path / f"{index}.png"
        image.save(path, compress_level=compression)
        rows.append(make_frame(frame_id=f"FRAME-{index:04d}", inspection_id=f"INSPECT-{index}",
                               physical_egg_id=f"EGG-{index}", batch_id=f"BATCH-{index}", image_path=path.name,
                               partition="train" if index == 0 else "prospective_test",
                               source_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    report = audit_rows(rows, require_files=True, manifest_root=tmp_path)
    assert not report.valid and any("identical decoded image" in error for error in report.errors)


@pytest.mark.parametrize("overrides,reason", [
    ({}, "duplicate inspection view"),
    ({"view_index": 1, "physical_egg_id": "OTHER-EGG"}, "inspection has conflicting"),
    ({"is_augmented": True, "parent_frame_id": "UNKNOWN-FRAME"}, "augmentation parent"),
    ({"is_augmented": True, "parent_frame_id": "FRAME-0001", "physical_egg_id": "OTHER-EGG"}, "augmentation changes"),
])
def test_session_and_augmentation_identity_cannot_be_fabricated(overrides, reason):
    rows = [make_frame(), make_frame(frame_id="FRAME-0002", source_sha256="b" * 64, **overrides)]
    report = audit_rows(rows)
    assert not report.valid and any(reason in error for error in report.errors)


def test_reviewer_references_must_be_distinct_and_age_finite():
    report = audit_rows([make_frame(label="REJECT_SUSPECT", reviewer_disposition_ids=["REVIEW-A", "REVIEW-A"])])
    assert any("two reviewer" in warning for warning in report.warnings)
    with pytest.raises(ValidationError):
        make_frame(recorded_elapsed_hours=float("inf"))
