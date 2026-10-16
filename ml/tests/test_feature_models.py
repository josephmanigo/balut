"""Check portable inference against sklearn and prevent evaluation leakage."""
import pytest
np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")
pytest.importorskip("sklearn")
from sklearn.datasets import make_classification
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier
from sklearn.svm import SVC

from balut_ml.benchmark_public import PartitionImages, selection_key
from balut_ml.feature_models import build_head, portable_head


@pytest.mark.parametrize("classes", [2, 3])
@pytest.mark.parametrize("kind", ["logistic", "rbf_ovr"])
def test_portable_head_matches_estimator_and_reloads(tmp_path, classes, kind):
    x, y = make_classification(n_samples=180, n_features=12, n_informative=8, n_redundant=0,
                               n_classes=classes, random_state=73)
    x = (x / np.linalg.norm(x, axis=1, keepdims=True)).astype(np.float32)
    estimator = (LogisticRegression(C=2) if kind == "logistic"
                 else OneVsRestClassifier(SVC(kernel="rbf", C=2, gamma="scale")))
    estimator.fit(x[:130], y[:130])
    head, spec = portable_head(estimator, kind)
    target = tmp_path / "head.pt"
    torch.save({"state_dict": head.state_dict(), "spec": spec}, target)
    payload = torch.load(target, weights_only=True)
    reloaded = build_head(payload["spec"])
    reloaded.load_state_dict(payload["state_dict"])
    with torch.inference_mode():
        actual = reloaded(torch.from_numpy(x[130:])).numpy()
    expected = estimator.decision_function(x[130:])
    if classes == 2:
        expected = np.stack([np.zeros_like(expected), expected], axis=1)
    np.testing.assert_allclose(actual, expected, atol=1e-4, rtol=1e-4)
    np.testing.assert_array_equal(actual.argmax(1), estimator.predict(x[130:]))


def test_development_dataset_excludes_test_rows():
    rows = [{"partition": p, "source_label": "a", "image_path": "unused"}
            for p in ["test", "train", "validation", "test"]]
    dataset = PartitionImages(rows, {"train", "validation"}, ["a"])
    assert [i for i, _ in dataset.items] == [1, 2]


def test_selection_uses_macro_f1_before_overall_accuracy():
    balanced = {"macro_f1": 0.9, "balanced_accuracy": 0.9, "accuracy": 0.85}
    imbalanced = {"macro_f1": 0.8, "balanced_accuracy": 0.8, "accuracy": 0.95}
    assert selection_key(balanced) > selection_key(imbalanced)
