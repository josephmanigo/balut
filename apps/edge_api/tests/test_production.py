import base64
import hashlib
import hmac
import io
import json
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from balut_api.config import Settings
from balut_api.main import create_app
from balut_api.model_service import ModelService, sha256_file


def settings_for(tmp_path, **updates):
    return replace(Settings(environment="production", database_path=tmp_path / "test.db", evidence_path=tmp_path / "evidence",
                            local_admin_token="a"*48, device_shared_secret="b"*48, allow_simulator=False, cors_origins=()), **updates)


def operator_headers(key="prediction-test-001"):
    return {"Authorization": "Bearer " + "a"*48, "X-Balut-Origin": "local", "Idempotency-Key": key, "Content-Type": "image/jpeg"}


def jpeg():
    buffer = io.BytesIO()
    Image.new("RGB", (48, 48), "gray").save(buffer, "JPEG")
    return buffer.getvalue()


@pytest.mark.parametrize("updates", [{"allow_simulator": True}, {"local_admin_token": "dev-local-token"},
                                     {"device_shared_secret": "a"*48}, {"environment": "typo"}, {"cors_origins": ("*",)}])
def test_production_rejects_unsafe_settings(tmp_path, updates):
    with pytest.raises(RuntimeError):
        settings_for(tmp_path, **updates).validate()


def test_production_auth_and_host_guard(tmp_path):
    with TestClient(create_app(settings_for(tmp_path)), base_url="http://127.0.0.1") as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/dashboard").status_code == 401
        assert client.get("/api/v1/dashboard", headers=operator_headers()).status_code == 200
        basic = base64.b64encode(("operator:" + "a"*48).encode()).decode()
        assert client.get("/api/v1/dashboard", headers={"Authorization": "Basic " + basic}).status_code == 200
        assert client.get("/health", headers={"Host": "evil.example"}).status_code == 400
        assert client.post("/api/v1/simulator/run", headers={**operator_headers(), "Content-Type": "application/json"}, json={}).status_code == 404
        assert client.get("/docs", headers=operator_headers()).status_code == 404
        assert client.get("/ready").json()["automaticGradingReady"] is False
        response = client.get("/health")
        assert response.headers["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        assert "img-src 'self' data: blob:;" in response.headers["content-security-policy"]
        assert "'unsafe-eval'" not in response.headers["content-security-policy"]


def test_body_limit_rejects_declared_and_streamed_oversize(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, max_request_bytes=100)), base_url="http://127.0.0.1") as client:
        response = client.post("/api/v1/model-predictions/unknown", headers=operator_headers(), content=b"x"*101)
        assert response.status_code == 413
        streamed = client.post("/api/v1/model-predictions/unknown", headers=operator_headers(), content=iter([b"x"*60, b"y"*60]))
        assert streamed.status_code == 413


def sign_v2(path, body, key="device-upload-001"):
    timestamp, device = str(int(time.time())), "DEVICE-001"
    image_hash = hashlib.sha256(body).hexdigest()
    prefix = "\n".join(["BALUT-HMAC-V2", "POST", path, "", key, "image/jpeg", image_hash])
    message = prefix.encode()+b"\n"+timestamp.encode()+b"."+device.encode()+b"."+body
    signature = hmac.new(b"b"*48, message, hashlib.sha256).hexdigest()
    return {"X-Device-Signature-Version": "2", "X-Device-Timestamp": timestamp, "X-Device-Id": device,
            "X-Device-Signature": signature, "X-Image-SHA256": image_hash, "Idempotency-Key": key, "Content-Type": "image/jpeg"}


def test_device_signature_cannot_move_between_views_or_keys(tmp_path):
    path, body = "/api/v1/device/evidence/INSPECTION-001/0", jpeg()
    headers = sign_v2(path, body)
    with TestClient(create_app(settings_for(tmp_path)), base_url="http://127.0.0.1") as client:
        assert client.post(path, headers=headers, content=body).status_code == 200
        assert client.post(path[:-1]+"1", headers=headers, content=body).status_code == 401
        assert client.post(path, headers={**headers, "Idempotency-Key": "changed-key-001"}, content=body).status_code == 401
        assert client.post(path, headers={**headers, "X-Device-Signature-Version": "1"}, content=body).status_code == 401


