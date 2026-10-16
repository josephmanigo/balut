import copy

import numpy as np
import pytest

from balut_ml.age_specialist_cv import admission_checks, validate_folds


def test_source_family_cannot_cross_fold_boundary():
    truth = np.array([0, 1, 0, 1])
    folds = [(np.array([0, 1]), np.array([2, 3])), (np.array([2, 3]), np.array([0, 1]))]
    validate_folds(truth, np.array(["a", "b", "c", "d"]), folds)
    with pytest.raises(ValueError, match="family crosses"):
        validate_folds(truth, np.array(["a", "b", "a", "d"]), folds)


def test_each_training_image_is_held_out_exactly_once():
    truth, groups = np.array([0, 1, 0, 1]), np.array(["a", "b", "c", "d"])
    fold = (np.array([0, 1]), np.array([2, 3]))
    with pytest.raises(ValueError, match="one held-out fold"):
        validate_folds(truth, groups, [fold, fold])
    with pytest.raises(ValueError, match="Invalid fold indexes"):
        validate_folds(truth, groups, [(np.array([0, 1, 2]), np.array([2, 3]))])


def test_higher_headline_accuracy_cannot_hide_lost_age_coverage():
    baseline = {"age_raw_balanced_accuracy": 0.83, "age_wrong_classified": 1, "classified": 212,
                "by_true_class": {"DAY_16": {"correct_classified": 7}, "DAY_18": {"correct_classified": 7}}}
    candidate = copy.deepcopy(baseline)
    candidate.update(age_raw_balanced_accuracy=0.85, age_wrong_classified=0, classified=213)
    policy = {"minimum_margin": {"DAY_16": 1.0, "DAY_18": 1.0}}
    assert all(admission_checks(baseline, candidate, policy).values())
    candidate["by_true_class"]["DAY_16"]["correct_classified"] = 0
    policy["minimum_margin"]["DAY_16"] = None
    checks = admission_checks(baseline, candidate, policy)
    assert not checks["both_age_outputs_enabled"]
    assert not checks["day16_correct_issued_not_lower"]
    candidate["classified"] = 200
    assert not admission_checks(baseline, candidate, policy)["coverage_not_lower"]
