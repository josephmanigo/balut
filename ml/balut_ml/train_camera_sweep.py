"""Retrain the retained three-class head with grouped camera views; keep tests closed."""
from collections import Counter
import copy
import json
from pathlib import Path

import numpy as np

from balut_api.model_service import ModelService, active_registry, preprocess, view_consensus
from balut_api.selective_gate import CLASSES, validate_policy
from .adapt_local_photos import summarize
from .camera_angles import ROOT, sha
from .train_camera_angles import grouped_weights, read, write
from scripts.camera_egg_ids import partition_for

DATA = ROOT / "data/local/retained-camera-rejects-20261019"
RUN = ROOT / "ml/runs/retained-camera-50views-rejects-20261019"
BASE = ROOT / "ml/runs/selective-v2"
CACHE = ROOT / "ml/runs/retained-multiangle-20261019"
CAMERA_WEIGHTS = (20, 50, 100)


def development_rows(rows):
    families = {}
    for row in rows:
        egg = row.get("physical_egg_id") or ""
        if egg.startswith("physical-camera-20261018:"):
            age, split = partition_for(egg.split(":")[1])
            if row["source_label"] != f"DAY_{age}" or row["partition"] != split:
                raise ValueError("Original age egg label or partition changed")
            expected = 54
        elif egg.startswith("physical-reject-20261019:"):
            split = {"R1": "train", "R2": "validation", "R3": "test"}.get(egg.split(":")[1])
            if (not split or row["source_label"] != "REJECT" or row["partition"] != split
                    or row["capture_record"]["defect_independently_confirmed"] is not False):
                raise ValueError("Reject provenance or partition changed")
            expected = 50
        else:
            continue
        families.setdefault(egg, []).append(row)
        if len(families[egg]) > expected:
            raise ValueError("Unexpected number of views for a physical egg")
    if len(families) != 33 or any(len(family) != (50 if egg.startswith("physical-reject") else 54)
                                  for egg, family in families.items()):
        raise ValueError("Complete all 30 age eggs and three Reject eggs before training")
    selected = [row for row in rows if row.get("physical_egg_id") in families and row["partition"] in {"train", "validation"}]
    if len(selected) != 1180 or any(row.get("test_status") for row in selected):
        raise ValueError("Development includes unexpected or reserved test data")
    return selected


def scan_report(rows, scores, outcomes, fifty=True):
    families = {}
    for index, row in enumerate(rows):
        families.setdefault(row["physical_egg_id"], []).append(index)
    scans = []
    for egg, indexes in families.items():
        if len({rows[i]["source_label"] for i in indexes}) != 1:
            raise ValueError("A physical egg has conflicting labels")
        if fifty:
            slots = {rows[i]["capture_record"]["angle_bin"]: i for i in indexes}
            if len(indexes) != 50 or set(slots) != set(range(50)):
                raise ValueError("Scan comparison requires all 50 distinct commanded bins")
            triples = [[slots[i], slots[i+17], slots[i+34]] for i in range(16)]
        else:
            if len(indexes) != 3:
                raise ValueError("Original scan comparison requires three views")
            triples = [indexes]
        for number, triple in enumerate(triples):
            prediction, reasons, accepted = view_consensus([outcomes[i] for i in triple], [rows[i]["source_sha256"] for i in triple])
            scans.append({"physical_egg_id": egg, "scan_index": number, "truth": rows[triple[0]]["source_label"],
                          "raw_prediction": CLASSES[int(scores[triple].mean(0).argmax())], "sourcePrediction": prediction,
                          "recaptureReasons": reasons, "accepted_distinct_views": accepted})
    by_class = {}
    for label in CLASSES:
        chosen = [s for s in scans if s["truth"] == label]
        accepted = [s for s in chosen if s["sourcePrediction"]]
        correct = sum(s["sourcePrediction"] == label for s in accepted)
        by_class[label] = {"physical_eggs": len({s["physical_egg_id"] for s in chosen}), "scans": len(chosen),
                           "raw_correct": sum(s["raw_prediction"] == label for s in chosen), "classified": len(accepted),
                           "correct_classified": correct, "wrong_classified": len(accepted)-correct}
    classified = sum(c["classified"] for c in by_class.values())
    correct = sum(c["correct_classified"] for c in by_class.values())
    report = {"physical_eggs": len(families), "correlated_scans": len(scans), "classified": classified,
              "correct_classified": correct, "wrong_classified": classified-correct,
              "raw_correct": sum(c["raw_correct"] for c in by_class.values()), "coverage": classified/len(scans),
              "accepted_accuracy": correct/classified if classified else None, "correct_of_all_inputs": correct/len(scans),
              "macro_correct_of_all_inputs": float(np.mean([c["correct_classified"]/c["scans"] for c in by_class.values() if c["scans"]])),
              "by_true_class": by_class}
    return report, scans