def test_boundary_markers_do_not_make_a_valid_jpeg(tmp_path):
    path, body = "/api/v1/device/evidence/INSPECTION-001/0", b"\xff\xd8garbage\xff\xd9"
    with TestClient(create_app(settings_for(tmp_path)), base_url="http://127.0.0.1") as client:
        assert client.post(path, headers=sign_v2(path, body), content=body).status_code == 409
        assert not list((tmp_path / "evidence").rglob("*.jpg"))


@pytest.fixture()
def registry(tmp_path):
    onnx = pytest.importorskip("onnx")
    pytest.importorskip("onnxruntime")
    from onnx import TensorProto, helper
    tensor = helper.make_tensor("constant", TensorProto.FLOAT, [1, 2], [0.2, 0.8])
    graph = helper.make_graph([helper.make_node("Constant", [], ["scores"], value=tensor)], "serving-test-only",
                              [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 224, 224])],
                              [helper.make_tensor_value_info("scores", TensorProto.FLOAT, [1, 2])])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)], ir_version=10)
    onnx.save(model, tmp_path / "test.onnx")
    config = {"status": "EXPLORATORY_FROZEN_FEATURE_CLASSIFIER", "operational_use_authorized": False,
              "class_order": ["source-a", "source-b"], "input_size": 224,
              "normalization_mean": [0.485, 0.456, 0.406], "normalization_std": [0.229, 0.224, 0.225]}
    (tmp_path / "config.json").write_text(json.dumps(config))
    (tmp_path / "fixture.jpg").write_bytes(jpeg())
    artifact = lambda name: {"path": name, "sha256": sha256_file(tmp_path / name)}
    value = {"schema_version": 1, "scope": "SOURCE_LABEL_SHADOW_ONLY", "release_id": "TEST-ONLY",
             "models": [{"id": "test-model", "model": artifact("test.onnx"), "config": artifact("config.json"),
                         "known_answer": artifact("fixture.jpg"), "expected_scores": [0.2, 0.8], "input_description": "Synthetic software test"}]}
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(value))
    return path


def test_corrupt_model_or_registry_prevents_startup(tmp_path, registry):
    service = ModelService()
    with pytest.raises(ValueError, match="registry checksum"):
        service.load(registry, "f"*64)
    (tmp_path / "test.onnx").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="artifact checksum"):
        service.load(registry, sha256_file(registry))
    assert not service.models


@pytest.mark.parametrize("operational", [False, True])
def test_epoch_finetuned_contract_stays_source_label_only(tmp_path, registry, operational):
    config_path = tmp_path / "config.json"
    config = json.loads(config_path.read_text())
    config.update(status="EXPLORATORY_EPOCH_FINETUNED_CLASSIFIER", operational_use_authorized=operational)
    config_path.write_text(json.dumps(config))
    value = json.loads(registry.read_text())
    value["models"][0]["config"]["sha256"] = sha256_file(config_path)
    registry.write_text(json.dumps(value))
    service = ModelService()
    if operational:
        with pytest.raises(ValueError, match="source-label-only"):
            service.load(registry, sha256_file(registry))
    else:
        service.load(registry, sha256_file(registry))
        assert service.describe()["operationalUseAuthorized"] is False


def test_wrong_known_answer_prevents_startup(registry):
    data = json.loads(registry.read_text())
    data["models"][0]["expected_scores"] = [1.0, 0.0]
    registry.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="known-answer"):
        ModelService().load(registry, sha256_file(registry))


def test_prediction_is_durable_idempotent_and_survives_restart(tmp_path, registry):
    settings = settings_for(tmp_path, model_registry_path=registry, model_registry_sha256=sha256_file(registry))
    app = create_app(settings)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/health").json()["trainedModelLoaded"] is True
        first = client.post("/api/v1/model-predictions/test-model", headers=operator_headers(), content=jpeg())
        assert first.status_code == 200
        result = first.json()
        assert result["sourcePrediction"] == "source-b"
        assert result["operationalOutcome"] == "REVIEW_RECAPTURE"
        assert result["operationalUseAuthorized"] is False
        repeated = client.post("/api/v1/model-predictions/test-model", headers=operator_headers(), content=jpeg())
        assert repeated.json() == result
        assert client.post("/api/v1/model-predictions/test-model", headers=operator_headers(), content=jpeg()+b"changed").status_code == 409
        with app.state.database.connect() as connection:
            for table in ["model_predictions", "audit_events", "sync_outbox", "idempotency_records"]:
                assert connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 1
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        record = client.get("/api/v1/model-predictions/records/"+result["predictionId"], headers=operator_headers())
        assert record.json() == result


