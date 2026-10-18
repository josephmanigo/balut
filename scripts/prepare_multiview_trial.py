"""Seal a camera-only experimental head without replacing single-photo inference."""
import copy
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/edge_api"))
from balut_api.model_service import ModelService, decode_jpeg, preprocess, sha256_file
from balut_api.selective_gate import decide

BASE = ROOT / "deployment/releases/camera-trial-20261018"
SOURCE = ROOT / "ml/runs/retained-multiangle-calibrated-20261019"
RELEASE = ROOT / "deployment/releases/camera-multiangle-trial-20261019"


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write("\n")


def main():
    import numpy as np
    if RELEASE.exists():
        raise FileExistsError("Preserve the prepared or interrupted trial")
    lock, metrics, config = [read(SOURCE / name) for name in ("selection-lock.json", "metrics.json", "config.json")]
    for name, digest in lock["artifacts"].items():
        if sha256_file(SOURCE / name) != digest:
            raise ValueError("Frozen calibration changed")
    if metrics["admission_passed"] or metrics["admission_failures"] != ["Accepted historical validation regressed"]:
        raise ValueError("This camera-only trial requires the documented global-candidate failure")
    protected = {str(path.relative_to(BASE)): sha256_file(path) for path in BASE.rglob("*") if path.is_file()}
    if protected["registry.json"] != "909b08a19e0af651eb7076264b109e709c6919221bc9298a24f00a6379af090e":
        raise ValueError("Single-photo baseline changed")
    manifest = Path(config["dataset_manifest"])
    if sha256_file(manifest) != config["dataset_sha256"]:
        raise ValueError("Camera dataset changed")
    rows = [json.loads(line) for line in manifest.read_text().splitlines()]
    validation = [r for r in rows if (r.get("physical_egg_id") or "").startswith("physical-camera-20261018:")
                  and r["partition"] == "validation"]
    if len(validation) != 40 or any(r.get("test_status") for r in validation):
        raise ValueError("Expected only 10 development eggs with four views each")
    RELEASE.mkdir(parents=True)
    write(RELEASE / "trial-plan.json", {
        "scope": "EXPERIMENTAL_CAMERA_ONLY_TRIAL_AFTER_DEVELOPMENT_CALIBRATION",
        "single_photo_contract": "Keep baseline ONNX, quality gates, references and software fixtures byte-identical",
        "camera_contract": "Use the frozen calibrated head only for three-view analysis; preserve distinct-view consensus",
        "selection": "No new fit, threshold selection or test evaluation; verify the actual serving path against frozen development outputs",
        "prior_global_candidate_admission_passed": False,
        "source_lock_sha256": sha256_file(SOURCE / "selection-lock.json"),
        "dataset_sha256": config["dataset_sha256"], "protected_baseline": protected,
        "required": ["All baseline single-photo decisions unchanged", "All 10 new validation groups match frozen outputs",
                     "More correct accepted camera groups, no additional wrong accepted groups, no per-age regression"],
        "test_eggs_reopened": False, "supports_99_percent_claim": False})
    shutil.copytree(BASE / "egg-grade", RELEASE / "egg-grade")
    shutil.copytree(BASE / "licenses", RELEASE / "licenses")
    directory = RELEASE / "camera-head"
    directory.mkdir()
    for name in ("head.npz", "gate-policy.json", "training-references.npz", "metrics.json", "selection-lock.json", "experiment-plan.json"):
        shutil.copyfile(SOURCE / name, directory / name)
    registry = copy.deepcopy(read(BASE / "registry.json"))
    registry["release_id"] = RELEASE.name
    entry = registry["models"][0]
    entry["input_description"] = "Single photo: retained camera model. Three paused views: experimental multiangle head."
    artifact = lambda path: {"path": path.relative_to(RELEASE).as_posix(), "sha256": sha256_file(path)}
    service = ModelService()
    service.load(BASE / "registry.json", protected["registry.json"])
    model = service.models["egg-grade"]
    with np.load(directory / "head.npz", allow_pickle=False) as bank:
        coefficient, intercept = bank["coefficient"], bank["intercept"]
    with np.load(directory / "training-references.npz", allow_pickle=False) as bank:
        references, labels = bank["features"], bank["labels"]
    policy = read(directory / "gate-policy.json")
    expected = read(SOURCE / "camera-validation-outcomes.json")
    camera_expected = {r["image_path"]: r for r in expected["views_after"]}
    fixtures = []
    for label in ("DAY_16", "DAY_18"):
        row = next(r for r in validation if r["source_label"] == label
                   and r["source_dataset"] == "physical-multiangle-20261019"
                   and camera_expected[r["image_path"]]["sourcePrediction"] == label)
        source = Path(row["image_path"])
        assert sha256_file(source) == row["source_sha256"]
        target = directory / (label.lower() + ".jpg")
        shutil.copyfile(source, target)
        fixtures.append(target)
    fixtures += [RELEASE / "egg-grade/reject.jpg", RELEASE / "egg-grade/too-dark.jpg"]
    answers = []
    for path in fixtures:
        body = path.read_bytes()
        embedding = model["session"].run(None, {model["input_name"]: preprocess(body, model["config"])})[1]
        scores = embedding @ coefficient.T + intercept
        result = decide(scores[0], embedding[0], decode_jpeg(body), policy, references, labels)
        answers.append({"file": artifact(path), "expected_scores": scores[0].tolist(),
                        "expected_prediction": result["sourcePrediction"], "expected_recapture_reasons": result["recaptureReasons"]})
    assert {a["expected_prediction"] for a in answers} == {"DAY_16", "DAY_18", "REJECT", None}
    service.close()
    entry["camera_head"] = {"capture_contract": "three-paused-views-v1", "head": artifact(directory / "head.npz"),
                            "gate_policy": artifact(directory / "gate-policy.json"),
                            "training_references": artifact(directory / "training-references.npz"), "known_answers": answers}
    write(RELEASE / "registry.json", registry)
    (RELEASE / "registry.sha256").write_text(sha256_file(RELEASE / "registry.json") + "\n")
    service.load(RELEASE / "registry.json", sha256_file(RELEASE / "registry.json"))
    single_expected = {r["image_path"]: r for r in expected["views_before"]}
    grouped = {}
    for index, row in enumerate(validation):
        source = Path(row["image_path"])
        assert sha256_file(source) == row["source_sha256"]
        body = source.read_bytes()
        single = service.predict("egg-grade", body)
        before = single_expected[str(source)]
        assert single["sourcePrediction"] == before["sourcePrediction"] and single["recaptureReasons"] == before["recaptureReasons"]
        assert "cameraHeadSha256" not in single
        if row["source_dataset"] == "physical-multiangle-20261019":
            camera = service._predict("egg-grade", body, camera=True)
            after = camera_expected[str(source)]
            assert camera["sourcePrediction"] == after["sourcePrediction"] and camera["recaptureReasons"] == after["recaptureReasons"]
            grouped.setdefault(row["physical_egg_id"], []).append((body, row["source_label"]))
        if (index + 1) % 10 == 0:
            print(json.dumps({"stage": "serving parity", "validation_views": index + 1, "total": len(validation)}), flush=True)
    outcomes = []
    expected_groups = {r["egg_id"]: r for r in expected["after"]}
    for egg, views in grouped.items():
        assert len(views) == 3
        result = service.predict_views("egg-grade", [body for body, _ in views])
        wanted = expected_groups[egg]
        assert result["sourcePrediction"] == wanted["sourcePrediction"] and result["recaptureReasons"] == wanted["recaptureReasons"]
        outcomes.append(dict(egg_id=egg, truth=views[0][1], sourcePrediction=result["sourcePrediction"],
                             recaptureReasons=result["recaptureReasons"], cameraHeadSha256=result["cameraHeadSha256"]))
    assert len(outcomes) == 10 and all(r["truth"] == r["sourcePrediction"] for r in outcomes)
    assert metrics["camera_validation_after"]["correct_classified"] > metrics["camera_validation_before"]["correct_classified"]
    for name, digest in protected.items():
        assert sha256_file(BASE / name) == digest
        if name.startswith("egg-grade/"):
            assert sha256_file(RELEASE / name) == digest
    service.close()
    write(RELEASE / "verification.json", {
        "trial_checks_passed": True, "scope": "DEVELOPMENT_VALIDATION_SERVING_CHECK_ONLY",
        "single_photo_artifacts_byte_identical": True, "single_photo_validation_views_unchanged": 40,
        "historical_single_photo_before_and_after": metrics["historical_validation_before"],
        "camera_validation_before": metrics["camera_validation_before"], "camera_validation_after": metrics["camera_validation_after"],
        "camera_validation_serving_outcomes": outcomes, "prior_global_candidate_admission_passed": False,
        "prior_global_candidate_failures": metrics["admission_failures"], "test_images_opened": 0,
        "fresh_independent_test_eggs": 0, "claim_99_percent_supported": False,
        "registry_sha256": sha256_file(RELEASE / "registry.json"), "camera_head_sha256": sha256_file(directory / "head.npz")})
    print(json.dumps({"release": RELEASE.name, "trial_checks_passed": True, "camera_validation_correct": len(outcomes),
                      "single_photo_validation_views_unchanged": 40, "test_images_opened": 0}), flush=True)


if __name__ == "__main__":
    main()
