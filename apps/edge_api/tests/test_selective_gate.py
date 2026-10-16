import io
import json
from copy import deepcopy

import numpy as np
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from balut_api.selective_gate import CLASSES, decide, validate_policy
from balut_api.model_service import ModelService, sha256_file
from balut_api.main import create_app
from test_production import settings_for, operator_headers, registry


def policy():
    return {"schema_version":1,"minimum_margin":dict.fromkeys(CLASSES,0.5),
            "minimum_training_cosine":dict.fromkeys(CLASSES,0.7),"review_required":False,"on_uncertain":"RECAPTURE_REQUIRED",
            "quality":{"minimum_short_side":64,"minimum_grayscale_std":8,"minimum_edge_variance":20,"maximum_clipped_fraction":0.85}}


def sharp_image():
    return Image.fromarray(np.random.default_rng(42).integers(10,245,(224,224,3),dtype=np.uint8))


@pytest.mark.parametrize("scores,vector,reason", [([2,1.8,0],[1,0,0],"AMBIGUOUS_APPEARANCE"),([2,0,0],[0,1,0],"UNFAMILIAR_APPEARANCE")])
def test_uncertain_output_never_contains_a_class(scores,vector,reason):
    result = decide(scores,vector,sharp_image(),policy(),np.eye(3),np.arange(3))
    assert result["analysisOutcome"] == "RECAPTURE_REQUIRED"
    assert result["sourcePrediction"] is None and result["recaptureRequested"] is True
    assert result["reviewRequired"] is False and reason in result["recaptureReasons"]


@pytest.mark.parametrize("color", ["white","black","gray"])
def test_flat_images_remain_unclassified_even_with_a_large_score_gap(color):
    result = decide([100,0,0],[1,0,0],Image.new("RGB",(224,224),color),policy(),np.eye(3),np.arange(3))
    assert result["sourcePrediction"] is None and "LOW_CONTRAST" in result["recaptureReasons"]


def test_classification_requires_quality_margin_similarity_and_validation_support():
    data = policy()
    result = decide([2,0,0],[1,0,0],sharp_image(),data,np.eye(3),np.arange(3))
    assert result["sourcePrediction"] == "DAY_16" and not result["reviewRequired"]
    data["minimum_margin"]["DAY_16"] = None
    assert decide([200,0,0],[1,0,0],sharp_image(),data,np.eye(3),np.arange(3))["sourcePrediction"] is None


@pytest.mark.parametrize("mutation", ["nan","boolean","missing_class","nonunit","bad_shape","review"])
def test_invalid_release_policy_or_reference_data_is_rejected(mutation):
    data, bank, labels = policy(),np.eye(3),np.arange(3)
    if mutation == "nan": data["minimum_margin"]["DAY_16"] = float("nan")
    if mutation == "boolean": data["minimum_margin"]["DAY_16"] = True
    if mutation == "missing_class": labels = np.array([0,1,1])
    if mutation == "nonunit": bank *= 2
    if mutation == "bad_shape": labels = labels[:,None]
    if mutation == "review": data["review_required"] = True
    with pytest.raises(ValueError): validate_policy(data,bank,labels)


def test_tied_scores_request_recapture_even_when_margin_limit_is_zero():
    data = policy()
    data["minimum_margin"]["DAY_16"] = 0
    result = decide([2, 2, 0], [1, 0, 0], sharp_image(), data, np.eye(3), np.arange(3))
    assert result["sourcePrediction"] is None
    assert "AMBIGUOUS_APPEARANCE" in result["recaptureReasons"]


