"""Count-based classification metrics and strict repeatability measurements."""
import numpy as np


def classification_metrics(raw, selective):
    raw, selective = np.asarray(raw), np.asarray(selective)
    if raw.shape != (3, 3) or selective.shape != (3, 4):
        raise ValueError("Expected three raw classes and a separate recapture column")
    if not np.isfinite(raw).all() or not np.isfinite(selective).all() or (raw < 0).any() or (selective < 0).any():
        raise ValueError("Counts must be finite and nonnegative")
    if not np.equal(raw, np.floor(raw)).all() or not np.equal(selective, np.floor(selective)).all():
        raise ValueError("Counts must be integers")
    if not np.array_equal(raw.sum(1), selective.sum(1)) or raw.sum() == 0:
        raise ValueError("Raw and gated populations must agree and be nonempty")
    total = int(raw.sum()); support = raw.sum(1); rows = []
    for label in range(3):
        tp = int(raw[label, label]); fp = int(raw[:, label].sum()) - tp; fn = int(support[label]) - tp
        rows.append({"class_index": label, "support": int(support[label]), "TP": tp, "FP": fp, "FN": fn, "TN": total - tp - fp - fn,
                     "precision": tp / (tp + fp) if tp + fp else 0., "recall": tp / (tp + fn) if tp + fn else 0.,
                     "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.})
    correct = int(np.trace(selective[:, :3])); accepted = int(selective[:, :3].sum())
    return {"evaluated": total, "raw_correct": int(np.trace(raw)), "raw_accuracy": float(np.trace(raw) / total),
            "balanced_accuracy": float(np.mean([r["recall"] for r in rows])), "macro_precision": float(np.mean([r["precision"] for r in rows])),
            "macro_recall": float(np.mean([r["recall"] for r in rows])), "macro_f1": float(np.mean([r["f1"] for r in rows])),
            "weighted_f1": float(sum(r["f1"] * r["support"] for r in rows) / total), "per_class": rows,
            "accepted": accepted, "correct_accepted": correct, "wrong_accepted": accepted - correct,
            "accepted_accuracy": correct / accepted if accepted else None, "coverage": accepted / total,
            "recaptures": total - accepted, "recapture_rate": (total - accepted) / total, "correct_over_all": correct / total,
            "raw_confusion_matrix": raw.astype(int).tolist(), "selective_confusion_matrix": selective.astype(int).tolist(),
            "zero_denominator_rule": "Per-class precision/recall/F1=0; accepted accuracy=null when no accepted predictions",
            "all_classes_represented": bool((support > 0).all())}


def cluster_intervals(records, classes, repeats=5000, seed=42):
    """Resample complete eggs/source families; never count each angle independently."""
    groups = {}
    for row in records:
        key = ("egg:" + row["physical_egg_id"]) if row.get("physical_egg_id") else ("source:" + row["duplicate_group"])
        raw, gated = groups.setdefault(key, (np.zeros((3, 3), dtype=int), np.zeros((3, 4), dtype=int)))
        truth = classes.index(row["truth"])
        raw[truth, classes.index(row["raw_prediction"])] += 1
        gated[truth, classes.index(row["sourcePrediction"]) if row["sourcePrediction"] else 3] += 1
    if len(groups) < 2:
        raise ValueError("At least two independent recorded groups are needed")
    raw = np.stack([v[0] for v in groups.values()]); gated = np.stack([v[1] for v in groups.values()])
    keys = ["raw_accuracy", "balanced_accuracy", "macro_f1", "weighted_f1", "accepted_accuracy", "coverage", "recapture_rate", "correct_over_all"]
    samples = {key: [] for key in keys}; missing_class = 0
    per_class_samples = [{key: [] for key in ("precision", "recall", "f1")} for _ in classes]
    rng = np.random.default_rng(seed)
    for _ in range(repeats):
        selected = rng.integers(len(groups), size=len(groups))
        value = classification_metrics(raw[selected].sum(0), gated[selected].sum(0))
        missing_class += not value["all_classes_represented"]
        for key in keys:
            if value[key] is not None:
                samples[key].append(value[key])
        for label, result in enumerate(value["per_class"]):
            for key in per_class_samples[label]:
                per_class_samples[label][key].append(result[key])
    return {"method": "Percentile bootstrap resampling complete known egg/source-family clusters", "confidence": .95,
            "resamples": repeats, "seed": seed, "clusters": len(groups), "known_physical_eggs": sum(k.startswith("egg:") for k in groups),
            "replicates_missing_a_class": missing_class,
            "intervals": {key: {"lower": float(np.quantile(values, .025)), "upper": float(np.quantile(values, .975))} for key, values in samples.items() if values},
            "per_class_intervals": [{"class": name, **{key: {"lower": float(np.quantile(values, .025)), "upper": float(np.quantile(values, .975))}
                                      for key, values in sample.items()}} for name, sample in zip(classes, per_class_samples, strict=True)],
            "limitations": "Conditional on recorded groups and historical sampling. Unknown public egg/batch identities and prior test inspection are not repaired by this interval."}


def repeatability(attempts, expected_repeats):
    valid = [a for a in attempts if a.get("result") is not None and a.get("score_vector") is not None]
    if not valid:
        return {"attempts": len(attempts), "valid": 0, "failures": len(attempts), "class_agreement": None,
                "decision_agreement": None, "maximum_score_difference": None, "strict_zero_gap_passed": False}
    vectors = np.asarray([a["score_vector"] for a in valid], dtype=np.float64)
    if vectors.ndim != 2 or vectors.shape[1] != 9 or not np.isfinite(vectors).all():
        raise ValueError("Expected all three full-precision class scores for each of three views")
    # Range over every pair catches changes between non-reference repeats too.
    gap = float(np.max(vectors.max(0) - vectors.min(0)))
    predictions = [a["result"]["sourcePrediction"] for a in valid]
    decisions = [(a["result"]["analysisOutcome"], a["result"]["recaptureRequested"]) for a in valid]
    class_agreement = max(predictions.count(p) for p in set(predictions)) / len(predictions)
    decision_agreement = max(decisions.count(p) for p in set(decisions)) / len(decisions)
    passed = len(attempts) == len(valid) == expected_repeats and expected_repeats >= 2 and class_agreement == decision_agreement == 1. and gap == 0.
    return {"attempts": len(attempts), "valid": len(valid), "failures": len(attempts) - len(valid), "class_agreement": class_agreement,
            "decision_agreement": decision_agreement, "maximum_score_difference": gap, "strict_zero_gap_passed": passed}
