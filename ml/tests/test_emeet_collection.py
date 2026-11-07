import base64
import json

import pytest
from PIL import Image

from scripts.capture_emeet_egg import capture, finish, sha, verify_candidate, write


@pytest.fixture
def collection(tmp_path):
    dataset = tmp_path / "emeet-study"
    folder = dataset / "captures/D16-01/session-1"
    folder.mkdir(parents=True)
    plan = {"eggs": {"D16-01": {"label": "DAY_16", "partition": "train"},
                     "D18-10": {"label": "DAY_18", "partition": "test"}},
            "camera": "test camera", "capture_size": [1920, 1080], "sampled_frames": 10,
            "warmup_frames": 2, "label_authority": "synthetic test only"}
    write(dataset / "collection-plan.json", plan)
    write(folder / "record.json", {"egg_id": "D16-01", "source_label": "DAY_16",
          "partition": "train", "status": "capturing", "plan_sha256": sha(dataset / "collection-plan.json")})
    for number in range(1, 13):
        Image.new("RGB", (1920, 1080), (number * 10, 20, 30)).save(folder / f"frame-{number:03d}.jpg")
    return dataset, folder


def test_frames_keep_one_physical_identity_and_completed_evidence_is_immutable(collection):
    dataset, folder = collection
    record = finish(dataset, folder)
    assert record["physical_egg_id"] == "emeet-study:D16-01"
    assert record["source_label"] == "DAY_16" and record["partition"] == "train"
    assert len(record["views"]) == 10 and record["views"][0]["image"] == "frame-003.jpg"
    assert not record["model_used_for_label"]
    assert finish(dataset, folder) == record
    with pytest.raises(ValueError, match="already captured"):
        capture(dataset, "D16-01")
    (folder / "frame-003.jpg").write_bytes(b"changed")
    with pytest.raises(ValueError, match="evidence changed"):
        finish(dataset, folder)


def test_holdout_and_path_escape_never_open_camera(collection):
    dataset, folder = collection
    with pytest.raises(ValueError, match="test eggs unscanned"):
        capture(dataset, "D18-10")
    with pytest.raises(ValueError, match="Invalid physical egg ID"):
        capture(dataset, "../D16-01")
    with pytest.raises(ValueError, match="belong"):
        finish(dataset, dataset.parent)
    write(dataset / "candidate-lock.json", {})
    with pytest.raises(ValueError, match="Invalid candidate lock"):
        capture(dataset, "D18-10")
    model = dataset / "model.onnx"
    model.write_bytes(b"test artifact")
    write(dataset / "candidate-lock.json", {"schema_version": 1,
          "collection_plan_sha256": sha(dataset / "collection-plan.json"),
          "artifacts": [{"path": str(model), "sha256": sha(model)}]})
    assert verify_candidate(dataset)["schema_version"] == 1
    model.write_bytes(b"changed")
    with pytest.raises(ValueError, match="artifacts changed"):
        verify_candidate(dataset)


def test_label_drift_and_incomplete_or_frozen_video_are_rejected(collection):
    dataset, folder = collection
    record = json.loads((folder / "record.json").read_text())
    record["source_label"] = "DAY_18"
    write(folder / "record.json", record)
    with pytest.raises(ValueError, match="label or partition"):
        finish(dataset, folder)
    record["source_label"] = "DAY_16"
    write(folder / "record.json", record)
    saved = (folder / "frame-012.jpg").read_bytes()
    (folder / "frame-012.jpg").unlink()
    with pytest.raises(ValueError, match="Incomplete"):
        finish(dataset, folder)
    (folder / "frame-012.jpg").write_bytes(saved)
    for path in folder.glob("frame-*.jpg"):
        path.write_bytes(saved)
    with pytest.raises(ValueError, match="distinct frames"):
        finish(dataset, folder)


