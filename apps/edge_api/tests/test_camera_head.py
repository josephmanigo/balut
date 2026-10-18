import io
import json

import numpy as np
import pytest
from PIL import Image

from balut_api.model_service import ModelService, sha256_file
from test_production import registry
from test_selective_gate import selective_registry, sharp_image


def camera_registry(tmp_path, registry):
    path = selective_registry(tmp_path, registry)
    np.savez(tmp_path / "camera-head.npz", coefficient=np.zeros((3, 3), dtype=np.float32),
             intercept=np.array([0, 3, 0], dtype=np.float32))
    np.savez(tmp_path / "camera-references.npz", features=np.array([[1, 0, 0]] * 3), labels=np.arange(3))
    data = json.loads(path.read_text())
    artifact = lambda name: {"path": name, "sha256": sha256_file(tmp_path / name)}
    data["models"][0]["camera_head"] = {
        "capture_contract": "three-paused-views-v1", "head": artifact("camera-head.npz"),
        "gate_policy": artifact("policy.json"), "training_references": artifact("camera-references.npz"),
        "known_answers": [{"file": artifact("fixture.jpg"), "expected_scores": [0, 3, 0],
                           "expected_prediction": "DAY_18", "expected_recapture_reasons": []}]}
    path.write_text(json.dumps(data))
    return path


def test_camera_head_changes_only_three_view_analysis_and_keeps_quality_gates(tmp_path, registry):
    path = camera_registry(tmp_path, registry)
    service = ModelService()
    service.load(path, sha256_file(path))
    bodies = []
    for quality in (80, 90, 95):
        buffer = io.BytesIO()
        sharp_image().save(buffer, "JPEG", quality=quality)
        bodies.append(buffer.getvalue())
    assert service.predict("test-model", bodies[0])["sourcePrediction"] == "DAY_16"
    result = service.predict_views("test-model", bodies)
    assert result["sourcePrediction"] == "DAY_18"
    assert result["cameraHeadSha256"] == sha256_file(tmp_path / "camera-head.npz")
    assert all(view["sourceClassDecisionScores"] == dict(DAY_16=0, DAY_18=3, REJECT=0)
               for view in result["multiView"]["views"])
    assert service.predict_views("test-model", [bodies[0]] * 3)["recaptureRequested"]
    buffer = io.BytesIO()
    Image.new("RGB", (224, 224), "black").save(buffer, "JPEG")
    assert service.predict_views("test-model", [buffer.getvalue()] * 3)["sourcePrediction"] is None
    assert service.predict("test-model", bodies[0])["sourcePrediction"] == "DAY_16"


@pytest.mark.parametrize("mutation", ["checksum", "shape", "nan", "contract", "scores", "decision", "references", "missing_answers"])
def test_invalid_camera_artifacts_fail_before_serving(tmp_path, registry, mutation):
    path = camera_registry(tmp_path, registry)
    data = json.loads(path.read_text())
    camera = data["models"][0]["camera_head"]
    if mutation == "checksum": camera["head"]["sha256"] = "0" * 64
    if mutation in {"shape", "nan"}:
        coefficient = np.zeros((3, 2) if mutation == "shape" else (3, 3))
        if mutation == "nan": coefficient[0, 0] = np.nan
        np.savez(tmp_path / "camera-head.npz", coefficient=coefficient, intercept=np.zeros(3))
        camera["head"]["sha256"] = sha256_file(tmp_path / "camera-head.npz")
    if mutation == "contract": camera["capture_contract"] = "browser-claimed"
    if mutation == "scores": camera["known_answers"][0]["expected_scores"] = [3, 0, 0]
    if mutation == "decision": camera["known_answers"][0]["expected_prediction"] = "DAY_16"
    if mutation == "missing_answers": camera["known_answers"] = []
    if mutation == "references":
        np.savez(tmp_path / "camera-references.npz", features=np.eye(4)[:3], labels=np.arange(3))
        camera["training_references"]["sha256"] = sha256_file(tmp_path / "camera-references.npz")
    path.write_text(json.dumps(data))
    service = ModelService()
    with pytest.raises(ValueError):
        service.load(path, sha256_file(path))
    assert not service.models
