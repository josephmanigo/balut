"""Train an isolated age specialist; never activate it or select on test results."""
from __future__ import annotations

import argparse
import copy
import json
import os
from collections import Counter
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
os.environ.setdefault("OMP_NUM_THREADS", "4")

import numpy as np
from PIL import Image, ImageOps

from .adapt_local_photos import ROOT, encoder_session, prepare_input, validate_disjoint
from .local_photo_data import load_local_rows
from .public_data import sha256
from balut_api.selective_gate import CLASSES, decide, image_quality, validate_policy

BASE = ROOT / "ml/runs/selective-v2"
AGE_CLASSES = CLASSES[:2]


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def feature_view(features, view):
    values = np.asarray(features, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != 1664 or not np.isfinite(values).all():
        raise ValueError("Invalid retained feature vectors")
    if view == "dino":
        values = values[:, :384]
    elif view == "efficientnet":
        values = values[:, 384:]
    elif view != "fused":
        raise ValueError("Unknown feature view")
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    if np.any(norms < 1e-12):
        raise ValueError("Zero feature vector")
    return values / norms


def head_arrays(estimator, kind):
    if kind == "logistic":
        return {"coefficient": estimator.coef_.copy(), "intercept": estimator.intercept_.copy()}
    return {"support": estimator.support_vectors_.copy(), "dual": estimator.dual_coef_[0].copy(),
            "intercept": estimator.intercept_.copy(), "gamma": np.array([estimator._gamma])}


def head_scores(features, spec, arrays):
    values = feature_view(features, spec["view"])
    if any(not np.isfinite(a).all() for a in arrays.values()):
        raise ValueError("Nonfinite specialist head")
    if spec["kind"] == "logistic":
        result = (values @ arrays["coefficient"].T + arrays["intercept"]).ravel()
    elif spec["kind"] == "rbf":
        support = arrays["support"]
        distance = np.maximum((values ** 2).sum(1)[:, None] + (support ** 2).sum(1)[None] - 2 * values @ support.T, 0)
        result = np.exp(-arrays["gamma"][0] * distance) @ arrays["dual"] + arrays["intercept"][0]
    else:
        raise ValueError("Unknown specialist head")
    if result.shape != (len(values),) or not np.isfinite(result).all():
        raise ValueError("Invalid specialist output")
    return result


def learn_age_thresholds(scores, truth, contexts, minimum_examples=5):
    """Calibrate only on validation; zero observed errors is not a guarantee."""
    thresholds, support = {}, {}
    predicted = (np.asarray(scores) > 0).astype(int)
    margins = np.abs(scores)
    for class_id, label in enumerate(AGE_CLASSES):
        eligible = np.array([c["base_winner"] != 2 and not c["quality_reasons"]
                             and c["age_similarities"][class_id] >= c["novelty_limits"][class_id] for c in contexts])
        selected = eligible & (predicted == class_id) & (margins > 0)
        wrong = selected & (truth != class_id)
        threshold = float(margins[wrong].max()) + 1e-6 if wrong.any() else 0.0
        accepted = selected & (margins >= threshold)
        count = int(accepted.sum())
        thresholds[label] = threshold if count >= minimum_examples else None
        support[label] = {"accepted": count if count >= minimum_examples else 0,
                          "correct": int((accepted & (truth == class_id)).sum()) if count >= minimum_examples else 0}
    return {"minimum_margin": thresholds, "validation_support": support, "minimum_examples": minimum_examples,
            "calibration_scope": "Validation-only heuristic, not calibrated probabilities or certainty"}


def combine_decision(context, signed_score, age_policy):
    # The reject route uses the retained decision and recapture reasons exactly.
    if context["base_winner"] == 2:
        return copy.deepcopy(context["baseline"])
    if not np.isfinite(signed_score):
        raise ValueError("Nonfinite age score")
    winner = int(signed_score > 0)
    label = AGE_CLASSES[winner]
    threshold = age_policy["minimum_margin"][label]
    if threshold is not None and (not np.isfinite(threshold) or threshold < 0):
        raise ValueError("Invalid age threshold")
    reasons = list(context["quality_reasons"])
    if threshold is None:
        reasons.append("INSUFFICIENT_VALIDATION_SUPPORT")
    elif abs(signed_score) <= 0 or abs(signed_score) < threshold:
        reasons.append("AMBIGUOUS_APPEARANCE")
    similarity = context["age_similarities"][winner]
    if similarity < context["novelty_limits"][winner]:
        reasons.append("UNFAMILIAR_APPEARANCE")
    return {"sourcePrediction": None if reasons else label,
            "analysisOutcome": "RECAPTURE_REQUIRED" if reasons else "CLASSIFIED",
            "recaptureRequested": bool(reasons), "recaptureReasons": reasons, "reviewRequired": False,
            "qualityMeasurements": context["baseline"]["qualityMeasurements"], "decisionMargin": abs(float(signed_score)),
            "nearestTrainingCosine": similarity, "scoresAreProbabilities": False}


def context_for(image, scores, feature, policy, references, labels):
    baseline = decide(scores, feature, image, policy, references, labels)
    _, quality_reasons = image_quality(image, policy)
    return {"baseline": baseline, "base_winner": int(scores.argmax()), "quality_reasons": quality_reasons,
            "age_similarities": [float((references[labels == i] @ feature).max()) for i in (0, 1)],
            "novelty_limits": [policy["minimum_training_cosine"][label] for label in AGE_CLASSES]}


def extract(session, rows, policy, references, labels, stage):
    features, scores, contexts = [], [], []
    for i, row in enumerate(rows):
        path = Path(row["image_path"])
        if sha256(path) != row["source_sha256"]:
            raise ValueError("Dataset image changed")
        with Image.open(path) as original:
            image = ImageOps.exif_transpose(original).convert("RGB")
            values, vectors = session.run(None, {"images": prepare_input(image)})
            contexts.append(context_for(image, values[0], vectors[0], policy, references, labels))
        scores.append(values[0])
        features.append(vectors[0])
        if i % 64 == 0 or i + 1 == len(rows):
            print(json.dumps({"stage": stage, "completed": i + 1, "total": len(rows)}), flush=True)
    return np.stack(features), np.stack(scores), contexts


def metrics(contexts, truth, signed_scores=None, age_policy=None):
    from sklearn.metrics import balanced_accuracy_score, confusion_matrix, f1_score
    outcomes, raw = [], []
    for i, context in enumerate(contexts):
        candidate = signed_scores is not None
        result = combine_decision(context, signed_scores[i], age_policy) if candidate else copy.deepcopy(context["baseline"])
        raw_prediction = (int(signed_scores[i] > 0) if candidate and context["base_winner"] != 2 else context["base_winner"])
        raw.append(raw_prediction)
        outcomes.append({"index_in_evaluation": i, "truth": CLASSES[int(truth[i])],
                         "raw_prediction": CLASSES[raw_prediction], **result})
    raw = np.asarray(raw)
    accepted = [r for r in outcomes if r["sourcePrediction"] is not None]
    correct = sum(r["truth"] == r["sourcePrediction"] for r in accepted)
    age = truth < 2
    age_accepted = [r for r in accepted if r["truth"] in AGE_CLASSES]
    age_correct = sum(r["truth"] == r["sourcePrediction"] for r in age_accepted)
    summary = {"images": len(truth), "raw_correct": int((raw == truth).sum()),
               "raw_accuracy": float((raw == truth).mean()), "raw_confusion_matrix": confusion_matrix(truth, raw, labels=[0, 1, 2]).tolist(),
               "classified": len(accepted), "correct_classified": correct, "wrong_classified": len(accepted) - correct,
               "recaptures": len(truth) - len(accepted), "coverage": len(accepted) / len(truth),
               "accepted_accuracy": correct / len(accepted) if accepted else None, "correct_of_all_inputs": correct / len(truth),
               "age_images": int(age.sum()), "age_raw_correct": int((raw[age] == truth[age]).sum()),
               "age_raw_balanced_accuracy": float(balanced_accuracy_score(truth[age], raw[age])),
               "age_raw_macro_f1": float(f1_score(truth[age], raw[age], labels=[0, 1], average="macro", zero_division=0)),
               "age_classified": len(age_accepted), "age_correct_classified": age_correct,
               "age_wrong_classified": len(age_accepted) - age_correct,
               "by_true_class": {label: {"images": int((truth == i).sum()),
                                           "classified": sum(r["truth"] == label for r in accepted),
                                           "correct_classified": sum(r["truth"] == label == r["sourcePrediction"] for r in accepted)}
                                  for i, label in enumerate(CLASSES)},
               "recapture_reasons": dict(Counter(reason for r in outcomes for reason in r["recaptureReasons"]))}
    return summary, outcomes


def selection_key(result):
    return tuple(result[k] for k in ("age_raw_balanced_accuracy", "age_raw_macro_f1", "age_correct_classified"))


def train(output):
    from sklearn.linear_model import LogisticRegression
    from sklearn.svm import SVC

    if output.exists():
        raise FileExistsError("Choose a fresh experiment directory")
    manifest = ROOT / "ml/runs/three-class-v1/manifest.jsonl"
    base_config = json.loads((BASE / "config.json").read_text())
    if sha256(manifest) != base_config["manifest_sha256"]:
        raise ValueError("Historical manifest changed")
    rows = [json.loads(line) for line in manifest.read_text().splitlines()]
    for key in ("duplicate_group", "pixel_sha256", "source_sha256"):
        partitions = {}
        for row in rows:
            if row[key] in partitions and partitions[row[key]] != row["partition"]:
                raise ValueError("Historical image group crosses partitions")
            partitions[row[key]] = row["partition"]
    local_manifest = ROOT / "data/local/user-day16-day18-20261014/manifest.jsonl"
    local, local_audit = load_local_rows(local_manifest)
    validate_disjoint(local, rows)
    train_rows = [r for r in rows if r["partition"] == "train" and r["source_label"] in AGE_CLASSES]
    validation = [r for r in rows if r["partition"] == "validation"]
    protected_paths = [BASE / n for n in ("best.onnx", "best.pt", "config.json", "gate-policy.json", "training-references.npz")]
    release = ROOT / "deployment/releases/automatic-recapture-20260912"
    protected_paths.append(release / "registry.json")
    registry = json.loads((release / "registry.json").read_text())
    for model in registry["models"]:
        for field in ("model", "config", "gate_policy", "training_references", "known_answer"):
            item = model[field]
            if sha256(release / item["path"]) != item["sha256"]:
                raise ValueError("Retained release hash mismatch")
            protected_paths.append(release / item["path"])
    protected = {str(path): sha256(path) for path in protected_paths}
    grid = [{"view": view, "kind": kind, "C": c, "local_weight": weight}
            for view in ("fused", "dino", "efficientnet")
            for kind, c in (("logistic", 1.0), ("logistic", 10.0), ("logistic", 100.0), ("rbf", 10.0))
            for weight in (0.0, 0.25)]
    output.mkdir(parents=True)
    plan = {"status": "EXPLORATORY_AGE_SPECIALIST", "grid": grid, "candidate_limit": len(grid),
            "selection": "Validation age balanced accuracy, age macro F1, accepted correct ages; first candidate breaks ties",
            "architecture": "Frozen retained ONNX encoder and reject route; independent binary DAY_16/DAY_18 head",
            "age_acceptance": "Retained image-quality and class novelty limits; binary margin calibrated on validation with five examples per predicted age",
            "manifest_sha256": sha256(manifest), "local_manifest_sha256": sha256(local_manifest),
            "protected_files": protected, "seed": 42, "train_age_counts": dict(Counter(r["source_label"] for r in train_rows)),
            "local_eligible_counts": dict(Counter(r["source_label"] for r in local if r["training_eligible"])),
            "local_partition": "Entire collection is training-only, including if selected model uses zero local weight",
            "day_tracker": "Excluded due to annotation errors and unresolved provenance",
            "test_policy": "Lock head, policy, config and plan before one historical regression evaluation. Never reselect after test.",
            "promotion": "Never automatically activate. Historical public test is previously inspected; verified unseen eggs required.",
            "unseen_egg_evaluation_available": False,
            "limitations": base_config["limitations"] + local_audit["limitations"]}
    write(output / "experiment-plan.json", plan)
    session_config = {"encoder_onnx": str(BASE / "best.onnx"), "encoder_onnx_sha256": protected[str(BASE / "best.onnx")]}
    session = encoder_session(session_config)
    policy = json.loads((BASE / "gate-policy.json").read_text())
    with np.load(BASE / "training-references.npz", allow_pickle=False) as bank:
        references, labels = bank["features"].copy(), bank["labels"].copy()
    validate_policy(policy, references, labels)
    train_x, _, _ = extract(session, train_rows, policy, references, labels, "age_training_features")
    val_x, val_scores, val_context = extract(session, validation, policy, references, labels, "validation_features")
    local_x, local_scores, local_context = extract(session, local, policy, references, labels, "local_training_features")
    train_y = np.array([CLASSES.index(r["source_label"]) for r in train_rows])
    val_y = np.array([CLASSES.index(r["source_label"]) for r in validation])
    local_y = np.array([CLASSES.index(r["source_label"]) for r in local])
    eligible = np.array([r["training_eligible"] for r in local], dtype=bool)
    np.savez_compressed(output / "development.npz", train_features=train_x, train_truth=train_y,
                        validation_features=val_x, validation_scores=val_scores, validation_truth=val_y,
                        local_features=local_x, local_scores=local_scores, local_truth=local_y, local_eligible=eligible)
    baseline_validation, _ = metrics(val_context, val_y)
    best = None
    for spec in grid:
        x = train_x if spec["local_weight"] == 0 else np.concatenate([train_x, local_x[eligible]])
        y = train_y if spec["local_weight"] == 0 else np.concatenate([train_y, local_y[eligible]])
        weights = np.ones(len(train_y)) if spec["local_weight"] == 0 else np.r_[np.ones(len(train_y)), np.full(eligible.sum(), spec["local_weight"])]
        estimator = (LogisticRegression(C=spec["C"], class_weight="balanced", max_iter=3000, random_state=42)
                     if spec["kind"] == "logistic" else SVC(C=spec["C"], kernel="rbf", gamma="scale", class_weight="balanced", random_state=42))
        estimator.fit(feature_view(x, spec["view"]), y, sample_weight=weights)
        if estimator.classes_.tolist() != [0, 1]:
            raise ValueError("Specialist training requires both age classes")
        arrays = head_arrays(estimator, spec["kind"])
        signed = head_scores(val_x, spec, arrays)
        native = estimator.decision_function(feature_view(val_x, spec["view"]))
        error = float(np.max(np.abs(native - signed)))
        if error > 1e-8 or not np.array_equal(native > 0, signed > 0):
            raise ValueError("Portable specialist does not match estimator")
        age_policy = learn_age_thresholds(signed, val_y, val_context)
        result, _ = metrics(val_context, val_y, signed, age_policy)
        record = {"spec": spec, "validation": result, "age_policy": age_policy, "portable_maximum_score_error": error}
        with (output / "search.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        if best is None or selection_key(result) > selection_key(best["validation"]):
            best = record
            np.savez_compressed(output / "age-head.npz", **arrays)
        print(json.dumps({"candidate": spec, "age_balanced_accuracy": result["age_raw_balanced_accuracy"],
                          "accepted_correct_ages": result["age_correct_classified"]}), flush=True)
    write(output / "age-policy.json", best["age_policy"])
    config = {"status": "EXPLORATORY_AGE_SPECIALIST", "operational_use_authorized": False,
              **session_config, "base_policy": str(BASE / "gate-policy.json"), "base_policy_sha256": protected[str(BASE / "gate-policy.json")],
              "references": str(BASE / "training-references.npz"), "references_sha256": protected[str(BASE / "training-references.npz")],
              "specialist": best["spec"], "input": "Same cropped RGB image supplied to retained model; local diagnostics use saved framing crops",
              "scope": "Shared retained encoder with separate binary age head. Not a standalone deployment bundle."}
    write(output / "config.json", config)
    lock = {"selected": best, "baseline_validation": baseline_validation,
            "artifacts": {name: sha256(output / name) for name in ("age-head.npz", "age-policy.json", "config.json", "development.npz", "experiment-plan.json", "search.jsonl")}}
    write(output / "selection-lock.json", lock)
    print("Candidate and policy locked. Starting one historical regression evaluation.", flush=True)
    with np.load(output / "age-head.npz", allow_pickle=False) as data:
        arrays = {key: data[key].copy() for key in data.files}
    selected_spec, age_policy = best["spec"], best["age_policy"]
    test_rows = [r for r in rows if r["partition"] == "test"]
    test_x, test_scores, test_context = extract(session, test_rows, policy, references, labels, "historical_regression")
    test_y = np.array([CLASSES.index(r["source_label"]) for r in test_rows])
    baseline_test, baseline_outcomes = metrics(test_context, test_y)
    candidate_test, candidate_outcomes = metrics(test_context, test_y, head_scores(test_x, selected_spec, arrays), age_policy)
    for old, new, row, context in zip(baseline_outcomes, candidate_outcomes, test_rows, test_context, strict=True):
        old["image_path"] = new["image_path"] = row["image_path"]
        if context["base_winner"] == 2 and old != new:
            raise ValueError("Retained reject route changed")
    write(output / "baseline-test-outcomes.json", baseline_outcomes)
    write(output / "candidate-test-outcomes.json", candidate_outcomes)
    local_before, _ = metrics(local_context, local_y)
    local_after, local_outcomes = metrics(local_context, local_y, head_scores(local_x, selected_spec, arrays), age_policy)
    write(output / "local-diagnostic-outcomes.json", local_outcomes)
    evaluation = {"baseline_validation": baseline_validation, "candidate_validation": best["validation"],
                  "baseline_historical": baseline_test, "candidate_historical": candidate_test,
                  "local_before": local_before, "local_after": local_after,
                  "local_interpretation": "Training-collection diagnostic, never independent accuracy",
                  "historical_interpretation": "Previously inspected public image holdout; physical egg identities unknown; not an unseen-egg test",
                  "unseen_eggs_evaluated": 0, "promoted": False, "promotion_reason": "No independently identified unseen eggs available",
                  "selection_lock_sha256": sha256(output / "selection-lock.json")}
    write(output / "metrics.json", evaluation)
    for path, digest in protected.items():
        if sha256(Path(path)) != digest:
            raise ValueError("Retained artifact changed")
    for name, digest in lock["artifacts"].items():
        if sha256(output / name) != digest:
            raise ValueError("Candidate changed after selection lock")
    write(output / "verification.json", {"passed": True, "protected_files_unchanged": len(protected),
                                         "locked_artifacts_verified": len(lock["artifacts"]), "reject_route_unchanged": True,
                                         "portable_head_verified_on_all_validation_examples": True, "retained_model_promoted_over": False})
    print(json.dumps({"selected": selected_spec, "baseline_historical": baseline_test,
                      "candidate_historical": candidate_test, "promoted": False}, indent=2), flush=True)


def predict(run, image_path):
    lock = json.loads((run / "selection-lock.json").read_text())
    for name, digest in lock["artifacts"].items():
        if sha256(run / name) != digest:
            raise ValueError("Locked candidate artifact changed")
    config = json.loads((run / "config.json").read_text())
    for path_key, hash_key in (("base_policy", "base_policy_sha256"), ("references", "references_sha256")):
        if sha256(Path(config[path_key])) != config[hash_key]:
            raise ValueError("Retained dependency changed")
    session = encoder_session(config)
    policy = json.loads(Path(config["base_policy"]).read_text())
    age_policy = json.loads((run / "age-policy.json").read_text())
    with np.load(config["references"], allow_pickle=False) as data:
        references, labels = data["features"].copy(), data["labels"].copy()
    validate_policy(policy, references, labels)
    with np.load(run / "age-head.npz", allow_pickle=False) as data:
        arrays = {key: data[key].copy() for key in data.files}
    with Image.open(image_path) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
        scores, features = session.run(None, {"images": prepare_input(image)})
        context = context_for(image, scores[0], features[0], policy, references, labels)
    signed = head_scores(features, config["specialist"], arrays)[0]
    return {"status": config["status"], "operational_use_authorized": False,
            "retained_result": context["baseline"], "candidate_result": combine_decision(context, signed, age_policy)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fit = commands.add_parser("train")
    fit.add_argument("output", type=Path)
    prediction = commands.add_parser("predict")
    prediction.add_argument("run", type=Path)
    prediction.add_argument("image", type=Path)
    args = parser.parse_args()
    if args.command == "train":
        train(args.output)
    else:
        print(json.dumps(predict(args.run, args.image), indent=2))