def test_local_scanner_preserves_labels_blocks_repeats_and_reserves_test_eggs(collection):
    from fastapi.testclient import TestClient
    from scripts.emeet_collection_server import create_app

    dataset, folder = collection
    payload = {"newEggConfirmed": True, "frames": [base64.b64encode(p.read_bytes()).decode()
               for p in sorted(folder.glob("frame-*.jpg"))]}
    with TestClient(create_app(dataset)) as client:
        assert client.get("/").status_code == 200
        status = client.get("/status").json()
        assert status["completed"] == 0 and status["total"] == 1 and status["reserved_test_eggs"] == 1
        assert client.post("/capture/D16-01", json=payload).status_code == 403
        headers = {"Origin": "http://testserver"}
        assert client.post("/capture/D18-10", json=payload, headers=headers).status_code == 400
        assert client.post("/capture/D16-01", json=[], headers=headers).status_code == 400
        assert client.post("/capture/D16-01", json={**payload, "frames": [payload["frames"][0]] * 12}, headers=headers).status_code == 400
        response = client.post("/capture/D16-01", json=payload, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json() == {"saved": True, "egg": "D16-01", "frames": 10}
        assert client.get("/status").json()["completed"] == 1
        assert client.post("/capture/D16-01", json=payload, headers=headers).status_code == 409


def test_development_rows_exclude_holdout_and_preserve_physical_groups(collection):
    from ml.balut_ml.emeet_development import development_rows, validate_rows

    dataset, folder = collection
    with pytest.raises(ValueError, match="Missing development eggs"):
        development_rows(dataset, require_complete=True)
    finish(dataset, folder)
    rows = development_rows(dataset, require_complete=True)
    assert len(rows) == 10 and {r["physical_egg_id"] for r in rows} == {"emeet-study:D16-01"}
    with pytest.raises(ValueError, match="crosses partitions"):
        validate_rows([rows[0], {**rows[1], "partition": "validation"}])
    with pytest.raises(ValueError, match="crosses partitions"):
        validate_rows([rows[0], {**rows[1], "partition": "test"}], allow_test=True)
    with pytest.raises(ValueError, match="crosses labels"):
        validate_rows([rows[0], {**rows[0], "source_label": "DAY_18"}])
    with pytest.raises(ValueError, match="Test images"):
        validate_rows([{**rows[0], "partition": "test"}])


def test_per_egg_target_and_report_do_not_invent_training_results(collection, tmp_path):
    from scripts.build_emeet_study_report import build

    dataset, folder = collection
    plan = json.loads((dataset / "collection-plan.json").read_text())
    plan["eggs"]["D16-01"]["sampled_frames"] = 4
    plan["requested_age_images"] = {"DAY_16": 1500, "DAY_18": 1500}
    write(dataset / "collection-plan.json", plan)
    record = json.loads((folder / "record.json").read_text())
    record["plan_sha256"] = sha(dataset / "collection-plan.json")
    write(folder / "record.json", record)
    for path in sorted(folder.glob("frame-*.jpg"))[6:]:
        path.unlink()
    assert len(finish(dataset, folder)["views"]) == 4
    output = tmp_path / "report"
    status = build(dataset, tmp_path / "no-training-run", output)
    assert status["age_images_saved"] == {"DAY_16": 4} and status["epochs_recorded"] == 0
    html = (output / "index.html").read_text(encoding="utf-8")
    assert html.count('<details open>') == 10 and "FIELD ACCURACY NOT YET ESTABLISHED" in html
    assert "No example curve or invented score" in html and not (output / "epoch-curves.png").exists()


def test_calibration_blocks_unsupported_class_and_counts_egg_uncertainty():
    import numpy as np
    from scripts.seal_emeet_candidate import calibrate
    from scripts.evaluate_emeet_candidate import wilson

    truth = np.repeat([0, 1, 2], 6)
    scores = np.eye(3)[truth] * 4
    scores[6] = [10, 0, 0]
    policy = calibrate(scores, truth, np.full((18, 3), .9), {})
    assert policy["minimum_margin"]["DAY_16"] is None
    assert policy["minimum_margin"]["DAY_18"] == 0
    assert policy["minimum_training_cosine"]["DAY_16"] == pytest.approx(.9)
    interval = wilson(6, 6)
    assert interval["lower"] == pytest.approx(.6096657121) and interval["upper"] == pytest.approx(1)


def test_report_keeps_raw_accuracy_separate_from_unclassified_decisions():
    from ml.balut_ml.scientific_metrics import classification_metrics
    from scripts.build_emeet_study_report import metric_table

    measured = classification_metrics([[2, 0, 0], [0, 2, 0], [0, 0, 2]],
                                      [[0, 0, 0, 2], [0, 0, 0, 2], [0, 0, 0, 2]])
    html = metric_table(measured, show_decisions=True)
    assert 'Accuracy: 1.0000' in html and '0 / 6 images classified' in html
    assert 'undefined (none classified)' in html and '6 unclassified' in html
    assert 'Correct classified / all images: 0.00%' in html


def test_fresh_repeat_summary_keeps_failures_and_exact_score_variation():
    from scripts.repeat_emeet_candidate import summarize

    classified = {"sourcePrediction": "DAY_16", "analysisOutcome": "CLASSIFIED", "recaptureRequested": False}
    attempts = [{"result": classified, "score_vector": [1.] * 9, "elapsed_seconds": 6.},
                {"result": classified, "score_vector": [1.0001] * 9, "elapsed_seconds": 7.},
                {"result": None, "score_vector": None, "elapsed_seconds": 30.}]
    measured = summarize(attempts, "DAY_16")
    assert measured["failures"] == 1 and measured["correct_over_attempts"] == pytest.approx(2 / 3)
    assert measured["class_agreement"] == 1 and measured["maximum_score_difference"] > 0
    assert measured["median_attempt_seconds"] == 7 and measured["strict_zero_gap_passed"] is False
    uncertain = {"sourcePrediction": None, "analysisOutcome": "RECAPTURE_REQUIRED", "recaptureRequested": True}
    unclassified = summarize([{"result": uncertain, "score_vector": [1.] * 9, "elapsed_seconds": 6.}] * 10, "DAY_16")
    assert unclassified["correct_over_attempts"] == 0 and unclassified["failures"] == 0
    assert unclassified["class_counts"] == {"UNCLASSIFIED": 10} and unclassified["class_agreement"] == 1


def test_refinement_selection_uses_validation_and_report_preserves_test_disclosure(collection, tmp_path):
    from scripts.build_emeet_refinement_report import build, choose
    from ml.balut_ml.scientific_metrics import classification_metrics

    dataset, _ = collection
    original, refinement, output = tmp_path / "original", tmp_path / "refinement", tmp_path / "report"
    candidates = {"full": original, "egg-roi": refinement / "egg-roi", "egg-roi-gamma": refinement / "egg-roi-gamma"}
    for name, run in candidates.items():
        run.mkdir(parents=True)
        matrix = [[4, 1, 0], [1, 4, 0], [0, 0, 5]] if name == "full" else [[5, 0, 0], [0, 5, 0], [0, 0, 5]]
        metrics = classification_metrics(matrix, [row + [0] for row in matrix])
        metrics["loss"] = .1 if name == "egg-roi" else .2
        write(run / "metrics.json", {"validation": metrics, "epochs_completed": 12, "selected_epoch": 4, "stop_reason": "validation_patience"})
        Image.new("RGB", (5, 5)).save(run / "epoch-curves.png")
        (run / "history.jsonl").write_text('{}\n')
        write(run / "training-lock.json", {"artifacts": {file: sha(run / file) for file in ("metrics.json", "epoch-curves.png", "history.jsonl")}})
    write(dataset / "candidate-lock.json", {"schema_version": 1, "run": str(original),
          "collection_plan_sha256": sha(dataset / "collection-plan.json"),
          "artifacts": [{"path": str(original / "training-lock.json"), "sha256": sha(original / "training-lock.json")}]})
    write(refinement / "protocol.json", {"candidates": ["egg-roi", "egg-roi-gamma"],
          "selection": "Validation macro F1, then loss", "original_candidate_lock_sha256": sha(dataset / "candidate-lock.json")})
    selection = build(dataset, original, refinement, output)
    assert selection["selected"] == "egg-roi" and selection["fresh_independent_test"] is False
    assert selection["test_used_for_candidate_selection"] is False
    assert build(dataset, original, refinement, output) == selection
    html = (output / "index.html").read_text(encoding="utf-8")
    assert "Evaluation pending. No retest score is claimed." in html
    assert "original test failures were already seen" in html and "FIELD ACCURACY NOT YET ESTABLISHED" in html
    assert choose({"a": {"validation": {"macro_f1": .9, "loss": .2}, "test_accuracy": 0},
                   "b": {"validation": {"macro_f1": .8, "loss": .1}, "test_accuracy": 1}}) == "a"
    (refinement / "egg-roi/metrics.json").write_text('{}')
    with pytest.raises(ValueError, match="changed training run"):
        build(dataset, original, refinement, output)
