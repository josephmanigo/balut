import numpy as np
import torch

from balut_ml.train_nested_feature_epochs import FeatureHead


def test_normalization_uses_fit_features_and_inference_preserves_them():
    fit = np.array([[0., 1.], [2., 1.]], dtype=np.float32)
    model = FeatureHead(fit, 4).eval()
    held = torch.tensor([[100., -100.]], dtype=torch.float32)
    with torch.inference_mode():
        scores = model(held)
    assert scores.shape == (1, 3) and torch.isfinite(scores).all()
    np.testing.assert_array_equal(model.mean.numpy(), [1., 1.])
    np.testing.assert_allclose(model.scale.numpy(), [1., .01])
