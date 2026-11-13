"""Compare two preregistered edge floors on development validation only."""
from collections import Counter, defaultdict
from copy import deepcopy
import json

import numpy as np

from balut_ml.scientific_metrics import classification_metrics
from scripts.capture_emeet_egg import sha, write


def summarize(rows, outcomes, scores, classes):
    raw = np.zeros((3, 3), dtype=int)
    gated = np.zeros((3, 4), dtype=int)
    groups = defaultdict(Counter)
    reasons = defaultdict(Counter)
    correct_reasons = defaultdict(Counter)
    for outcome in outcomes:
        index = outcome["row_index"]
        row = rows[index]
        if row["partition"] != "validation" or row["source_label"] != outcome["truth"]:
            raise ValueError("Calibration may score only matching validation rows")
        label = outcome["truth"]
        truth = classes.index(label)
        prediction = outcome["sourcePrediction"]
        raw_class = int(scores[index].argmax())
        raw[truth, raw_class] += 1
        gated[truth, classes.index(prediction) if prediction else 3] += 1
        group_id = row.get("egg_id") or row["duplicate_group"]
        group = groups[group_id]
        group.update({"views": 1, "raw_correct": int(raw_class == truth),
                      "correct_accepted": int(prediction == label),
                      "wrong_accepted": int(prediction is not None and prediction != label),
                      "recaptures": int(prediction is None)})
        reasons[label].update(outcome["recaptureReasons"])
        if raw_class == truth:
            correct_reasons[label].update(outcome["recaptureReasons"])
    if len(outcomes) != sum(row["partition"] == "validation" for row in rows):
        raise ValueError("Validation analysis must include every validation row")
    metrics = classification_metrics(raw, gated)
    per_class = {}
    for i, label in enumerate(classes):
        total = int(gated[i].sum())
        accepted = int(gated[i, :3].sum())
        correct = int(gated[i, i])
        predicted = int(gated[:, i].sum())
        per_class[label] = {"views": total, "raw": metrics["per_class"][i], "correct_accepted": correct,
                            "accepted": accepted, "wrong_accepted": accepted - correct,
                            "recaptures": total - accepted, "coverage": accepted / total,
                            "accuracy_among_accepted": correct / accepted if accepted else None,
                            "correct_over_all": correct / total,
                            "gated_precision": correct / predicted if predicted else 0.,
                            "gated_recall": correct / total,
                            "gated_f1": 2 * correct / (total + predicted),
                            "recapture_reasons": reasons[label],
                            "reasons_on_raw_correct_views": correct_reasons[label]}
    return {"metrics": metrics, "per_class": per_class, "groups": dict(groups),
            "class_balanced_correct_over_all": float(np.mean([m["correct_over_all"] for m in per_class.values()]))}


def compare_rotation_floor(dataset, run, policy, original_outcomes, evaluate, rows, scores, classes):
    plan_path = run / "edge-calibration-plan.json"
    plan = json.loads(plan_path.read_text())
    original_floor = policy["quality"]["minimum_edge_variance"]
    candidate_floor = plan["candidate_floor"]
    if (plan["study"] != dataset.name or plan["collection_plan_sha256"] != sha(dataset / "collection-plan.json")
            or plan["original_floor"] != original_floor or not 15 <= candidate_floor <= original_floor):
        raise ValueError("Edge comparison differs from its registered study or bounds")
    alternative = deepcopy(policy)
    alternative["quality"]["minimum_edge_variance"] = candidate_floor
    alternative_outcomes = evaluate(alternative)
    baseline = summarize(rows, original_outcomes, scores, classes)
    candidate = summarize(rows, alternative_outcomes, scores, classes)
    age_ids = {r["egg_id"]: r["source_label"] for r in rows if r.get("physical_egg_id") and r["partition"] == "validation"}
    gains = {egg: candidate["groups"][egg]["correct_accepted"] - baseline["groups"][egg]["correct_accepted"] for egg in age_ids}
    wrong_increase = [g for g, m in candidate["groups"].items() if m["wrong_accepted"] > baseline["groups"][g]["wrong_accepted"]]
    use_candidate = (candidate["class_balanced_correct_over_all"] > baseline["class_balanced_correct_over_all"]
                     and candidate["per_class"]["DAY_18"]["correct_over_all"] > baseline["per_class"]["DAY_18"]["correct_over_all"]
                     and sum(n > 0 for n in gains.values()) >= 2 and any(n > 0 and age_ids[e] == "DAY_18" for e, n in gains.items())
                     and min(gains.values()) >= 0 and not wrong_increase)
    selected, outcomes = (alternative, alternative_outcomes) if use_candidate else (policy, original_outcomes)
    comparison = {"registered_plan_sha256": sha(plan_path), "selected_edge_floor": selected["quality"]["minimum_edge_variance"],
                  "changed": bool(use_candidate), "original_floor": original_floor, "candidate_floor": candidate_floor,
                  "per_validation_age_egg_correct_gain": gains, "groups_with_increased_wrong_accepts": wrong_increase,
                  "baseline": baseline, "candidate": candidate, "test_images_opened": 0,
                  "scope": "View-level development calibration. The same four age validation eggs selected the checkpoint and gate. Correlated views do not estimate field accuracy."}
    folder = run / "calibration"
    write(folder / "edge-comparison.json", comparison)
    write(folder / "original-gate-policy.json", policy)
    write(folder / "original-validation-outcomes.json", original_outcomes)
    write(folder / "candidate-edge-policy.json", alternative)
    write(folder / "candidate-edge-validation-outcomes.json", alternative_outcomes)
    return selected, outcomes
