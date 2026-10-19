import io
import numpy as np
from PIL import Image
from balut_ml.search_camera_photometry import photometry


def test_fixed_crop_has_expected_black_and_white_measurements():
    for value in (0, 255):
        stream = io.BytesIO(); Image.new("RGB", (224, 224), (value,) * 3).save(stream, format="PNG")
        values = photometry(stream.getvalue()).reshape(12, 12)
        np.testing.assert_allclose(values[:, :3], value / 255)
        np.testing.assert_allclose(values[:, 3:6], 0)
        np.testing.assert_allclose(values[:, 6:9], int(value == 0))
        np.testing.assert_array_equal(values[:, 9:11], 0)
        np.testing.assert_array_equal(values[:, 11], int(value == 255))
