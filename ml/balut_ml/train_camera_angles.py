"""Fit one predeclared grouped camera candidate; never open the completed test eggs."""
import copy
from collections import Counter
import json
from pathlib import Path

import numpy as np

from balut_api.model_service import ModelService, active_registry, preprocess, view_consensus
from balut_api.selective_gate import CLASSES, validate_policy
from .adapt_local_photos import summarize
from .camera_angles import ROOT, DATA, CAPTURE, sha
from .retained_camera import training_arrays

BASE = ROOT / "ml/runs/selective-v2"
CURRENT = ROOT / "ml/runs/retained-camera-20261018"
RUN = ROOT / "ml/runs/retained-multiangle-20261019"


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)


def grouped_weights(old_truth, training_rows):
    if any(row["partition"] != "train" or not row["training_eligible"] for row in training_rows):
        raise ValueError("Only eligible training views may fit the head")
    counts = Counter(row["physical_egg_id"] for row in training_rows)
    labels = {row["physical_egg_id"]: CLASSES.index(row["source_label"]) for row in training_rows}
    totals = np.bincount(np.concatenate((old_truth, np.array(list(labels.values())))), minlength=3)
    if (totals == 0).any():
        raise ValueError("Training requires all three retained classes")
    class_weights = {i: float(totals.sum() / (3 * count)) for i, count in enumerate(totals)}
    sample_weights = np.concatenate((np.ones(len(old_truth)), np.array([20 / counts[row["physical_egg_id"]] for row in training_rows])))
    return sample_weights, class_weights


def group_report(rows, scores, outcomes):
    grouped = {}
    for index, row in enumerate(rows):
        grouped.setdefault(row["physical_egg_id"], []).append(index)
    eggs = []
    for egg, indexes in grouped.items():
        if len(indexes) != 3 or len({rows[i]["source_label"] for i in indexes}) != 1:
            raise ValueError("Validation requires three views with one label per physical egg")
        views = [outcomes[i] for i in indexes]
        prediction, reasons, accepted = view_consensus(views, [rows[i]["source_sha256"] for i in indexes])
        eggs.append({"egg_id": egg, "truth": rows[indexes[0]]["source_label"],
                     "raw_prediction": CLASSES[int(scores[indexes].mean(0).argmax())],
                     "sourcePrediction": prediction, "recaptureReasons": reasons, "accepted_distinct_views": accepted})
    accepted = [egg for egg in eggs if egg["sourcePrediction"]]
    correct = sum(egg["sourcePrediction"] == egg["truth"] for egg in accepted)
    summary = {"physical_eggs": len(eggs), "raw_correct": sum(e["raw_prediction"] == e["truth"] for e in eggs),
               "classified": len(accepted), "correct_classified": correct, "wrong_classified": len(accepted) - correct,
               "coverage": len(accepted) / len(eggs), "accepted_accuracy": correct / len(accepted) if accepted else None,
               "correct_of_all_inputs": correct / len(eggs),
               "by_true_class": {label: {"eggs": sum(e["truth"] == label for e in eggs),
                   "raw_correct": sum(e["truth"] == e["raw_prediction"] == label for e in eggs),
                   "correct_classified": sum(e["truth"] == e["sourcePrediction"] == label for e in eggs)} for label in CLASSES[:2]}}
    return summary, eggs


def admission(before, after, historical_before, historical_after, original_before, original_after):
    failures = []
    if after["correct_classified"] <= before["correct_classified"] or after["wrong_classified"] > before["wrong_classified"]:
        failures.append("No increase in correct accepted validation eggs without more wrong accepted eggs")
    for label in CLASSES[:2]:
        a, b = after["by_true_class"][label], before["by_true_class"][label]
        if a["correct_classified"] < max(3, b["correct_classified"]) or a["raw_correct"] < b["raw_correct"]:
            failures.append(f"Insufficient or regressed {label} validation support")
    for name, old, new in (("historical", historical_before, historical_after), ("original camera", original_before, original_after)):
        if (new["selective"]["correct_classified"] < old["selective"]["correct_classified"]
                or new["selective"]["wrong_classified"] > old["selective"]["wrong_classified"]):
            failures.append(f"Accepted {name} validation regressed")
    if (historical_after["raw"]["correct"] < historical_before["raw"]["correct"]
            or historical_after["raw"]["macro_f1"] < historical_before["raw"]["macro_f1"]):
        failures.append("Raw historical validation regressed")
    return failures


