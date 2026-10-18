"""Preserve the failed fixed head and tighten only margins that accepted validation errors."""
import copy
import json
from pathlib import Path
import shutil

import numpy as np

from balut_api.selective_gate import CLASSES, validate_policy
from .adapt_local_photos import summarize
from .train_camera_angles import ROOT, DATA, BASE, RUN as SOURCE, read, write, group_report, admission
from .camera_angles import sha

RUN = ROOT / "ml/runs/retained-multiangle-calibrated-20261019"


def tighten_margins(policy, outcomes):
    policy = copy.deepcopy(policy)
    for outcome in outcomes:
        label = outcome["sourcePrediction"]
        if label is not None and label != outcome["source_label"]:
            policy["minimum_margin"][label] = max(policy["minimum_margin"][label], outcome["decisionMargin"] + .0001)
    return policy


def run():
    if RUN.exists():
        raise FileExistsError("Preserve the completed or interrupted calibration")
    lock, first = read(SOURCE / "selection-lock.json"), read(SOURCE / "metrics.json")
    for name, digest in lock["artifacts"].items():
        if sha(SOURCE / name) != digest:
            raise ValueError("Frozen candidate artifact changed")
    audit, config = read(DATA / "audit.json"), read(SOURCE / "config.json")
    if audit["status"] != "EXPLORATORY_RETAINED_MULTIANGLE_DATASET" or sha(DATA / "manifest.jsonl") != config["dataset_sha256"]:
        raise ValueError("Complete camera dataset changed")
    if first["admission_passed"] or first["admission_failures"] != ["Accepted historical validation regressed"]:
        raise ValueError("Review the original failure before applying this bounded correction")
    protected = {str(SOURCE / name): digest for name, digest in lock["artifacts"].items()}
    RUN.mkdir()
    write(RUN / "experiment-plan.json", {"scope": "DEVELOPMENT_VALIDATION_CALIBRATION", "head_refitted": False,
          "original_failed_metrics_sha256": sha(SOURCE / "metrics.json"), "original_lock_sha256": sha(SOURCE / "selection-lock.json"),
          "head_sha256": sha(SOURCE / "head.npz"), "dataset_sha256": config["dataset_sha256"],
          "rule": "For each wrongly accepted validation label, raise its margin to the maximum offending margin plus 0.0001",
          "other_gates": "Keep quality, cosine, references and all other thresholds unchanged",
          "admission": "Apply the original comparison requirements without weakening them",
          "test_reopened": False, "claim_99_percent_supported": False})
    rows = [json.loads(line) for line in (DATA / "manifest.jsonl").read_text().splitlines() if line.strip()]
    development = [r for r in rows if (r.get("physical_egg_id") or "").startswith("physical-camera-20261018:") and r["partition"] in {"train", "validation"}]
    with np.load(SOURCE / "development.npz", allow_pickle=False) as bank:
        features = bank["features"].copy()
        np.testing.assert_array_equal(bank["source_sha256"], [row["source_sha256"] for row in development])
    with np.load(SOURCE / "head.npz", allow_pickle=False) as bank:
        coefficient, intercept = bank["coefficient"].copy(), bank["intercept"].copy()
    with np.load(SOURCE / "training-references.npz", allow_pickle=False) as bank:
        references, labels = bank["features"].copy(), bank["labels"].copy()
    with np.load(BASE / "selected-development.npz", allow_pickle=False) as bank:
        hist_x, hist_y, indexes = bank["validation_features"].copy(), bank["truth"].copy(), bank["indexes"].copy()
    historical = [rows[int(i)] for i in indexes]
    if any(row["partition"] != "validation" for row in historical):
        raise ValueError("Calibration includes a non-validation row")
    old_policy = read(SOURCE / "gate-policy.json")
    hist_scores = hist_x @ coefficient.T + intercept
    _, historical_outcomes = summarize(historical, hist_scores, hist_x, hist_y, old_policy, references, labels)
    previous_views = read(SOURCE / "camera-validation-outcomes.json")
    policy = tighten_margins(old_policy, historical_outcomes + previous_views["views_after"])
    updates = {label: {"before": old_policy["minimum_margin"][label], "after": policy["minimum_margin"][label]}
               for label in CLASSES if old_policy["minimum_margin"][label] != policy["minimum_margin"][label]}
    if not updates:
        raise ValueError("No wrongly accepted validation margin required correction")
    policy["previous_validation_margin_gate_counts"] = policy.pop("validation_margin_gate_counts", {})
    policy["calibration_scope"] = "Development validation only; repeated views are correlated; margins only increased after a documented false acceptance"
    validate_policy(policy, references, labels)
    selected = np.array([row["partition"] == "validation" for row in development])
    validation = [row for row in development if row["partition"] == "validation"]
    truth = np.array([CLASSES.index(row["source_label"]) for row in validation])
    scores = features[selected] @ coefficient.T + intercept
    _, after_views = summarize(validation, scores, features[selected], truth, policy, references, labels)
    new = np.array([row["source_dataset"] == "physical-multiangle-20261019" for row in validation])
    new_rows = [row for row, keep in zip(validation, new, strict=True) if keep]
    after, eggs = group_report(new_rows, scores[new], [row for row, keep in zip(after_views, new, strict=True) if keep])
    original_rows = [row for row, keep in zip(validation, new, strict=True) if not keep]
    original_after, _ = summarize(original_rows, scores[~new], features[selected][~new], truth[~new], policy, references, labels)
    historical_after, _ = summarize(historical, hist_scores, hist_x, hist_y, policy, references, labels)
    failures = admission(first["camera_validation_before"], after, first["historical_validation_before"], historical_after,
                         first["original_camera_validation_before"], original_after)
    report = {**first, "scope": "DEVELOPMENT_VALIDATION_CALIBRATION", "head_refitted": False, "margin_updates": updates,
              "camera_validation_after": after, "original_camera_validation_after": original_after,
              "historical_validation_after": historical_after, "admission_passed": not failures, "admission_failures": failures,
              "limitations": ["Calibration uses the same development validation; this is not a fresh accuracy test",
                              "Repeat photos are not independent new eggs; no 99 percent claim"]}
    for name in ("head.npz", "training-references.npz", "development.npz"):
        shutil.copyfile(SOURCE / name, RUN / name)
    write(RUN / "gate-policy.json", policy)
    write(RUN / "config.json", {**config, "status": "EXPLORATORY_GROUPED_MULTIANGLE_CALIBRATED_HEAD",
          "gates": "Only margin thresholds with documented validation false acceptance were raised", "margin_updates": updates})
    write(RUN / "camera-validation-outcomes.json", {"before": previous_views["before"], "after": eggs,
                                                   "views_before": previous_views["views_before"], "views_after": after_views})
    write(RUN / "metrics.json", report)
    for path, digest in protected.items():
        if sha(Path(path)) != digest:
            raise ValueError("Original failed candidate changed")
    artifacts = ("head.npz", "training-references.npz", "development.npz", "gate-policy.json", "config.json", "experiment-plan.json", "metrics.json", "camera-validation-outcomes.json")
    write(RUN / "selection-lock.json", {"evaluator_sha256": sha(Path(__file__)), "admission_passed": not failures,
          "artifacts": {name: sha(RUN / name) for name in artifacts}})
    print(json.dumps({"admission_passed": not failures, "admission_failures": failures, "margin_updates": updates,
                      "camera_before": first["camera_validation_before"], "camera_after": after,
                      "historical_after": historical_after["selective"], "head_refitted": False, "test_reopened": False}), flush=True)
    return report


if __name__ == "__main__":
    run()