def test_busy_inference_does_not_persist_a_guess(tmp_path, registry):
    app = create_app(settings_for(tmp_path, model_registry_path=registry, model_registry_sha256=sha256_file(registry)))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        app.state.model_service.gate.acquire()
        try:
            response = client.post("/api/v1/model-predictions/test-model", headers=operator_headers(), content=jpeg())
            assert response.status_code == 429
            assert not list((tmp_path / "evidence").rglob("*.jpg"))
        finally:
            app.state.model_service.gate.release()


def test_storage_failure_never_returns_a_prediction(tmp_path, registry, monkeypatch):
    app = create_app(settings_for(tmp_path, model_registry_path=registry, model_registry_sha256=sha256_file(registry)))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        def fail(*args, **kwargs):
            raise OSError("disk full")
        monkeypatch.setattr("balut_api.evidence.EvidenceStore.store_jpeg", fail)
        assert client.post("/api/v1/model-predictions/test-model", headers=operator_headers(), content=jpeg()).status_code == 503
        with app.state.database.connect() as connection:
            assert connection.execute("SELECT count(*) FROM model_predictions").fetchone()[0] == 0


def test_analysis_rejects_a_release_without_the_three_class_contract(tmp_path, registry):
    settings = settings_for(tmp_path, model_registry_path=registry, model_registry_sha256=sha256_file(registry))
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        assert client.post("/api/v1/egg-analysis", headers=operator_headers(), content=jpeg()).status_code == 503
    data = json.loads(registry.read_text())
    data["default_analysis_model"] = "test-model"
    registry.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="must support Day 16"):
        ModelService().load(registry, sha256_file(registry))


def test_analysis_selects_pinned_three_class_model_and_preserves_retries(tmp_path, registry):
    from onnx import TensorProto, helper, save
    tensor = helper.make_tensor("constant", TensorProto.FLOAT, [1, 3], [0.2, 0.8, 0.1])
    graph = helper.make_graph([helper.make_node("Constant", [], ["scores"], value=tensor)], "three-class-test-only",
                              [helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 224, 224])],
                              [helper.make_tensor_value_info("scores", TensorProto.FLOAT, [1, 3])])
    save(helper.make_model(graph, opset_imports=[helper.make_opsetid("", 18)], ir_version=10), tmp_path / "test.onnx")
    config = json.loads((tmp_path / "config.json").read_text())
    config.update(task="THREE_CLASS_EGG_APPEARANCE", class_order=["DAY_16", "DAY_18", "REJECT"])
    (tmp_path / "config.json").write_text(json.dumps(config))
    data = json.loads(registry.read_text())
    data["default_analysis_model"] = "test-model"
    entry = data["models"][0]
    entry["model"]["sha256"] = sha256_file(tmp_path / "test.onnx")
    entry["config"]["sha256"] = sha256_file(tmp_path / "config.json")
    entry["expected_scores"] = [0.2, 0.8, 0.1]
    registry.write_text(json.dumps(data))
    settings = settings_for(tmp_path, model_registry_path=registry, model_registry_sha256=sha256_file(registry))
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        assert client.get("/api/v1/models", headers=operator_headers()).json()["analysisModelId"] == "test-model"
        assert client.post("/api/v1/egg-analysis", content=jpeg()).status_code == 401
        first = client.post("/api/v1/egg-analysis", headers=operator_headers(), content=jpeg())
        assert first.status_code == 200
        result = first.json()
        assert result["sourcePrediction"] == "DAY_18" and result["reviewRequired"] is True
        assert result["operationalUseAuthorized"] is False
        assert client.post("/api/v1/egg-analysis", headers=operator_headers(), content=jpeg()).json() == result
        assert client.post("/api/v1/egg-analysis", headers=operator_headers(), content=jpeg()+b"changed").status_code == 409