def selective_registry(tmp_path, registry):
    from onnx import TensorProto, helper, save
    outputs = [("decision_scores", [2,0,0]), ("embedding", [1,0,0])]
    graph = helper.make_graph([helper.make_node("Constant",[],[name],value=helper.make_tensor(name+"-constant",TensorProto.FLOAT,[1,3],values)) for name,values in outputs],"selective-software-test",
                              [helper.make_tensor_value_info("images",TensorProto.FLOAT,[1,3,224,224])],
                              [helper.make_tensor_value_info(name,TensorProto.FLOAT,[1,3]) for name,_ in outputs])
    save(helper.make_model(graph,opset_imports=[helper.make_opsetid("",18)],ir_version=10),tmp_path / "test.onnx")
    (tmp_path / "policy.json").write_text(json.dumps(policy()))
    np.savez(tmp_path / "references.npz",features=np.eye(3),labels=np.arange(3))
    sharp_image().save(tmp_path / "fixture.jpg","JPEG")
    config = json.loads((tmp_path / "config.json").read_text())
    config.update(task="THREE_CLASS_EGG_APPEARANCE",class_order=CLASSES,selective_inference=True,
                  gate_policy_sha256=sha256_file(tmp_path / "policy.json"),references_sha256=sha256_file(tmp_path / "references.npz"))
    (tmp_path / "config.json").write_text(json.dumps(config))
    data = json.loads(registry.read_text())
    data["default_analysis_model"] = "test-model"
    entry = data["models"][0]
    entry.update(expected_scores=[2,0,0],expected_prediction="DAY_16")
    for key,name in [("model","test.onnx"),("config","config.json"),("known_answer","fixture.jpg"),("gate_policy","policy.json"),("training_references","references.npz")]:
        entry[key] = {"path":name,"sha256":sha256_file(tmp_path / name)}
    registry.write_text(json.dumps(data))
    return registry


def test_automatic_recapture_is_durable_and_a_replacement_can_be_classified(tmp_path,registry):
    path = selective_registry(tmp_path,registry)
    settings = settings_for(tmp_path,model_registry_path=path,model_registry_sha256=sha256_file(path))
    buffer = io.BytesIO()
    Image.new("RGB",(224,224),"black").save(buffer,"JPEG")
    with TestClient(create_app(settings),base_url="http://127.0.0.1") as client:
        response = client.post("/api/v1/egg-analysis",headers=operator_headers(),content=buffer.getvalue())
        assert response.status_code == 200
        record = response.json()
        assert record["sourcePrediction"] is None and record["reviewRequired"] is False
        assert record["analysisOutcome"] == "RECAPTURE_REQUIRED" and record["recaptureRequested"] is True
        assert client.post("/api/v1/egg-analysis",headers=operator_headers(),content=buffer.getvalue()).json() == record
        replacement = client.post("/api/v1/egg-analysis",headers=operator_headers("replacement-001"),content=(tmp_path / "fixture.jpg").read_bytes()).json()
        assert replacement["sourcePrediction"] == "DAY_16" and replacement["analysisOutcome"] == "CLASSIFIED"
        assert replacement["reviewRequired"] is False and replacement["operationalUseAuthorized"] is False
    with TestClient(create_app(settings),base_url="http://127.0.0.1") as client:
        assert client.get("/api/v1/model-predictions/records/"+record["predictionId"],headers=operator_headers()).json() == record


def test_missing_or_replaced_gates_cannot_silently_disable_abstention(tmp_path,registry):
    path = selective_registry(tmp_path,registry)
    data = json.loads(path.read_text())
    missing = deepcopy(data)
    del missing["models"][0]["gate_policy"]
    path.write_text(json.dumps(missing))
    with pytest.raises(ValueError,match="Incomplete selective"): ModelService().load(path,sha256_file(path))
    path.write_text(json.dumps(data))
    (tmp_path / "policy.json").write_text("{}")
    with pytest.raises(ValueError,match="artifact checksum"): ModelService().load(path,sha256_file(path))


@pytest.mark.parametrize("mutation", ["bytes", "scores", "decision", "coverage"])
def test_additional_startup_examples_are_checked_before_loading(tmp_path, registry, mutation):
    path = selective_registry(tmp_path, registry)
    extra = tmp_path / "additional.jpg"
    extra.write_bytes((tmp_path / "fixture.jpg").read_bytes())
    example = {"file": {"path": extra.name, "sha256": sha256_file(extra)},
               "expected_scores": [2, 0, 0], "expected_prediction": "DAY_16",
               "expected_analysis_outcome": "CLASSIFIED", "expected_recapture_reasons": []}
    if mutation == "bytes": extra.write_bytes(b"changed additional fixture")
    if mutation == "scores": example["expected_scores"] = [0, 2, 0]
    if mutation == "decision": example["expected_prediction"] = "DAY_18"
    data = json.loads(path.read_text())
    data["software_test_examples"] = [example]
    path.write_text(json.dumps(data))
    service = ModelService()
    with pytest.raises(ValueError):
        service.load(path, sha256_file(path))
    assert not service.models
