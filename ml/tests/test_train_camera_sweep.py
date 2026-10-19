import copy
import json

import numpy as np
import pytest

from balut_ml import train_camera_sweep as training
from scripts.camera_egg_ids import partition_for


def test_development_keeps_all_33_physical_egg_families_in_their_original_roles():
    rows = []
    for age in (16, 18):
        for index in range(1, 16):
            egg = f"{age}-{index}"
            _, split = partition_for(egg)
            rows += [{"physical_egg_id": f"physical-camera-20261018:{egg}", "source_label": f"DAY_{age}",
                      "partition": split, "test_status": "closed_original_pilot_test" if split == "test" else None} for _ in range(54)]
    for egg, split in (("R1", "train"), ("R2", "validation"), ("R3", "test")):
        rows += [{"physical_egg_id": f"physical-reject-20261019:{egg}", "source_label": "REJECT", "partition": split,
                  "capture_record": {"defect_independently_confirmed": False},
                  "test_status": "closed_reject_collection_test" if split == "test" else None} for _ in range(50)]
    development = training.development_rows(rows)
    assert len(development) == 1180 and not any(r["partition"] == "test" for r in development)
    assert len({r["physical_egg_id"] for r in development}) == 22
    rows[-1]["partition"] = "train"
    with pytest.raises(ValueError, match="Reject provenance or partition"):
        training.development_rows(rows)


def test_fifty_views_form_sixteen_correlated_scans_of_one_physical_egg():
    rows = [{"physical_egg_id": "R2", "source_label": "REJECT", "source_sha256": str(i),
             "capture_record": {"angle_bin": i}} for i in reversed(range(50))]
    outcomes = [{"sourcePrediction": "REJECT", "analysisOutcome": "CLASSIFIED", "recaptureRequested": False, "recaptureReasons": []} for _ in rows]
    scores = np.array([[0, 0, 4]] * 50)
    report, scans = training.scan_report(rows, scores, outcomes)
    assert report["physical_eggs"] == 1 and report["correlated_scans"] == 16
    assert report["correct_classified"] == 16 and report["coverage"] == 1
    assert report["by_true_class"]["REJECT"]["physical_eggs"] == 1
    assert len(scans) == 16
    rows[1]["capture_record"]["angle_bin"] = rows[0]["capture_record"]["angle_bin"]
    with pytest.raises(ValueError, match="50 distinct"):
        training.scan_report(rows, scores, outcomes)


def test_admission_rejects_higher_accuracy_obtained_by_reducing_class_support():
    before = {"correct_classified": 24, "by_true_class": {label: {"scans": 16, "correct_classified": 8,
              "raw_correct": 12, "wrong_classified": 1, "classified": 9} for label in training.CLASSES}}
    after = copy.deepcopy(before)
    after["correct_classified"] = 25
    after["by_true_class"]["DAY_16"]["correct_classified"] = 10
    after["by_true_class"]["REJECT"].update(correct_classified=7, classified=7, wrong_classified=0)
    historical = {"selective": {"correct_classified": 8, "wrong_classified": 0}, "raw": {"correct": 9, "macro_f1": .9}}
    original = {"correct_classified": 8, "wrong_classified": 0, "raw_correct": 9}
    failures = training.admission(before, after, historical, historical, original, original, historical, historical)
    assert any("REJECT" in f for f in failures)


def test_training_cannot_start_before_the_three_reject_eggs_are_complete(tmp_path, monkeypatch):
    (tmp_path / "audit.json").write_text(json.dumps({"status": "COLLECTION_IN_PROGRESS"}))
    monkeypatch.setattr(training, "DATA", tmp_path)
    monkeypatch.setattr(training, "RUN", tmp_path / "candidate")
    with pytest.raises(ValueError, match="Complete and verify"):
        training.run()
    assert not training.RUN.exists()
