import json

import numpy as np
import pytest

from balut_ml import train_camera_angles as training


def test_camera_weights_do_not_count_repeat_photos_as_independent_eggs():
    rows = [{"physical_egg_id": egg, "source_label": label, "partition": "train", "training_eligible": True}
            for egg, label, count in (("16-1", "DAY_16", 4), ("18-1", "DAY_18", 2)) for _ in range(count)]
    weights, classes = training.grouped_weights(np.array([0, 1, 2, 2]), rows)
    np.testing.assert_array_equal(weights[:4], np.ones(4))
    assert weights[4:8].sum() == weights[8:].sum() == 20
    assert classes == {0: 1.0, 1: 1.0, 2: 1.0}
    rows[-1]["partition"] = "test"
    with pytest.raises(ValueError, match="training"):
        training.grouped_weights(np.array([0, 1, 2, 2]), rows)


def test_validation_report_counts_eggs_and_keeps_view_disagreement_uncertain():
    rows = [{"physical_egg_id": egg, "source_label": label, "source_sha256": f"{egg}-{index}"}
            for egg, label in (("16-4", "DAY_16"), ("18-4", "DAY_18")) for index in range(3)]
    labels = ["DAY_16", "DAY_16", None, "DAY_18", "DAY_16", None]
    outcomes = [{"sourcePrediction": label, "analysisOutcome": "CLASSIFIED" if label else "RECAPTURE_REQUIRED",
                 "recaptureRequested": label is None, "recaptureReasons": [] if label else ["AMBIGUOUS_APPEARANCE"]} for label in labels]
    scores = np.array([[4, 0, 0]] * 3 + [[0, 4, 0]] * 3)
    report, eggs = training.group_report(rows, scores, outcomes)
    assert report["physical_eggs"] == 2 and report["classified"] == report["correct_classified"] == 1
    assert report["coverage"] == .5 and report["raw_correct"] == 2
    assert eggs[1]["sourcePrediction"] is None and "MULTIVIEW_DISAGREEMENT" in eggs[1]["recaptureReasons"]


def test_training_refuses_an_incomplete_capture_collection(tmp_path, monkeypatch):
    (tmp_path / "audit.json").write_text(json.dumps({"status": "COLLECTION_IN_PROGRESS"}))
    monkeypatch.setattr(training, "DATA", tmp_path)
    monkeypatch.setattr(training, "RUN", tmp_path / "run")
    with pytest.raises(ValueError, match="30 numbered"):
        training.run()
    assert not training.RUN.exists()
