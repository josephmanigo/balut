"""Deterministic abstention heuristics shared by evaluation and serving.

Passing these gates is not a probability or proof of correct classification.
The limits are frozen on development data, never on the historical test.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

CLASSES = ["DAY_16", "DAY_18", "REJECT"]
SUPPORTED_CLASS_ORDERS = [CLASSES, ["DAY_16", "DAY_18", "UNFERTILIZED"]]


def policy_classes(policy):
    classes = policy.get("class_order", CLASSES)
    if classes not in SUPPORTED_CLASS_ORDERS:
        raise ValueError("Unsupported selective class order")
    return classes


def validate_policy(policy, references, labels):
    classes = policy_classes(policy)
    if (policy.get("schema_version") != 1 or policy.get("review_required") is not False
            or policy.get("on_uncertain") != "RECAPTURE_REQUIRED"):
        raise ValueError("Unsupported automatic recapture policy")
    for key in ["minimum_margin", "minimum_training_cosine"]:
        if set(policy[key]) != set(classes):
            raise ValueError("Incomplete recapture thresholds")
        for value in policy[key].values():
            if value is None and key == "minimum_margin":
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
                raise ValueError("Invalid recapture threshold")
            if key == "minimum_margin" and value < 0 or key == "minimum_training_cosine" and not -1 <= value <= 1:
                raise ValueError("Recapture threshold outside valid range")
    quality = policy["quality"]
    for name in ["minimum_short_side", "minimum_grayscale_std", "minimum_edge_variance", "maximum_clipped_fraction"]:
        if isinstance(quality[name], bool) or not isinstance(quality[name], (int, float)) or not np.isfinite(quality[name]) or quality[name] <= 0:
            raise ValueError("Invalid image quality threshold")
    if quality["maximum_clipped_fraction"] > 1:
        raise ValueError("Invalid clipping fraction")
    if (references.ndim != 2 or len(references) == 0 or labels.shape != (len(references),)
            or not np.issubdtype(labels.dtype, np.integer) or set(labels.tolist()) != {0, 1, 2}
            or not np.isfinite(references).all() or not np.allclose(np.linalg.norm(references, axis=1), 1, atol=1e-4)):
        raise ValueError("Invalid training reference bank")


def image_quality(image, policy):
    """Measure native crop resolution and fixed-scale contrast/clipping/edges."""
    gray = np.asarray(image.convert("L").resize((224, 224), Image.Resampling.BILINEAR), dtype=np.float32)
    laplacian = -4 * gray[1:-1, 1:-1] + gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:]
    measured = {"shortSide": min(image.size), "grayscaleStd": float(gray.std()),
                "edgeVariance": float(laplacian.var()), "clippedFraction": float(((gray <= 3) | (gray >= 252)).mean())}
    limits = policy["quality"]
    reasons = []
    for invalid, reason in [
        (measured["shortSide"] < limits["minimum_short_side"], "IMAGE_TOO_SMALL"),
        (measured["grayscaleStd"] < limits["minimum_grayscale_std"], "LOW_CONTRAST"),
        (measured["edgeVariance"] < limits["minimum_edge_variance"], "IMAGE_TOO_BLURRY"),
        (measured["clippedFraction"] > limits["maximum_clipped_fraction"], "EXPOSURE_CLIPPED"),
    ]:
        if invalid:
            reasons.append(reason)
    return measured, reasons


def decide(scores, embedding, image, policy, references, labels):
    scores, embedding = np.asarray(scores), np.asarray(embedding)
    if (scores.shape != (3,) or embedding.shape != (references.shape[1],)
            or not np.isfinite(scores).all() or not np.isfinite(embedding).all()
            or not np.isclose(np.linalg.norm(embedding), 1, atol=1e-4)):
        raise RuntimeError("Invalid selective model output")
    winner = int(scores.argmax())
    label = policy_classes(policy)[winner]
    ordered = np.sort(scores)
    margin = float(ordered[-1] - ordered[-2])
    similarity = float((references[labels == winner] @ embedding).max())
    quality, reasons = image_quality(image, policy)
    threshold = policy["minimum_margin"][label]
    if threshold is None:
        reasons.append("INSUFFICIENT_VALIDATION_SUPPORT")
    elif margin <= 0 or margin < threshold:
        reasons.append("AMBIGUOUS_APPEARANCE")
    if similarity < policy["minimum_training_cosine"][label]:
        reasons.append("UNFAMILIAR_APPEARANCE")
    return {"sourcePrediction": None if reasons else label,
            "analysisOutcome": "RECAPTURE_REQUIRED" if reasons else "CLASSIFIED",
            "recaptureRequested": bool(reasons), "recaptureReasons": reasons, "reviewRequired": False,
            "qualityMeasurements": quality, "decisionMargin": margin, "nearestTrainingCosine": similarity,
            "scoresAreProbabilities": False}
