from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable


CLASSES = ("DAY_16_LIKE", "DAY_18_LIKE", "REJECT_SUSPECT")


@dataclass(frozen=True)
class SessionPrediction:
    session_id: str
    expected: str
    predicted: str
    confidence: float
    automatically_decided: bool


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def evaluate_selective_classification(rows: Iterable[SessionPrediction]) -> dict[str, object]:
    materialized = list(rows)
    seen = set()
    for row in materialized:
        if not row.session_id or row.session_id in seen:
            raise ValueError("session IDs must be present and unique")
        seen.add(row.session_id)
        if (row.expected not in CLASSES or row.predicted not in (*CLASSES, "REVIEW_RECAPTURE")
                or type(row.automatically_decided) is not bool
                or (row.automatically_decided and row.predicted not in CLASSES)
                or not math.isfinite(row.confidence) or not 0 <= row.confidence <= 1):
            raise ValueError(f"invalid prediction in session {row.session_id}")
    automatic = [row for row in materialized if row.automatically_decided]
    confusion = {expected: {predicted: 0 for predicted in CLASSES} for expected in CLASSES}
    for row in automatic:
        if row.expected not in CLASSES or row.predicted not in CLASSES:
            raise ValueError(f"unsupported class in session {row.session_id}")
        confusion[row.expected][row.predicted] += 1

    per_class: dict[str, dict[str, object]] = {}
    for label in CLASSES:
        true_positive = confusion[label][label]
        false_negative = sum(confusion[label][other] for other in CLASSES if other != label)
        false_positive = sum(confusion[other][label] for other in CLASSES if other != label)
        true_negative = len(automatic) - true_positive - false_negative - false_positive
        precision = _safe_div(true_positive, true_positive + false_positive)
        recall = _safe_div(true_positive, true_positive + false_negative)
        specificity = _safe_div(true_negative, true_negative + false_positive)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        total_support = sum(row.expected == label for row in materialized)
        decided_support = true_positive + false_negative
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "specificity": specificity,
            "f1": f1,
            "support": float(decided_support),
            "total_support": total_support,
            "abstained": total_support - decided_support,
            "coverage": _safe_div(decided_support, total_support),
            "end_to_end_recall": _safe_div(true_positive, total_support),
            "precision_95ci": wilson_interval(true_positive, true_positive + false_positive),
            "end_to_end_recall_95ci": wilson_interval(true_positive, total_support),
        }

    recalls_with_support = [values["recall"] for values in per_class.values() if values["support"] > 0]
    correct = sum(confusion[label][label] for label in CLASSES)
    return {
        "session_count": len(materialized),
        "automatic_count": len(automatic),
        "correct_count": correct,
        "incorrect_automatic_count": len(automatic) - correct,
        "abstained_count": len(materialized) - len(automatic),
        "coverage": _safe_div(len(automatic), len(materialized)),
        "selective_accuracy": _safe_div(correct, len(automatic)),
        "balanced_accuracy": _safe_div(sum(recalls_with_support), len(recalls_with_support)),
        "automatic_support_complete": all(values["support"] > 0 for values in per_class.values()),
        "end_to_end_balanced_accuracy": sum(values["end_to_end_recall"] for values in per_class.values()) / len(CLASSES),
        "correct_fraction_all_sessions": _safe_div(correct, len(materialized)),
        "coverage_95ci": wilson_interval(len(automatic), len(materialized)),
        "selective_accuracy_95ci": wilson_interval(correct, len(automatic)),
        "confidence_interval_assumption": "Independent trials; repeated sessions of one egg require clustered analysis",
        "confusion_matrix": confusion,
        "per_class": per_class,
    }


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if (type(successes) is not int or type(total) is not int or not 0 <= successes <= total
            or not math.isfinite(z) or z <= 0):
        raise ValueError("invalid binomial counts or interval z-score")
    if total == 0:
        return (0.0, 1.0)
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    spread = z * math.sqrt((proportion * (1 - proportion) + z * z / (4 * total)) / total) / denominator
    return (max(0.0, center - spread), min(1.0, center + spread))


def compare_float_int8(
    float_predictions: Iterable[tuple[str, str]],
    int8_predictions: Iterable[tuple[str, str]],
) -> dict[str, float | int]:
    float_rows, int8_rows = list(float_predictions), list(int8_predictions)
    float_map, int8_map = dict(float_rows), dict(int8_rows)
    if len(float_map) != len(float_rows) or len(int8_map) != len(int8_rows):
        raise ValueError("duplicate session IDs invalidate parity evaluation")
    shared = sorted(set(float_map) & set(int8_map))
    agreements = sum(float_map[key] == int8_map[key] for key in shared)
    return {
        "shared_session_count": len(shared),
        "prediction_agreement": _safe_div(agreements, len(shared)),
        "missing_from_float": len(set(int8_map) - set(float_map)),
        "missing_from_int8": len(set(float_map) - set(int8_map)),
    }
