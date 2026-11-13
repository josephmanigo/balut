import json

import numpy as np
import pytest

from scripts.capture_emeet_egg import sha
from scripts.emeet_rotation_calibration import compare_rotation_floor


@pytest.mark.parametrize("extra_wrong,expected_floor", [(False, 15.), (True, 20.)])
def test_edge_change_needs_distributed_accuracy_gain_without_new_wrong_accepts(tmp_path, extra_wrong, expected_floor):
    dataset = tmp_path / "study"
    run = tmp_path / "run"
    dataset.mkdir()
    (run / "calibration").mkdir(parents=True)
    (dataset / "collection-plan.json").write_text("{}")
    (run / "edge-calibration-plan.json").write_text(json.dumps({
        "study": dataset.name, "collection_plan_sha256": sha(dataset / "collection-plan.json"),
        "original_floor": 20., "candidate_floor": 15.}))
    names = ["DAY_16", "DAY_18", "REJECT"]
    rows = [
        {"partition": "validation", "source_label": label, "egg_id": egg,
         "physical_egg_id": egg, "duplicate_group": "reject-group"}
        for label, egg in zip(names, ["D16-07", "D18-08", None], strict=True)
    ]
    scores = np.array([[3., 1., 0.], [0., 3., 1.], [0., 3., 1.]])
    original = [{"row_index": i, "truth": label, "sourcePrediction": None, "recaptureReasons": ["IMAGE_TOO_BLURRY"]}
                for i, label in enumerate(names)]
    new = [{**o, "sourcePrediction": pred, "recaptureReasons": [] if pred else ["IMAGE_TOO_BLURRY"]}
           for o, pred in zip(original, ["DAY_16", "DAY_18", "DAY_18" if extra_wrong else None], strict=True)]
    def evaluate(policy):
        assert policy["quality"]["minimum_edge_variance"] == 15.
        return new
    baseline = {"quality": {"minimum_edge_variance": 20.}}
    selected, outcomes = compare_rotation_floor(dataset, run, baseline, original, evaluate, rows, scores, names)
    assert selected["quality"]["minimum_edge_variance"] == expected_floor
    assert outcomes == (original if extra_wrong else new)
    assert baseline["quality"]["minimum_edge_variance"] == 20.
    evidence = json.loads((run / "calibration/edge-comparison.json").read_text())
    assert evidence["groups_with_increased_wrong_accepts"] == (["reject-group"] if extra_wrong else [])
    assert evidence["candidate"]["metrics"]["wrong_accepted"] == int(extra_wrong)
