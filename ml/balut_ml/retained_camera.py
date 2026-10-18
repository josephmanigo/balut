"""Add the numbered camera eggs to the retained dataset and fit its three-class head."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

from . import camera_pilot
from .public_data import sha256
from balut_api.model_service import ModelService, preprocess
from balut_api.selective_gate import CLASSES, image_quality, validate_policy

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "ml/runs/selective-v2"
HISTORY = ROOT / "ml/runs/three-class-v1/manifest.jsonl"
DATA = ROOT / "data/local/retained-camera-20261018"
RUN = ROOT / "ml/runs/retained-camera-20261018"
COLLECTION = "physical-camera-20261018"
WEIGHTS = (1.0, 5.0, 20.0)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)


def rows_from(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_dataset():
    if DATA.exists():
        raise FileExistsError("Dataset already exists; preserve the imported records")
    config, old_rows = read(BASE / "config.json"), rows_from(HISTORY)
    if sha256(HISTORY) != config["manifest_sha256"]:
        raise ValueError("Retained historical manifest changed")
    records = camera_pilot.records({"train", "validation", "test"})
    policy = read(BASE / "gate-policy.json")
    identities = {r[k] for r in old_rows for k in ("source_sha256", "pixel_sha256")}
    incoming = []
    for record in records:
        source = camera_pilot.DATA / record["image"]
        if record.get("model_used_for_label") is not False:
            raise ValueError("Camera labels must come from the user, not model predictions")
        with Image.open(source) as image:
            rgb = image.convert("RGB")
            if rgb.size != (600, 800):
                raise ValueError("Camera serving frame changed")
            pixels = hashlib.sha256(str(rgb.size).encode() + rgb.tobytes()).hexdigest()
            quality, flags = image_quality(rgb, policy)
        if record["sha256"] in identities or pixels in identities:
            raise ValueError("Camera image duplicates an existing dataset image")
        identities.update((record["sha256"], pixels))
        egg = record["egg_id"]
        incoming.append({"image_path": str((DATA / "images" / record["image"]).resolve()),
                         "source_sha256": record["sha256"], "pixel_sha256": pixels,
                         "source_label": f'DAY_{record["reported_age_days"]}', "source_dataset": COLLECTION,
                         "partition": record["partition"], "physical_egg_id": f"{COLLECTION}:{egg}",
                         "duplicate_group": f"{COLLECTION}:{egg}", "batch_id": None,
                         "capture_session_id": COLLECTION, "verified_incubation_hours": None,
                         "label_authority": record["label_authority"], "capture_record": record,
                         "dimensions": [600, 800], "quality_measurements": quality, "quality_flags": flags,
                         "training_eligible": record["partition"] == "train" and not flags,
                         "test_status": "closed_original_pilot_test" if record["partition"] == "test" else None})
    combined = old_rows + incoming
    groups = {}
    for row in combined:
        for key in ("source_sha256", "pixel_sha256", "duplicate_group"):
            identity = (key, row[key])
            if identity in groups and groups[identity] != row["partition"]:
                raise ValueError("Dataset identity crosses partitions")
            groups[identity] = row["partition"]
    (DATA / "images").mkdir(parents=True)
    for record, row in zip(records, incoming, strict=True):
        shutil.copyfile(camera_pilot.DATA / record["image"], row["image_path"])
        if sha256(Path(row["image_path"])) != row["source_sha256"]:
            raise ValueError("Camera copy failed integrity verification")
    manifest = DATA / "manifest.jsonl"
    with manifest.open("x", encoding="utf-8") as handle:
        for row in combined:
            handle.write(json.dumps(row, allow_nan=False) + "\n")
    audit = {"status": "EXPLORATORY_RETAINED_CAMERA_DATASET", "manifest_sha256": sha256(manifest),
             "historical_manifest_sha256": sha256(HISTORY), "historical_rows": len(old_rows),
             "camera_rows": len(incoming), "total_rows": len(combined),
             "camera_partitions": dict(Counter(r["partition"] for r in incoming)),
             "camera_training_eligible": sum(r["training_eligible"] for r in incoming),
             "class_counts": dict(Counter(r["source_label"] for r in combined)),
             "original_pilot_lock_sha256": sha256(camera_pilot.RUN / "selection-lock.json"),
             "original_pilot_test_report_sha256": sha256(camera_pilot.RUN / "test-report.json"),
             "independently_verified_age_labels": False, "operational_use_authorized": False,
             "preprocessing": "Original serving-frame bytes; no crop, relabel, augmentation, or exposure edits",
             "limitations": ["One user-reported farm collection and camera session; batch identity unknown",
                             "Incubation records and species not independently verified",
                             "No new Reject examples; retained public Reject examples remain",
                             "Original pilot test is closed; no new independent test for this adaptation"]}
    write(DATA / "audit.json", audit)
    return audit


def load_dataset():
    audit = read(DATA / "audit.json")
    if audit["status"] != "EXPLORATORY_RETAINED_CAMERA_DATASET" or sha256(DATA / "manifest.jsonl") != audit["manifest_sha256"]:
        raise ValueError("Dataset manifest changed")
    if sha256(HISTORY) != audit["historical_manifest_sha256"]:
        raise ValueError("Retained historical manifest changed")
    rows = rows_from(DATA / "manifest.jsonl")
    if rows[:audit["historical_rows"]] != rows_from(HISTORY):
        raise ValueError("Retained historical rows changed")
    local = rows[audit["historical_rows"]:]
    plan = read(camera_pilot.DATA / "capture-plan.json")["split"]
    if len(local) != 30 or {r["capture_record"]["egg_id"] for r in local} != set(plan):
        raise ValueError("Camera collection is incomplete")
    for row in local:
        egg = row["capture_record"]["egg_id"]
        if row["partition"] != plan[egg] or row["source_label"] != f'DAY_{egg.split("-")[0]}':
            raise ValueError("Camera labels or partitions changed")
        if row["training_eligible"] and (row["partition"] != "train" or row["quality_flags"]):
            raise ValueError("Only eligible training eggs can fit the model")
    return rows, local, audit


def training_arrays(old_x, old_y, rows, features):
    eligible = np.array([r["partition"] == "train" and r["training_eligible"] for r in rows])
    labels = np.array([CLASSES.index(r["source_label"]) for r in rows])
    if set(labels[eligible].tolist()) != {0, 1}:
        raise ValueError("Both camera ages need eligible training eggs")
    return np.concatenate((old_x, features[eligible])), np.concatenate((old_y, labels[eligible])), eligible


def train():
    if RUN.exists():
        raise FileExistsError("Adaptation already exists; preserve its results")
    from sklearn.linear_model import LogisticRegression
    from .adapt_local_photos import summarize
    from .benchmark_public import metrics_for
    from .selective_search import learn_margin_thresholds

    rows, local, audit = load_dataset()
    development = [r for r in local if r["partition"] in {"train", "validation"}]
    config, original_lock = read(BASE / "config.json"), read(BASE / "selection-lock.json")
    if (sha256(BASE / "selected-development.npz") != original_lock["development_data_sha256"]
            or sha256(BASE / "gate-policy.json") != original_lock["gate_policy_sha256"]):
        raise ValueError("Retained development cache or policy changed")
    protected = {str(p): sha256(p) for p in (BASE / "config.json", BASE / "best.onnx", BASE / "best.pt",
                 BASE / "gate-policy.json", BASE / "training-references.npz", HISTORY, camera_pilot.REGISTRY,
                 camera_pilot.RUN / "selection-lock.json", camera_pilot.RUN / "test-report.json")}
    RUN.mkdir(parents=True)
    write(RUN / "experiment-plan.json", {"dataset": str(DATA / "manifest.jsonl"), "dataset_sha256": audit["manifest_sha256"],
          "backbones": config["backbones"], "hyperparameters": config["hyperparameters"], "camera_weights": WEIGHTS,
          "selection": "Prefer no historical macro-F1 regression, then camera balanced accuracy, historical macro F1, first tie",
          "training": "Retained training examples plus eligible camera train eggs only",
          "test": "Both historical and original pilot tests remain closed; development evidence only",
          "protected_files": protected, "operational_use_authorized": False})
    service = ModelService()
    service.load(camera_pilot.REGISTRY, None)
    try:
        model = service.models["egg-grade"]
        if model["entry"]["model"]["sha256"] != sha256(BASE / "best.onnx"):
            raise ValueError("Serving encoder differs from retained training encoder")
        vectors, baseline_scores = [], []
        for row in development:
            body = Path(row["image_path"]).read_bytes()
            if hashlib.sha256(body).hexdigest() != row["source_sha256"]:
                raise ValueError("Camera training or validation image changed")
            scores, feature = model["session"].run(None, {model["input_name"]: preprocess(body, model["config"])})
            vectors.append(feature[0])
            baseline_scores.append(scores[0])
        vectors, baseline_scores = np.stack(vectors), np.stack(baseline_scores)
    finally:
        service.close()
    with np.load(BASE / "selected-development.npz", allow_pickle=False) as bank:
        old_x, old_y = bank["train_features"].copy(), bank["train_truth"].copy()
        val_x, val_y, old_scores = bank["validation_features"].copy(), bank["truth"].copy(), bank["scores"].copy()
        indexes, train_indexes = bank["indexes"].copy(), bank["train_indexes"].copy()
    assert all(rows[int(i)]["partition"] == "train" for i in train_indexes)
    assert all(rows[int(i)]["partition"] == "validation" for i in indexes)
    np.testing.assert_array_equal(old_y, [CLASSES.index(rows[int(i)]["source_label"]) for i in train_indexes])
    np.testing.assert_array_equal(val_y, [CLASSES.index(rows[int(i)]["source_label"]) for i in indexes])
    train_x, train_y, eligible = training_arrays(old_x, old_y, development, vectors)
    selected = np.array([r["partition"] == "validation" for r in development])
    camera_x = vectors[selected]
    camera_y = np.array([CLASSES.index(r["source_label"]) for r in development])[selected]
    camera_rows = [r for r in development if r["partition"] == "validation"]
    historical_baseline = metrics_for(val_y, old_scores.argmax(1), CLASSES)
    candidates, best_key, estimator = [], None, None
    for weight in WEIGHTS:
        candidate = LogisticRegression(C=config["hyperparameters"]["C"], class_weight="balanced", max_iter=3000, random_state=42)
        weights = np.concatenate((np.ones(len(old_y)), np.full(int(eligible.sum()), weight)))
        candidate.fit(train_x, train_y, sample_weight=weights)
        historical = metrics_for(val_y, candidate.predict(val_x), CLASSES)
        camera = metrics_for(camera_y, candidate.predict(camera_x), CLASSES)
        record = {"camera_weight": weight, "historical_validation": historical, "camera_validation": camera}
        candidates.append(record)
        key = (historical["macro_f1"] >= historical_baseline["macro_f1"], camera["balanced_accuracy"], historical["macro_f1"])
        if best_key is None or key > best_key:
            best_key, estimator, best = key, candidate, record
        print(json.dumps({"weight": weight, "camera_validation_correct": camera["correct"],
                          "historical_validation_correct": historical["correct"]}), flush=True)
    coefficient, intercept = estimator.coef_.astype(np.float32), estimator.intercept_.astype(np.float32)
    calibration_x, calibration_y = np.concatenate((val_x, camera_x)), np.concatenate((val_y, camera_y))
    scores = calibration_x @ coefficient.T + intercept
    np.testing.assert_allclose(scores, estimator.decision_function(calibration_x), atol=1e-5, rtol=1e-5)
    np.testing.assert_array_equal(scores.argmax(1), estimator.predict(calibration_x))
    policy = copy.deepcopy(read(BASE / "gate-policy.json"))
    policy["minimum_margin"], policy["validation_margin_gate_counts"] = learn_margin_thresholds(scores, calibration_y)
    policy["calibration_scope"] = "Historical and camera validation only; no fresh test or guaranteed accuracy"
    validate_policy(policy, train_x, train_y)
    np.savez_compressed(RUN / "head.npz", coefficient=coefficient, intercept=intercept)
    np.savez_compressed(RUN / "training-references.npz", features=train_x, labels=train_y)
    write(RUN / "gate-policy.json", policy)
    write(RUN / "candidates.json", candidates)
    write(RUN / "config.json", {"status": "EXPLORATORY_CAMERA_ADAPTED_HEAD", "class_order": CLASSES,
          "operational_use_authorized": False, "encoder_onnx": str((BASE / "best.onnx").resolve()),
          "encoder_onnx_sha256": sha256(BASE / "best.onnx"), "requires_existing_encoder_file": True,
          "input_contract": "Original 600x800 camera frame; retained resize224 and ImageNet normalization",
          "head": "head.npz", "training_references": "training-references.npz", "gate_policy": "gate-policy.json",
          "dataset_manifest": str(DATA / "manifest.jsonl"), "dataset_sha256": audit["manifest_sha256"],
          "limitations": audit["limitations"]})
    write(RUN / "selection-lock.json", {"selected": best, "evaluator_sha256": sha256(Path(__file__)),
          "dataset_sha256": audit["manifest_sha256"], "artifacts": {name: sha256(RUN / name) for name in
          ("head.npz", "training-references.npz", "gate-policy.json", "experiment-plan.json", "candidates.json", "config.json")}})
    before, _ = summarize(camera_rows, baseline_scores[selected], camera_x, camera_y,
                          read(BASE / "gate-policy.json"), old_x, old_y)
    after, outcomes = summarize(camera_rows, camera_x @ coefficient.T + intercept, camera_x, camera_y, policy, train_x, train_y)
    historical_after, _ = summarize([rows[int(i)] for i in indexes], val_x @ coefficient.T + intercept,
                                     val_x, val_y, policy, train_x, train_y)
    write(RUN / "camera-validation-outcomes.json", outcomes)
    for path, digest in protected.items():
        if sha256(Path(path)) != digest:
            raise ValueError("Protected retained release or original pilot evidence changed")
    report = {"dataset_rows": len(rows), "camera_rows_added": len(local), "camera_training_used": int(eligible.sum()),
              "training_counts": {label: int((train_y == i).sum()) for i, label in enumerate(CLASSES)},
              "selected_camera_weight": best["camera_weight"], "camera_validation_before": before,
              "camera_validation_after": after, "historical_validation_after": historical_after,
              "fresh_test_eggs": 0, "test_reopened": False, "active_release_changed": False,
              "portable_score_parity_passed": True, "protected_files_unchanged": True,
              "claim_99_percent_supported": False, "limitations": audit["limitations"]}
    write(RUN / "metrics.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("import", "train"))
    args = parser.parse_args()
    print(json.dumps(build_dataset() if args.stage == "import" else train()), flush=True)
