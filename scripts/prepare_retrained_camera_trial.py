"""Seal the operator-requested retrained camera trial, preserving failed admission."""
import copy
import json
from pathlib import Path
import shutil

import numpy as np

from prepare_multiview_trial import ROOT, read, write
from balut_api.model_service import ModelService, decode_jpeg, preprocess, sha256_file
from balut_api.selective_gate import decide

BASE = ROOT / "deployment/releases/camera-multiangle-trial-20261019"
SOURCE = ROOT / "ml/runs/retained-camera-50views-rejects-20261019"
RELEASE = ROOT / "deployment/releases/camera-retrained-trial-20261019"


def main():
    if RELEASE.exists():
        raise FileExistsError("Preserve the prepared or interrupted retrained trial")
    lock, metrics, adapted = [read(SOURCE / name) for name in ("selection-lock.json", "metrics.json", "config.json")]
    for name, digest in lock["artifacts"].items():
        if sha256_file(SOURCE / name) != digest:
            raise ValueError("Locked retraining artifacts changed")
    assert lock["admission_passed"] is False and metrics["selected_candidate"]["admission_passed"] is False
    protected = {str(p.relative_to(BASE)): sha256_file(p) for p in BASE.rglob("*") if p.is_file()}
    assert protected["registry.json"] == "e8efa5b6236d29022d520a58462316ffaeaed1fdd52584b9512e648efc4f5a5b"
    manifest = Path(adapted["dataset_manifest"])
    assert sha256_file(manifest) == adapted["dataset_sha256"]
    rows = [json.loads(line) for line in manifest.read_text().splitlines()]
    validation = [r for r in rows if r.get("physical_egg_id") and r["partition"] == "validation"
                  and r["source_dataset"] in {"physical-50views-20261019", "physical-reject-20261019"}]
    assert len(validation) == 550 and not any(r.get("test_status") for r in validation)
    registry = copy.deepcopy(read(BASE / "registry.json"))
    entry = registry["models"][0]
    assert entry["model"]["sha256"] == adapted["encoder_onnx_sha256"]
    RELEASE.mkdir()
    shutil.copytree(BASE / "egg-grade", RELEASE / "egg-grade")
    shutil.copytree(BASE / "licenses", RELEASE / "licenses")
    directory = RELEASE / "camera-head"
    directory.mkdir()
    for name in ("head.npz", "gate-policy.json", "training-references.npz"):
        shutil.copyfile(SOURCE / name, directory / name)
    for answer in entry["camera_head"]["known_answers"]:
        relative = answer["file"]["path"]
        if relative.startswith("camera-head/"):
            shutil.copyfile(BASE / relative, RELEASE / relative)
    config = read(RELEASE / entry["config"]["path"])
    config.update(experimental=True, display_name="Retrained camera model · experimental",
                  camera_dataset_sha256=adapted["dataset_sha256"],
                  camera_candidate_admission_passed=False, camera_selection_lock_sha256=sha256_file(SOURCE / "selection-lock.json"))
    config["limitations"] += ["The latest retrained camera candidate regressed in validation and failed admission. Operator-requested live trial only."]
    (RELEASE / entry["config"]["path"]).write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    artifact = lambda p: {"path": p.relative_to(RELEASE).as_posix(), "sha256": sha256_file(p)}
    entry["config"] = artifact(RELEASE / entry["config"]["path"])
    registry["release_id"] = RELEASE.name
    entry["input_description"] = "Single photo: retained model. Three paused camera views: latest retrained experimental head; validation regressed."
    with np.load(directory / "head.npz", allow_pickle=False) as bank:
        coefficient, intercept = bank["coefficient"], bank["intercept"]
    with np.load(directory / "training-references.npz", allow_pickle=False) as bank:
        references, labels = bank["features"], bank["labels"]
    policy = read(directory / "gate-policy.json")
    service = ModelService()
    try:
        service.load(BASE / "registry.json", protected["registry.json"])
        model = service.models["egg-grade"]
        answers = []
        for old in entry["camera_head"]["known_answers"]:
            path = RELEASE / old["file"]["path"]
            body = path.read_bytes()
            embedding = model["session"].run(None, {model["input_name"]: preprocess(body, config)})[1]
            scores = embedding @ coefficient.T + intercept
            result = decide(scores[0], embedding[0], decode_jpeg(body), policy, references, labels)
            answers.append({"file": artifact(path), "expected_scores": scores[0].tolist(),
                            "expected_prediction": result["sourcePrediction"], "expected_recapture_reasons": result["recaptureReasons"]})
        entry["camera_head"] = {"capture_contract": "three-paused-views-v1", "head": artifact(directory / "head.npz"),
                                "gate_policy": artifact(directory / "gate-policy.json"),
                                "training_references": artifact(directory / "training-references.npz"), "known_answers": answers}
        write(RELEASE / "registry.json", registry)
        registry_sha = sha256_file(RELEASE / "registry.json")
        (RELEASE / "registry.sha256").write_text(registry_sha + "\n", encoding="utf-8")
        service.close()
        service.load(RELEASE / "registry.json", registry_sha)
        expected = {s["physical_egg_id"]: s for s in read(SOURCE / "validation-outcomes.json")["after_scans"]["sweep"] if s["scan_index"] == 0}
        with np.load(SOURCE / "development.npz", allow_pickle=False) as bank:
            cached = dict(zip(bank["source_sha256"].tolist(), bank["features"], strict=True))
        checked = 0
        for egg, wanted in expected.items():
            selected = sorted((r for r in validation if r["physical_egg_id"] == egg and r["capture_record"]["angle_bin"] in (0, 17, 34)),
                              key=lambda r: r["capture_record"]["angle_bin"])
            assert len(selected) == 3
            bodies = []
            for row in selected:
                body = Path(row["image_path"]).read_bytes()
                assert sha256_file(Path(row["image_path"])) == row["source_sha256"]
                result = service._predict("egg-grade", body, camera=True)
                scores = list(result["sourceClassDecisionScores"].values())
                np.testing.assert_allclose(scores, cached[row["source_sha256"]] @ coefficient.T + intercept, atol=1e-4, rtol=1e-4)
                bodies.append(body)
            result = service.predict_views("egg-grade", bodies)
            assert result["cameraHeadSha256"] == lock["artifacts"]["head.npz"]
            assert result["sourcePrediction"] == wanted["sourcePrediction"] and result["recaptureReasons"] == wanted["recaptureReasons"]
            checked += 1
            print(json.dumps({"stage": "serving parity", "validation_eggs": checked, "total": len(expected)}), flush=True)
        assert checked == 11
        assert service.describe()["experimental"] is True
    finally:
        service.close()
    assert all(sha256_file(BASE / name) == digest for name, digest in protected.items())
    write(RELEASE / "trial-plan.json", {"scope": "OPERATOR_REQUESTED_EXPERIMENTAL_CAMERA_TRIAL_AFTER_FAILED_ADMISSION",
          "source_selection_lock_sha256": sha256_file(SOURCE / "selection-lock.json"), "dataset_sha256": adapted["dataset_sha256"],
          "candidate_admission_passed": False, "admission_failures": metrics["selected_candidate"]["admission_failures"],
          "validation_before": metrics["before"]["sweep"], "validation_after": metrics["selected_candidate"]["validation"]["sweep"],
          "rollback_release": BASE.name, "test_images_opened": 0, "supports_99_percent_claim": False,
          "activation_reason": "Operator requested the latest retrained model in the app for live testing after the failed comparison was reported."})
    write(RELEASE / "verification.json", {"serving_parity_passed": True, "candidate_admission_passed": False,
          "validation_eggs_checked": checked, "validation_groups_checked": checked, "test_images_opened": 0,
          "single_photo_weights_and_gates_unchanged": True, "registry_sha256": registry_sha,
          "camera_head_sha256": lock["artifacts"]["head.npz"], "active_release_changed": False})
    print(json.dumps({"release": RELEASE.name, "registry_sha256": registry_sha,
                      "camera_head_sha256": lock["artifacts"]["head.npz"], "serving_parity_passed": True, "candidate_admission_passed": False}))


if __name__ == "__main__":
    main()
