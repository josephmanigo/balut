import numpy as np
import pytest

from balut_ml.train_epoch_head import metrics, target_rows


def test_reject_output_name_preserves_unfertilized_source_and_partition():
    row = {"source_label": "UNFERTILIZED", "partition": "train", "source_sha256": "bytes", "pixel_sha256": "pixels", "duplicate_group": "family"}
    result = target_rows([row])[0]
    assert result["source_label"] == "UNFERTILIZED"
    assert result["training_label"] == "REJECT"
    assert row == {key: result[key] for key in row}
    with pytest.raises(ValueError, match="crosses"):
        target_rows([row, {**row, "partition": "test", "source_sha256": "other", "pixel_sha256": "other"}])


def test_vendor_rejects_cannot_silently_reenter_new_dataset():
    with pytest.raises(ValueError, match="explicit"):
        target_rows([{"source_label": "REJECT"}])


def test_epoch_metrics_include_real_loss_and_all_class_errors():
    values = metrics(np.array([[4., 0., 0.], [0., 4., 0.], [0., 4., 0.]]), np.array([0, 1, 2]))
    assert values["accuracy"] == pytest.approx(2 / 3)
    assert values["confusion_matrix"] == [[1, 0, 0], [0, 1, 0], [0, 1, 0]]
    assert values["loss"] > 1 and values["recall"] == pytest.approx(2 / 3)
