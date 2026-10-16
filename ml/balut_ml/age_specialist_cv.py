"""Select one nonlinear age head on training folds, then assess validation only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
from sklearn.metrics import balanced_accuracy_score, f1_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.svm import SVC

from .age_specialist import (
    AGE_CLASSES, BASE, CLASSES, ROOT, context_for, feature_view, head_arrays,
    head_scores, learn_age_thresholds, metrics, write,
)
from .public_data import sha256
from balut_api.selective_gate import validate_policy

PREVIOUS = ROOT / "ml/runs/age-specialist-20261014"


def validate_folds(truth, groups, folds):
    seen = np.zeros(len(truth), dtype=int)
    expected = set(range(len(truth)))
    for training, held in folds:
        if (len(set(training)) != len(training) or len(set(held)) != len(held)
                or set(training) & set(held) or set(training) | set(held) != expected):
            raise ValueError("Invalid fold indexes")
        if set(groups[training]) & set(groups[held]):
            raise ValueError("Image family crosses a fold")
        if set(truth[training]) != {0, 1} or set(truth[held]) != {0, 1}:
            raise ValueError("Both ages are required in every fold")
        seen[held] += 1
    if not np.all(seen == 1):
        raise ValueError("Every training image needs one held-out fold")


def admission_checks(baseline, candidate, policy):
    return {
        "both_age_outputs_enabled": all(policy["minimum_margin"][label] is not None for label in AGE_CLASSES),
        "raw_age_balanced_accuracy_improved": candidate["age_raw_balanced_accuracy"] > baseline["age_raw_balanced_accuracy"],
        "day16_correct_issued_not_lower": candidate["by_true_class"]["DAY_16"]["correct_classified"] >= baseline["by_true_class"]["DAY_16"]["correct_classified"],
        "day18_correct_issued_not_lower": candidate["by_true_class"]["DAY_18"]["correct_classified"] >= baseline["by_true_class"]["DAY_18"]["correct_classified"],
        "age_errors_not_higher": candidate["age_wrong_classified"] <= baseline["age_wrong_classified"],
        "coverage_not_lower": candidate["classified"] >= baseline["classified"],
    }


def train(output):
    if output.exists():
        raise FileExistsError("Choose a fresh experiment directory")
    previous_plan = json.loads((PREVIOUS / "experiment-plan.json").read_text())
    previous_lock = json.loads((PREVIOUS / "selection-lock.json").read_text())
    previous_config = json.loads((PREVIOUS / "config.json").read_text())
    for name, digest in previous_lock["artifacts"].items():
        if sha256(PREVIOUS / name) != digest:
            raise ValueError("Previous development artifact changed")
    protected = previous_plan["protected_files"]
    for name, digest in protected.items():
        if sha256(Path(name)) != digest:
            raise ValueError("Retained artifact changed")
    manifest = ROOT / "ml/runs/three-class-v1/manifest.jsonl"
    if sha256(manifest) != previous_plan["manifest_sha256"]:
        raise ValueError("Historical manifest changed")
    # Read manifest metadata for integrity; no historical test image or prediction is loaded.
    rows = [json.loads(line) for line in manifest.read_text().splitlines()]
    training = [r for r in rows if r["partition"] == "train" and r["source_label"] in AGE_CLASSES]
    groups = np.array([r["duplicate_group"] for r in training])
    with np.load(PREVIOUS / "development.npz", allow_pickle=False) as cache:
        train_x, train_y = cache["train_features"].copy(), cache["train_truth"].copy()
    if not np.array_equal(train_y, [CLASSES.index(r["source_label"]) for r in training]):
        raise ValueError("Cached training order mismatch")
    folds = list(StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42).split(train_x, train_y, groups))
    validate_folds(train_y, groups, folds)
    grid = [{"kind": "rbf", "view": view, "C": c, "gamma": gamma, "local_weight": 0.0}
            for view in ("fused", "dino") for c in (1.0, 10.0, 100.0) for gamma in (1.0, 5.0, 20.0)]
    output.mkdir(parents=True)
    write(output / "experiment-plan.json", {
        "status": "EXPLORATORY_GROUPED_CV_AGE_SPECIALIST", "grid": grid, "seed": 42,
        "selection": "Mean training-fold age balanced accuracy, worst-fold balanced accuracy, pooled age macro F1; first breaks ties",
        "folds": 5, "training_images": len(training), "source_families": len(set(groups)),
        "physical_egg_ids_available": False, "local_photos": "Excluded after prior validation comparison; remain training-only",
        "validation_admission": "Both ages enabled, raw age balanced accuracy improves, correct issued predictions for each age and coverage do not fall, age errors do not rise",
        "calibration": "Margin thresholds fitted on validation. Validation acceptance is an optimistic development result, not an independent test.",
        "historical_test": "Not evaluated, and no historical test images or predictions loaded",
        "promotion": "Never activate; new independently identified eggs and batches are required",
        "inputs": {str(manifest): sha256(manifest), str(PREVIOUS / "development.npz"): sha256(PREVIOUS / "development.npz")},
        "protected_files": protected,
    })
    write(output / "folds.json", {"groups": groups.tolist(), "folds": [{"train": a.tolist(), "held_out": b.tolist()} for a, b in folds]})
    best = None
    for spec in grid:
        x = feature_view(train_x, spec["view"])
        predictions = np.full(len(train_y), -1, dtype=int)
        scores = np.full(len(train_y), np.nan)
        fold_scores = []
        for fit, held in folds:
            estimator = SVC(C=spec["C"], gamma=spec["gamma"], kernel="rbf", class_weight="balanced")
            estimator.fit(x[fit], train_y[fit])
            scores[held] = estimator.decision_function(x[held])
            predictions[held] = (scores[held] > 0).astype(int)
            fold_scores.append(float(balanced_accuracy_score(train_y[held], predictions[held])))
        if not np.isfinite(scores).all():
            raise ValueError("Missing out-of-fold predictions")
        key = (float(np.mean(fold_scores)), min(fold_scores), float(f1_score(train_y, predictions, average="macro")))
        record = {"spec": spec, "selection_key": key, "fold_balanced_accuracy": fold_scores,
                  "out_of_fold_correct": int((predictions == train_y).sum()), "out_of_fold_images": len(train_y)}
        with (output / "search.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        if best is None or key > tuple(best["selection_key"]):
            best = record
        print(json.dumps({"candidate": spec, "mean_fold_balanced_accuracy": key[0]}), flush=True)
    spec = best["spec"]
    estimator = SVC(C=spec["C"], gamma=spec["gamma"], kernel="rbf", class_weight="balanced")
    estimator.fit(feature_view(train_x, spec["view"]), train_y)
    arrays = head_arrays(estimator, "rbf")
    np.savez_compressed(output / "age-head.npz", **arrays)
    config = {**previous_config, "status": "EXPLORATORY_GROUPED_CV_AGE_SPECIALIST", "specialist": spec}
    write(output / "config.json", config)
    frozen = {name: sha256(output / name) for name in ("experiment-plan.json", "folds.json", "search.jsonl", "age-head.npz", "config.json")}
    write(output / "cv-selection-lock.json", {"selected": best, "artifacts": frozen})
    print("Training-fold selection locked. Assessing validation only.", flush=True)

    validation = [r for r in rows if r["partition"] == "validation"]
    with np.load(PREVIOUS / "development.npz", allow_pickle=False) as cache:
        val_x, val_y, val_scores = (cache[k].copy() for k in ("validation_features", "validation_truth", "validation_scores"))
    if not np.array_equal(val_y, [CLASSES.index(r["source_label"]) for r in validation]):
        raise ValueError("Cached validation order mismatch")
    policy = json.loads((BASE / "gate-policy.json").read_text())
    with np.load(BASE / "training-references.npz", allow_pickle=False) as bank:
        references, labels = bank["features"].copy(), bank["labels"].copy()
    validate_policy(policy, references, labels)
    contexts = []
    for row, scores, feature in zip(validation, val_scores, val_x, strict=True):
        if sha256(Path(row["image_path"])) != row["source_sha256"]:
            raise ValueError("Validation image changed")
        with Image.open(row["image_path"]) as original:
            contexts.append(context_for(ImageOps.exif_transpose(original).convert("RGB"), scores, feature, policy, references, labels))
    signed = head_scores(val_x, spec, arrays)
    native = estimator.decision_function(feature_view(val_x, spec["view"]))
    error = float(np.max(np.abs(signed - native)))
    if error > 1e-8 or not np.array_equal(signed > 0, native > 0):
        raise ValueError("Portable head disagrees with fitted classifier")
    age_policy = learn_age_thresholds(signed, val_y, contexts)
    baseline, baseline_outcomes = metrics(contexts, val_y)
    candidate, candidate_outcomes = metrics(contexts, val_y, signed, age_policy)
    for old, new, row in zip(baseline_outcomes, candidate_outcomes, validation, strict=True):
        old["image_path"] = new["image_path"] = row["image_path"]
        if old["raw_prediction"] == "REJECT" and old != new:
            raise ValueError("Reject route changed")
    write(output / "baseline-validation-outcomes.json", baseline_outcomes)
    write(output / "candidate-validation-outcomes.json", candidate_outcomes)
    write(output / "age-policy.json", age_policy)
    checks = admission_checks(baseline, candidate, age_policy)
    evaluation = {"selected": best, "baseline_validation": baseline, "candidate_validation": candidate,
                  "validation_admission": checks, "validation_passed": all(checks.values()),
                  "historical_test_evaluated": False, "unseen_eggs_evaluated": 0, "promoted": False,
                  "portable_head_maximum_score_error": error}
    write(output / "metrics.json", evaluation)
    for name, digest in frozen.items():
        if sha256(output / name) != digest:
            raise ValueError("Candidate changed after training-fold selection")
    for name, digest in protected.items():
        if sha256(Path(name)) != digest:
            raise ValueError("Retained artifact changed")
    names = [*frozen, "cv-selection-lock.json", "age-policy.json", "metrics.json"]
    write(output / "selection-lock.json", {"selected": best, "artifacts": {name: sha256(output / name) for name in names}})
    write(output / "verification.json", {"passed": True, "protected_files_unchanged": len(protected),
                                         "fold_integrity_passed": True, "head_locked_before_validation": True,
                                         "reject_route_unchanged": True, "historical_test_evaluated": False})
    print(json.dumps(evaluation, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    train(parser.parse_args().output)
