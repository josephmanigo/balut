import copy

import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression
from sklearn.svm import SVC

from balut_ml.age_specialist import (
    combine_decision,
    feature_view,
    head_arrays,
    head_scores,
    learn_age_thresholds,
    metrics,
    predict,
    train,
)


def context(winner=0, reasons=()):
    labels = ["DAY_16", "DAY_18", "REJECT"]
    return {
        "base_winner": winner,
        "quality_reasons": list(reasons),
        "age_similarities": [0.9, 0.9],
        "novelty_limits": [0.6, 0.7],
        "baseline": {
            "sourcePrediction": None if reasons else labels[winner],
            "analysisOutcome": "RECAPTURE_REQUIRED" if reasons else "CLASSIFIED",
            "recaptureRequested": bool(reasons),
            "recaptureReasons": list(reasons),
            "reviewRequired": False,
            "qualityMeasurements": {"shortSide": 224},
            "decisionMargin": 3.0,
            "nearestTrainingCosine": 0.9,
            "scoresAreProbabilities": False,
        },
    }


@pytest.mark.parametrize("view", ["fused", "dino", "efficientnet"])
@pytest.mark.parametrize("kind", ["logistic", "rbf"])
def test_portable_head_matches_fitted_estimator_on_separate_inputs(view, kind):
    rng = np.random.default_rng(42)
    features = rng.normal(size=(40, 1664))
    truth = np.tile([0, 1], 20)
    estimator = LogisticRegression(C=10) if kind == "logistic" else SVC(C=10, gamma="scale")
    estimator.fit(feature_view(features, view), truth)
    queries = rng.normal(size=(12, 1664))
    expected = estimator.decision_function(feature_view(queries, view))
    actual = head_scores(queries, {"kind": kind, "view": view}, head_arrays(estimator, kind))
    np.testing.assert_allclose(actual, expected, atol=1e-10, rtol=1e-10)
    np.testing.assert_array_equal(actual > 0, expected > 0)


def test_calibration_excludes_blocked_images_and_reject_route():
    scores = np.array([-2.0] * 5 + [2.0] * 5 + [0.8, 0.7, 10.0, -20.0])
    truth = np.array([0] * 5 + [1] * 5 + [0, 1, 0, 2])
    contexts = [context() for _ in scores]
    contexts[-2] = context(reasons=["IMAGE_TOO_BLURRY"])
    contexts[-1] = context(winner=2)
    policy = learn_age_thresholds(scores, truth, contexts)
    assert policy["minimum_margin"]["DAY_16"] == 0.0
    assert policy["minimum_margin"]["DAY_18"] == pytest.approx(0.800001)
    assert policy["validation_support"]["DAY_18"] == {"accepted": 5, "correct": 5}
    assert combine_decision(context(), 0.8, policy)["sourcePrediction"] is None
    assert combine_decision(context(), 2.0, policy)["sourcePrediction"] == "DAY_18"


def test_calibration_disables_class_with_insufficient_support():
    policy = learn_age_thresholds(np.array([-2.0] * 4 + [2.0] * 5),
                                  np.array([0] * 4 + [1] * 5), [context()] * 9)
    assert policy["minimum_margin"]["DAY_16"] is None
    result = combine_decision(context(), -100.0, policy)
    assert result["sourcePrediction"] is None
    assert result["recaptureReasons"] == ["INSUFFICIENT_VALIDATION_SUPPORT"]


@pytest.mark.parametrize("reasons", [[], ["IMAGE_TOO_BLURRY"], ["UNFAMILIAR_APPEARANCE"]])
def test_reject_decision_and_recapture_are_preserved_exactly(reasons):
    original = context(winner=2, reasons=reasons)
    before = copy.deepcopy(original)
    result = combine_decision(original, -100.0, {"minimum_margin": {}})
    assert result == before["baseline"]
    result["recaptureReasons"].append("EDIT")
    assert original == before


def test_age_correction_keeps_quality_novelty_and_tie_abstention():
    policy = {"minimum_margin": {"DAY_16": 0.0, "DAY_18": 0.0}}
    assert combine_decision(context(winner=1), -2.0, policy)["sourcePrediction"] == "DAY_16"
    original = context(reasons=["IMAGE_TOO_BLURRY"])
    original["age_similarities"][1] = 0.65
    result = combine_decision(original, 100.0, policy)
    assert result["sourcePrediction"] is None
    assert result["recaptureReasons"] == ["IMAGE_TOO_BLURRY", "UNFAMILIAR_APPEARANCE"]
    assert result["reviewRequired"] is False
    assert combine_decision(context(), 0.0, policy)["recaptureReasons"] == ["AMBIGUOUS_APPEARANCE"]
    with pytest.raises(ValueError, match="Nonfinite age score"):
        combine_decision(context(), np.nan, policy)


def test_metrics_keep_accuracy_coverage_and_all_input_correctness_distinct():
    contexts = [context(winner=1), context(winner=1), context(winner=2, reasons=["IMAGE_TOO_BLURRY"])]
    truth = np.array([0, 1, 2])
    before, _ = metrics(contexts, truth)
    after, _ = metrics(contexts, truth, [-2.0, 2.0, -2.0],
                       {"minimum_margin": {"DAY_16": 0.0, "DAY_18": 0.0}})
    assert before["accepted_accuracy"] == 0.5
    assert after["raw_accuracy"] == after["accepted_accuracy"] == 1.0
    assert after["coverage"] == after["correct_of_all_inputs"] == 2 / 3
    assert after["age_wrong_classified"] == 0
    assert after["recaptures"] == 1


def test_existing_experiment_cannot_be_overwritten(tmp_path):
    with pytest.raises(FileExistsError, match="fresh experiment directory"):
        train(tmp_path)


def test_prediction_refuses_modified_locked_artifact(tmp_path):
    import json
    from balut_ml.public_data import sha256

    artifact = tmp_path / "age-head.npz"
    artifact.write_bytes(b"original")
    (tmp_path / "selection-lock.json").write_text(json.dumps({"artifacts": {artifact.name: sha256(artifact)}}))
    artifact.write_bytes(b"modified")
    with pytest.raises(ValueError, match="Locked candidate artifact changed"):
        predict(tmp_path, tmp_path / "unused.jpg")
