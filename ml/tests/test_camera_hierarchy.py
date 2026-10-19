import numpy as np
import pytest

from balut_ml.search_camera_hierarchy import hierarchical_scores


def test_hierarchy_preserves_reject_detector_and_binary_age_decision():
    general = np.array([[2, 1, 0], [2, 1, 0], [2, 1, 3], [2, 1, 3]], dtype=np.float32)
    scores = hierarchical_scores(np.array([-100, 100, -100, 100]), general)
    assert scores.argmax(1).tolist() == [0, 1, 2, 2]
    assert scores.dtype == np.float32


def test_hierarchy_rejects_nonfinite_inputs():
    with pytest.raises(ValueError, match="finite"):
        hierarchical_scores(np.array([np.nan]), np.zeros((1, 3)))