def admission(before, after, historical_before, historical_after, original_before, original_after, single_before, single_after):
    failures = []
    if after["correct_classified"] <= before["correct_classified"]:
        failures.append("No increase in correct accepted fifty-view validation scans")
    for label in CLASSES:
        old, new = before["by_true_class"][label], after["by_true_class"][label]
        if (new["correct_classified"] < max(old["correct_classified"], (new["scans"]+1)//2)
                or new["raw_correct"] < old["raw_correct"] or new["wrong_classified"] > old["wrong_classified"]
                or new["classified"] < old["classified"]):
            failures.append(f"Insufficient or regressed {label} camera validation support")
    if (original_after["correct_classified"] < original_before["correct_classified"]
            or original_after["wrong_classified"] > original_before["wrong_classified"]
            or original_after["raw_correct"] < original_before["raw_correct"]):
        failures.append("Original three-view camera validation regressed")
    for name, old, new in (("historical", historical_before, historical_after), ("original camera frames", single_before, single_after)):
        if (new["selective"]["correct_classified"] < old["selective"]["correct_classified"]
                or new["selective"]["wrong_classified"] > old["selective"]["wrong_classified"]
                or new["raw"]["correct"] < old["raw"]["correct"] or new["raw"]["macro_f1"] < old["raw"]["macro_f1"]):
            failures.append(f"Retained {name} validation regressed")
    return failures


def run():
    if RUN.exists():
        raise FileExistsError("Preserve the completed or interrupted retraining run")
    audit = read(DATA / "audit.json")
    manifest = DATA / "manifest.jsonl"
    if (audit["status"] != "EXPLORATORY_RETAINED_REJECT_DATASET" or audit["completed_eggs"] != 3
            or audit["new_views"] != 150 or audit["total_rows"] != 3831 or sha(manifest) != audit["manifest_sha256"]):
        raise ValueError("Complete and verify all age and Reject captures before retraining")
    rows = list(map(json.loads, manifest.read_text().splitlines()))
    development = development_rows(rows)
    registry = active_registry(ROOT)
    config = read(registry)
    entry = next(m for m in config["models"] if m["id"] == "egg-grade")
    protected_paths = [registry, ROOT / "deployment/active-release.txt", manifest, BASE / "selected-development.npz",
                       CACHE / "development.npz", CACHE / "selection-lock.json", CACHE / "config.json", Path(__file__)]
    protected_paths += [registry.parent / entry["model"]["path"]]
    protected_paths += [registry.parent / entry["camera_head"][name]["path"] for name in ("head", "gate_policy", "training_references")]
    protected = {str(p): sha(p) for p in protected_paths}
    if sha(BASE / "selected-development.npz") != read(BASE / "selection-lock.json")["development_data_sha256"]:
        raise ValueError("Retained development feature bank changed")
    if sha(CACHE / "development.npz") != read(CACHE / "selection-lock.json")["artifacts"]["development.npz"]:
        raise ValueError("Original camera feature cache changed")
    if (sha(CACHE / "config.json") != read(CACHE / "selection-lock.json")["artifacts"]["config.json"]
            or read(CACHE / "config.json")["encoder_onnx_sha256"] != protected[str(registry.parent / entry["model"]["path"])]):
        raise ValueError("Cached camera features use a different encoder")
    RUN.mkdir()
    write(RUN / "experiment-plan.json", {"dataset_sha256": audit["manifest_sha256"], "candidate_C": 100,
          "camera_weights_per_physical_egg": CAMERA_WEIGHTS, "fitted_data": "Historical training plus 11 eligible camera training eggs only",
          "validation": "Original validation roles only; all views of each physical egg retain one partition",
          "scans": "16 disjoint three-view groups per 50-view egg at commanded bins i,i+17,i+34 for i=0..15; bins16,33 only in per-view metrics",
          "selection": "Prefer candidates passing all admission gates, then macro correct-over-all scans, correct accepted scans, fewer errors, raw correct; first tie",
          "admission": "Strict increase in correct accepted scans, no per-class raw/accepted/coverage regression, at least half scans correct accepted per class, no historical or earlier-camera regression",
          "policy": "Current camera quality, ambiguity and unfamiliar-image thresholds unchanged", "test_images_opened": 0,
          "label_limit": "Reject labels are vendor reports without confirmed reasons; incubation timestamps are not independently supplied",
          "protected_files": protected, "active_release_changed": False, "claim_99_percent_supported": False})
    with np.load(CACHE / "development.npz", allow_pickle=False) as bank:
        cached = dict(zip(bank["source_sha256"].tolist(), bank["features"], strict=True))
    service = ModelService()
    vectors = []
    try:
        service.load(registry, protected[str(registry)])
        model = service.models["egg-grade"]
        baseline = model["camera"]
        old_coefficient, old_intercept = baseline["coefficient"].copy(), baseline["intercept"].copy()
        old_refs, old_labels = baseline["references"].copy(), baseline["reference_labels"].copy()
        policy = copy.deepcopy(baseline["policy"])
        for index, row in enumerate(development):
            path = Path(row["image_path"])
            if sha(path) != row["source_sha256"]:
                raise ValueError("Training or validation image changed")
            feature = cached.get(row["source_sha256"])
            if feature is None:
                feature = model["session"].run(None, {model["input_name"]: preprocess(path.read_bytes(), model["config"])})[1][0]
            vectors.append(feature)
            if (index+1) % 25 == 0:
                print(json.dumps({"stage": "development features", "done": index+1, "total": len(development)}), flush=True)
    finally:
        service.close()
    vectors = np.stack(vectors)
    np.savez_compressed(RUN / "development.npz", features=vectors, source_sha256=np.array([r["source_sha256"] for r in development]))
    with np.load(BASE / "selected-development.npz", allow_pickle=False) as bank:
        old_x, old_y = bank["train_features"].copy(), bank["train_truth"].copy()
        hist_x, hist_y, hist_indexes, train_indexes = (bank[name].copy() for name in ("validation_features", "truth", "indexes", "train_indexes"))
    if any(rows[int(i)]["partition"] != "train" for i in train_indexes) or any(rows[int(i)]["partition"] != "validation" for i in hist_indexes):
        raise ValueError("Historical feature partitions changed")
    np.testing.assert_array_equal(old_y, [CLASSES.index(rows[int(i)]["source_label"]) for i in train_indexes])
    np.testing.assert_array_equal(hist_y, [CLASSES.index(rows[int(i)]["source_label"]) for i in hist_indexes])
    eligible = np.array([r["partition"] == "train" and r["training_eligible"] for r in development])
    training = [r for r, keep in zip(development, eligible, strict=True) if keep]
    if len(training) != 590 or len({r["physical_egg_id"] for r in training}) != 11 or {r["source_label"] for r in training} != set(CLASSES):
        raise ValueError("All 11 physical training eggs and three classes are required")
    train_x = np.concatenate((old_x, vectors[eligible]))
    train_y = np.concatenate((old_y, np.array([CLASSES.index(r["source_label"]) for r in training])))
    weights, classes = grouped_weights(old_y, training)
    selected = np.array([r["partition"] == "validation" for r in development])
    validation = [r for r in development if r["partition"] == "validation"]
    val_x = vectors[selected]
    truth = np.array([CLASSES.index(r["source_label"]) for r in validation])
    historical = [rows[int(i)] for i in hist_indexes]

    def evaluate(coefficient, intercept, references, labels):
        scores = val_x @ coefficient.T + intercept
        view_metrics, outcomes = summarize(validation, scores, val_x, truth, policy, references, labels)
        reports, scans = {}, {}
        for key, source, fifty in (("sweep", "physical-50views-20261019", True), ("rejects", "physical-reject-20261019", True),
                                   ("original_angles", "physical-multiangle-20261019", False)):
            keep = [i for i, row in enumerate(validation) if row["source_dataset"] == source]
            if key == "sweep": keep += [i for i, row in enumerate(validation) if row["source_dataset"] == "physical-reject-20261019"]
            reports[key], scans[key] = scan_report([validation[i] for i in keep], scores[keep], [outcomes[i] for i in keep], fifty)
        originals = [i for i, r in enumerate(validation) if r["source_dataset"] == "physical-camera-20261018"]
        reports["original_frames"], _ = summarize([validation[i] for i in originals], scores[originals], val_x[originals], truth[originals], policy, references, labels)
        reports["historical"], _ = summarize(historical, hist_x @ coefficient.T + intercept, hist_x, hist_y, policy, references, labels)
        reports["all_camera_views"] = view_metrics
        return reports, scans, outcomes

    before, before_scans, before_views = evaluate(old_coefficient, old_intercept, old_refs, old_labels)
    from sklearn.linear_model import LogisticRegression
    candidates, best_key, chosen = [], None, None
    for weight in CAMERA_WEIGHTS:
        estimator = LogisticRegression(C=100, class_weight=classes, max_iter=3000, random_state=42)
        candidate_weights = weights.copy()
        candidate_weights[len(old_y):] *= weight/20
        estimator.fit(train_x, train_y, sample_weight=candidate_weights)
        coefficient, intercept = estimator.coef_.astype(np.float32), estimator.intercept_.astype(np.float32)
        np.testing.assert_allclose(val_x @ coefficient.T + intercept, estimator.decision_function(val_x), atol=2e-5, rtol=2e-5)
        after, scans, outcomes = evaluate(coefficient, intercept, train_x, train_y)
        failures = admission(before["sweep"], after["sweep"], before["historical"], after["historical"],
                             before["original_angles"], after["original_angles"], before["original_frames"], after["original_frames"])
        record = {"camera_weight_per_egg": weight, "admission_passed": not failures, "admission_failures": failures, "validation": after}
        candidates.append(record)
        key = (not failures, after["sweep"]["macro_correct_of_all_inputs"], after["sweep"]["correct_classified"],
               -after["sweep"]["wrong_classified"], after["sweep"]["raw_correct"])
        if best_key is None or key > best_key:
            best_key, chosen = key, (record, coefficient, intercept, scans, outcomes)
        print(json.dumps({"stage": "candidate fitted", "weight": weight, "admission_passed": not failures,
                          "scan_correct": after["sweep"]["correct_classified"], "scan_wrong": after["sweep"]["wrong_classified"]}), flush=True)
    best, coefficient, intercept, scans, outcomes = chosen
    validate_policy(policy, train_x, train_y)
    np.savez_compressed(RUN / "head.npz", coefficient=coefficient, intercept=intercept)
    np.savez_compressed(RUN / "training-references.npz", features=train_x, labels=train_y)
    write(RUN / "gate-policy.json", policy)
    write(RUN / "candidates.json", candidates)
    write(RUN / "validation-outcomes.json", {"before_scans": before_scans, "after_scans": scans, "views_before": before_views, "views_after": outcomes})
    write(RUN / "config.json", {"status": "EXPLORATORY_RETRAINED_THREE_CLASS_CAMERA_HEAD", "class_order": CLASSES,
          "dataset_manifest": str(manifest), "dataset_sha256": audit["manifest_sha256"], "encoder_onnx_sha256": protected[str(registry.parent/entry["model"]["path"])],
          "camera_weight_per_egg": best["camera_weight_per_egg"], "operational_use_authorized": False, "limitations": audit["limitations"]})
    report = {"scope": "CORRELATED_DEVELOPMENT_VALIDATION_ONLY", "dataset_rows": len(rows), "prior_90_views_included": 90,
              "age_1500_views_included": 1500, "reject_150_views_included": 150, "physical_training_eggs": 11,
              "camera_training_views": len(training), "training_counts": dict(Counter(CLASSES[int(y)] for y in train_y)),
              "before": before, "selected_candidate": best, "test_images_opened": 0, "fresh_independent_test_eggs": 0,
              "active_release_changed": False, "claim_99_percent_supported": False, "limitations": audit["limitations"]}
    write(RUN / "metrics.json", report)
    for path, digest in protected.items():
        if sha(Path(path)) != digest:
            raise ValueError("Protected dataset, baseline, or evaluator changed")
    artifacts = ("head.npz", "training-references.npz", "gate-policy.json", "config.json", "experiment-plan.json", "metrics.json",
                 "candidates.json", "development.npz", "validation-outcomes.json")
    write(RUN / "selection-lock.json", {"admission_passed": best["admission_passed"], "evaluator_sha256": sha(Path(__file__)),
          "artifacts": {name: sha(RUN/name) for name in artifacts}})
    print(json.dumps({"stage": "retraining complete", "run": str(RUN), "admission_passed": best["admission_passed"],
                      "admission_failures": best["admission_failures"], "test_images_opened": 0}), flush=True)
    return report


if __name__ == "__main__":
    run()
