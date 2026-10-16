import numpy as np
import pytest
pytest.importorskip("torch")
from balut_ml.selective_search import learn_margin_thresholds


def test_development_mistake_sets_threshold_and_low_support_disables_class():
    scores = np.array([[4,0,0]]*5 + [[3,0,0]] + [[0,5,0]]*4 + [[0,0,8]]*5,dtype=np.float32)
    truth = np.array([0]*5 + [1] + [1]*4 + [2]*5)
    thresholds, counts = learn_margin_thresholds(scores,truth)
    assert 3 < thresholds["DAY_16"] < 4 and counts["DAY_16"] == {"accepted":5,"correct":5}
    assert thresholds["DAY_18"] is None and counts["DAY_18"]["accepted"] == 0
    assert thresholds["REJECT"] == 0 and counts["REJECT"]["accepted"] == 5