def run():
    if RUN.exists():
        raise FileExistsError("Preserve the completed or interrupted candidate run")
    audit = read(DATA / "audit.json")
    manifest = DATA / "manifest.jsonl"
    if (audit["status"] != "EXPLORATORY_RETAINED_MULTIANGLE_DATASET" or audit["captured_eggs"] != 30
            or audit["new_views"] != 90 or sha(manifest) != audit["manifest_sha256"]):
        raise ValueError("Complete and verify all 30 numbered eggs before training")
    plan_path = CAPTURE / "experiment-plan.json"
    plan = read(plan_path)
    if (sha(plan_path) != "f42e42f8fb3757593bc5247196a2b94e22e9d51a3e5ea97acd3d3c2345b51bad"
            or plan["candidate_count"] != 1 or plan["candidate"]["C"] != 100
            or plan["candidate"]["camera_weight_per_physical_egg"] != 20):
        raise ValueError("The predeclared experiment plan changed")
    registry = active_registry(ROOT)
    if sha(registry) != plan["baseline_registry_sha256"]:
        raise ValueError("Active baseline changed after the experiment was fixed")
    for egg, digest in plan["training_capture_records"].items():
        if sha(CAPTURE / egg / "record.json") != digest:
            raise ValueError("Training capture changed after the experiment was fixed")
    base_manifest = ROOT / "data/local/retained-camera-20261018/manifest.jsonl"
    if sha(base_manifest) != plan["base_dataset_sha256"]:
        raise ValueError("Original retained camera data changed")
    rows = [json.loads(line) for line in manifest.read_text().splitlines() if line.strip()]
    if rows[:audit["base_rows_preserved"]] != [json.loads(line) for line in base_manifest.read_text().splitlines() if line.strip()]:
        raise ValueError("Original dataset rows changed")
    development = [row for row in rows if (row.get("physical_egg_id") or "").startswith("physical-camera-20261018:")
                   and row["partition"] in {"train", "validation"}]
    if len(development) != 80 or any(row.get("test_status") for row in development):
        raise ValueError("Development must contain 20 original eggs with four views each, excluding test eggs")
    lock = read(BASE / "selection-lock.json")
    if sha(BASE / "selected-development.npz") != lock["development_data_sha256"]:
        raise ValueError("Retained feature cache changed")
    protected = {str(path): sha(path) for path in (registry, registry.parent / "egg-grade/best.onnx",
                 registry.parent / "egg-grade/gate-policy.json", registry.parent / "egg-grade/training-references.npz",
                 BASE / "best.onnx", BASE / "selected-development.npz", CURRENT / "head.npz", base_manifest, manifest, plan_path)}
    RUN.mkdir()
    write(RUN / "experiment-plan.json", {**plan, "dataset_sha256": audit["manifest_sha256"], "protected_files": protected})
    service = ModelService()
    features, baseline_scores = [], []
    try:
        service.load(registry, None)
        model = service.models["egg-grade"]
        policy = copy.deepcopy(model["policy"])
        baseline_references, baseline_labels = model["references"].copy(), model["reference_labels"].copy()
        for index, row in enumerate(development):
            path = Path(row["image_path"])
            if sha(path) != row["source_sha256"]:
                raise ValueError("Development image changed")
            score, feature = model["session"].run(None, {model["input_name"]: preprocess(path.read_bytes(), model["config"])})
            baseline_scores.append(score[0])
            features.append(feature[0])
            if (index + 1) % 10 == 0:
                print(json.dumps({"stage": "development features", "done": index + 1, "total": len(development)}), flush=True)
    finally:
        service.close()
    features, baseline_scores = np.stack(features), np.stack(baseline_scores)
    np.savez_compressed(RUN / "development.npz", features=features, baseline_scores=baseline_scores,
                        source_sha256=np.array([row["source_sha256"] for row in development]))
    with np.load(BASE / "selected-development.npz", allow_pickle=False) as bank:
        old_x, old_y = bank["train_features"].copy(), bank["train_truth"].copy()
        hist_x, hist_y, hist_indexes = bank["validation_features"].copy(), bank["truth"].copy(), bank["indexes"].copy()
    with np.load(CURRENT / "head.npz", allow_pickle=False) as bank:
        active_coefficient, active_intercept = bank["coefficient"].copy(), bank["intercept"].copy()
    np.testing.assert_allclose(features @ active_coefficient.T + active_intercept, baseline_scores, atol=2e-5, rtol=2e-5)
    train_x, train_y, eligible = training_arrays(old_x, old_y, development, features)
    training = [row for row, keep in zip(development, eligible, strict=True) if keep]
    weights, class_weights = grouped_weights(old_y, training)
    from sklearn.linear_model import LogisticRegression
    estimator = LogisticRegression(C=100, class_weight=class_weights, max_iter=3000, random_state=42)
    estimator.fit(train_x, train_y, sample_weight=weights)
    coefficient, intercept = estimator.coef_.astype(np.float32), estimator.intercept_.astype(np.float32)
    validate_policy(policy, train_x, train_y)
    np.savez_compressed(RUN / "head.npz", coefficient=coefficient, intercept=intercept)
    np.savez_compressed(RUN / "training-references.npz", features=train_x, labels=train_y)
    write(RUN / "gate-policy.json", policy)
    selected = np.array([row["partition"] == "validation" for row in development])
    validation = [row for row in development if row["partition"] == "validation"]
    truth = np.array([CLASSES.index(row["source_label"]) for row in validation])
    candidate_scores = features[selected] @ coefficient.T + intercept
    np.testing.assert_allclose(candidate_scores, estimator.decision_function(features[selected]), atol=2e-5, rtol=2e-5)
    _, before_views = summarize(validation, baseline_scores[selected], features[selected], truth, policy, baseline_references, baseline_labels)
    _, after_views = summarize(validation, candidate_scores, features[selected], truth, policy, train_x, train_y)
    new = np.array([row["source_dataset"] == "physical-multiangle-20261019" for row in validation])
    new_rows = [row for row, keep in zip(validation, new, strict=True) if keep]
    before, before_eggs = group_report(new_rows, baseline_scores[selected][new], [row for row, keep in zip(before_views, new, strict=True) if keep])
    after, after_eggs = group_report(new_rows, candidate_scores[new], [row for row, keep in zip(after_views, new, strict=True) if keep])
    original_rows = [row for row, keep in zip(validation, new, strict=True) if not keep]
    original_before, _ = summarize(original_rows, baseline_scores[selected][~new], features[selected][~new], truth[~new], policy, baseline_references, baseline_labels)
    original_after, _ = summarize(original_rows, candidate_scores[~new], features[selected][~new], truth[~new], policy, train_x, train_y)
    historical_rows = [rows[int(i)] for i in hist_indexes]
    if any(row["partition"] != "validation" for row in historical_rows):
        raise ValueError("Historical evaluation includes a non-validation row")
    historical_before, _ = summarize(historical_rows, hist_x @ active_coefficient.T + active_intercept, hist_x, hist_y, policy, baseline_references, baseline_labels)
    historical_after, _ = summarize(historical_rows, hist_x @ coefficient.T + intercept, hist_x, hist_y, policy, train_x, train_y)
    failures = admission(before, after, historical_before, historical_after, original_before, original_after)
    report = {"scope": "DEVELOPMENT_COMPARISON_ONLY", "camera_training_eggs": len({r["physical_egg_id"] for r in training}),
              "camera_training_views": len(training), "camera_validation_before": before, "camera_validation_after": after,
              "original_camera_validation_before": original_before, "original_camera_validation_after": original_after,
              "historical_validation_before": historical_before, "historical_validation_after": historical_after,
              "admission_passed": not failures, "admission_failures": failures, "test_reopened": False,
              "fresh_independent_test_eggs": 0, "active_release_changed": False, "claim_99_percent_supported": False}
    write(RUN / "camera-validation-outcomes.json", {"before": before_eggs, "after": after_eggs,
                                                 "views_before": before_views, "views_after": after_views})
    write(RUN / "metrics.json", report)
    write(RUN / "config.json", {"status": "EXPLORATORY_GROUPED_MULTIANGLE_HEAD", "class_order": CLASSES,
          "operational_use_authorized": False, "encoder_onnx": str(registry.parent / "egg-grade/best.onnx"),
          "encoder_onnx_sha256": protected[str(registry.parent / "egg-grade/best.onnx")],
          "dataset_manifest": str(manifest), "dataset_sha256": audit["manifest_sha256"],
          "gates": "Active thresholds unchanged", "camera_weight_per_egg": 20, "class_weights": class_weights,
          "limitations": audit["limitations"]})
    for path, digest in protected.items():
        if sha(Path(path)) != digest:
            raise ValueError("Protected baseline or dataset changed")
    artifacts = ("head.npz", "training-references.npz", "gate-policy.json", "experiment-plan.json", "config.json", "metrics.json", "camera-validation-outcomes.json", "development.npz")
    write(RUN / "selection-lock.json", {"evaluator_sha256": sha(Path(__file__)), "plan_sha256": sha(plan_path),
          "admission_passed": not failures, "artifacts": {name: sha(RUN / name) for name in artifacts}})
    print(json.dumps(report), flush=True)
    return report


if __name__ == "__main__":
    run()
