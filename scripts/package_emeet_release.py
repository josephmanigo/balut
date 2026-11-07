"""Package the locked 20-egg MobileNetV2 for the existing three-view scanner."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps/edge_api")]
import numpy as np
import onnxruntime as ort

from balut_api.model_service import ModelService, preprocess, sha256_file

STUDY = "emeet-20-rotation-20261107"
RELEASE = "emeet-mobilenetv2-20261107"
LOCK_HASH = "3f9b1ee9a6223328055b38167fc2077fba227034762931975d3e96f3db08c35d"
CLASSES = ["DAY_16", "DAY_18", "REJECT"]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def locked_artifacts(run):
    path = ROOT / "data/local" / STUDY / "candidate-lock.json"
    if sha256_file(path) != LOCK_HASH:
        raise ValueError("Candidate differs from the one used in the four-egg physical study")
    lock = read(path)
    study_run = Path(lock["run"])
    artifacts = {}
    for item in lock["artifacts"]:
        rel = Path(item["path"]).relative_to(study_run)
        if ".." in rel.parts or sha256_file(run / rel) != item["sha256"]:
            raise ValueError(f"Locked artifact changed: {rel}")
        artifacts[rel.as_posix()] = run / rel
    return artifacts


def check_scanner(service, run, artifacts):
    # Only software parity inputs from development validation. No new raw egg photos in the release.
    rows = read(artifacts["development-manifest.json"])
    outcomes = read(artifacts["calibration/validation-outcomes.json"])
    inputs = read(run / "calibration/serving-inputs.json")
    result = {}
    with np.load(artifacts["calibration/development-cpu.npz"], allow_pickle=False) as bank:
        scores = bank["scores"]
    for label in CLASSES:
        matches = [r for r in outcomes if r["truth"] == r["sourcePrediction"] == label]
        selected = [matches[i] for i in (0, len(matches)//2, len(matches)-1)]
        bodies = []
        for row in selected:
            i = row["row_index"]
            source = run / "calibration/inputs" / (rows[i]["source_sha256"] + ".jpg")
            if rows[i]["partition"] != "validation" or sha256_file(source) != inputs[i]["serving_sha256"]:
                raise ValueError("Validation input changed")
            body = source.read_bytes()
            single = service.predict("egg-grade", body)
            np.testing.assert_allclose([single["sourceClassDecisionScores"][c] for c in CLASSES], scores[i],
                                       atol=1e-4, rtol=1e-4)
            if single["sourcePrediction"] != label:
                raise ValueError("Serving decision differs from locked validation decision")
            bodies.append(body)
        multi = service.predict_views("egg-grade", bodies)
        if multi["sourcePrediction"] != label or multi["multiView"]["acceptedDistinctViews"] != 3 or multi["operationalUseAuthorized"]:
            raise ValueError("Three-view scanner contract failed")
        result[label] = multi["multiView"]["acceptedDistinctViews"]
    dark = (ROOT / "data/recapture-test-samples/too-dark.jpg").read_bytes()
    result_dark = service.predict_views("egg-grade", [dark]*3)
    if not result_dark["recaptureRequested"] or result_dark["sourcePrediction"] is not None or "LOW_CONTRAST" not in result_dark["recaptureReasons"]:
        raise ValueError("Recapture check failed")
    return result


def main():
    run = ROOT / "ml/runs" / STUDY
    artifacts = locked_artifacts(run)
    out = ROOT / "deployment/releases" / RELEASE
    parts = ROOT / "deployment/model-parts" / RELEASE
    if out.exists() or parts.exists():
        raise FileExistsError("Preserve the existing immutable release")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "release"
        model_dir = root / "egg-grade"
        model_dir.mkdir(parents=True)
        for name in ("best.onnx", "calibration/gate-policy.json", "calibration/training-references.npz"):
            shutil.copyfile(artifacts[name], model_dir / Path(name).name)
        def artifact(name):
            p = model_dir / name
            return {"path": p.relative_to(root).as_posix(), "sha256": sha256_file(p)}
        policy, refs = artifact("gate-policy.json"), artifact("training-references.npz")
        config = {"status":"EXPLORATORY_EPOCH_FINETUNED_CLASSIFIER","task":"THREE_CLASS_EGG_APPEARANCE",
                  "architecture":"MobileNetV2","class_order":CLASSES,"selective_inference":True,
                  "operational_use_authorized":False,"experimental":True,"display_name":"EMEET MobileNetV2 · research classifier",
                  "input_size":224,"normalization_mean":[.485,.456,.406],"normalization_std":[.229,.224,.225],
                  "gate_policy_sha256":policy["sha256"],"references_sha256":refs["sha256"],"candidate_lock_sha256":LOCK_HASH}
        write(model_dir / "config.json", config)
        shutil.copyfile(ROOT / "data/recapture-test-samples/reject.jpg", model_dir / "startup-fixture.jpg")
        options = ort.SessionOptions()
        options.intra_op_num_threads, options.inter_op_num_threads = 4, 1
        engine = ort.InferenceSession(str(model_dir/"best.onnx"), options, providers=["CPUExecutionProvider"])
        expected = engine.run(None, {"images":preprocess((model_dir/"startup-fixture.jpg").read_bytes(), config)})[0][0]
        entry = {"id":"egg-grade","model":{**artifact("best.onnx"),"parts_revision":RELEASE},
                 "config":artifact("config.json"),"gate_policy":policy,"training_references":refs,
                 "known_answer":artifact("startup-fixture.jpg"),"expected_scores":expected.tolist(),"expected_prediction":"REJECT",
                 "input_description":"Three distinct candling views from the rotating EMEET holder for a Day 16, Day 18 or Reject appearance estimate."}
        write(root / "registry.json", {"schema_version":1,"scope":"SOURCE_LABEL_SHADOW_ONLY","release_id":RELEASE,
                                      "default_analysis_model":"egg-grade","models":[entry],"software_test_examples":[]})
        digest = sha256_file(root/"registry.json")
        (root/"registry.sha256").write_text(digest+"\n", encoding="ascii", newline="\n")
        service = ModelService()
        service.load(root/"registry.json", digest)
        checks = check_scanner(service, run, artifacts)
        service.close()
        (root/"licenses").mkdir()
        shutil.copyfile(ROOT/"deployment/releases/unfertilized-trial-20261019/licenses/torchvision-LICENSE",
                        root/"licenses/torchvision-LICENSE")
        write(root/"verification.json", {"release":RELEASE,"registry_sha256":digest,"candidate_lock_sha256":LOCK_HASH,
            "model_sha256":entry["model"]["sha256"],"three_view_software_checks":checks,"dark_input_requests_recapture":True,
            "physical_first_correct":3,"physical_first_attempts":4,"physical_repeat_correct":28,"physical_repeat_attempts":40,
            "physical_reject_eggs":0,"operational_use_authorized":False})
        chunk_dir = Path(tmp)/"parts"
        chunk_dir.mkdir()
        chunk = chunk_dir/"best.onnx.part00"
        shutil.copyfile(model_dir/"best.onnx", chunk)
        sha = sha256_file(chunk)
        if sha != entry["model"]["sha256"]:
            raise ValueError("Deployment chunk differs from locked ONNX")
        size = chunk.stat().st_size
        write(chunk_dir/"manifest.json", {"sha256":sha,"bytes":size,"parts":[{"name":chunk.name,"bytes":size,"sha256":sha}]})
        shutil.copytree(root, out)
        shutil.copytree(chunk_dir, parts)
    print(json.dumps(read(out/"verification.json")))


if __name__ == "__main__":
    main()
