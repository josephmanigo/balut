"""Adapt a frozen source-label classifier with a training-only local collection."""
from __future__ import annotations

import argparse
import copy
import io
import json
import os
import sys
from collections import Counter
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import numpy as np
from PIL import Image, ImageOps

from .local_photo_data import ROOT, frame_image, load_local_rows
from .public_data import sha256

sys.path.insert(0, str(ROOT / "apps/edge_api"))
from balut_api.selective_gate import CLASSES, decide, validate_policy


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def validate_disjoint(local_rows, old_rows):
    identities = {r[k] for r in old_rows for k in ("source_sha256", "pixel_sha256")}
    if any(r[k] in identities for r in local_rows for k in ("source_sha256", "pixel_sha256", "original_sha256")):
        raise ValueError("Incoming collection overlaps an existing dataset")
    if any(r["partition"] != "train" for r in local_rows):
        raise ValueError("Local collection cannot be used as independent validation or test")


def summarize(rows, scores, features, truth, policy, references, labels):
    from .benchmark_public import metrics_for
    outcomes = []
    for row, score, feature, target in zip(rows, scores, features, truth, strict=True):
        if sha256(Path(row["image_path"])) != row["source_sha256"]:
            raise ValueError("Evaluation image changed")
        with Image.open(row["image_path"]) as original:
            result = decide(score, feature, ImageOps.exif_transpose(original).convert("RGB"), policy, references, labels)
        outcomes.append({"image_path": row["image_path"], "source_label": CLASSES[int(target)], **result})
    accepted = [r for r in outcomes if r["sourcePrediction"] is not None]
    correct = sum(r["sourcePrediction"] == r["source_label"] for r in accepted)
    total = len(outcomes)
    raw = metrics_for(truth, scores.argmax(1), CLASSES)
    raw["macro_f1"] = raw["per_class"]["macro avg"]["f1-score"]
    return {"raw": raw,
            "selective": {"images": total, "classified": len(accepted), "correct_classified": correct,
                          "wrong_classified": len(accepted) - correct, "recapture_requested": total - len(accepted),
                          "coverage": len(accepted) / total, "accepted_accuracy": correct / len(accepted) if accepted else None,
                          "correct_of_all_inputs": correct / total,
                          "recapture_reasons": dict(Counter(reason for row in outcomes for reason in row["recaptureReasons"])),
                          "by_true_class": {label: {"images": sum(r["source_label"] == label for r in outcomes),
                                                     "classified": sum(r["source_label"] == label for r in accepted),
                                                     "correct_classified": sum(r["source_label"] == label == r["sourcePrediction"] for r in accepted)} for label in CLASSES}}}, outcomes


def train(manifest, output):
    if output.exists():
        raise FileExistsError("Preserve completed experiments; choose a fresh output")
    local_rows, audit = load_local_rows(manifest)
    baseline = ROOT / "ml/runs/selective-v2"
    old_manifest = ROOT / "ml/runs/three-class-v1/manifest.jsonl"
    config = json.loads((baseline / "config.json").read_text())
    lock = json.loads((baseline / "selection-lock.json").read_text())
    old_rows = [json.loads(line) for line in old_manifest.read_text().splitlines()]
    if sha256(old_manifest) != config["manifest_sha256"]:
        raise ValueError("Historical manifest changed")
    validate_disjoint(local_rows, old_rows)
    for name, key in (("selected-development.npz", "development_data_sha256"), ("gate-policy.json", "gate_policy_sha256")):
        if sha256(baseline / name) != lock[key]:
            raise ValueError("Baseline development data or policy changed")
    output.mkdir()
    specs = [{"C": c, "local_weight": weight} for c in (1.0, 10.0, 30.0, 100.0) for weight in (0.25, 1.0)]
    plan = {"status": "EXPLORATORY_USER_LABEL_ADAPTATION", "baseline": str(baseline),
            "baseline_checkpoint_sha256": sha256(baseline / "best.pt"), "baseline_onnx_sha256": sha256(baseline / "best.onnx"),
            "local_manifest": str(manifest.resolve()), "local_manifest_sha256": sha256(manifest),
            "historical_manifest_sha256": sha256(old_manifest), "candidate_limit": len(specs), "grid": specs,
            "frozen_backbones": config["backbones"], "seed": 42,
            "selection": "Historical validation macro F1, balanced accuracy, accuracy; first candidate breaks ties",
            "local_partition": "Entire incoming collection is training-only; retain existing quality gates and fit only eligible framed photos",
            "local_before_after": "Diagnostic source-label agreement on training collection, not independent accuracy",
            "test_policy": "Do not load historical test feature cache until candidate and gate hashes are locked; one evaluation only",
            "activation": "No activation: no independent local eggs/batches with verified ages are available",
            "limitations": audit["limitations"] + config["limitations"]}
    write_json(output / "experiment-plan.json", plan)

    import torch
    from sklearn.linear_model import LogisticRegression
    from .benchmark_public import metrics_for, selection_key
    from .feature_models import image_transform, load_classifier
    from .selective_search import learn_margin_thresholds

    torch.set_num_threads(4)
    torch.manual_seed(42)
    torch.use_deterministic_algorithms(True)
    model, _ = load_classifier(baseline / "best.pt")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    transform = image_transform()
    feature_parts, score_parts = [], []
    with torch.inference_mode():
        for start in range(0, len(local_rows), 8):
            tensors = []
            for row in local_rows[start:start + 8]:
                with Image.open(row["image_path"]) as image:
                    tensors.append(transform(ImageOps.exif_transpose(image).convert("RGB")))
            scores, features = model(torch.stack(tensors).to(device))
            feature_parts.append(features.cpu().numpy())
            score_parts.append(scores.cpu().numpy())
            if start % 32 == 0:
                print(json.dumps({"stage": "local_features", "completed": min(start + 8, len(local_rows)), "total": len(local_rows), "device": str(device)}), flush=True)
    features = np.concatenate(feature_parts)
    before_scores = np.concatenate(score_parts)
    truth = np.array([CLASSES.index(r["source_label"]) for r in local_rows])
    eligible = np.array([r["training_eligible"] for r in local_rows], dtype=bool)
    if set(truth[eligible].tolist()) != {0, 1}:
        raise ValueError("Both local age labels need quality-eligible training examples")
    np.savez_compressed(output / "local-features.npz", features=features, truth=truth, baseline_scores=before_scores, eligible=eligible)
    model.cpu()
    if device.type == "cuda":
        torch.cuda.empty_cache()

    with np.load(baseline / "selected-development.npz", allow_pickle=False) as bank:
        old_x, old_y = bank["train_features"].copy(), bank["train_truth"].copy()
        val_x, val_y, val_indexes = bank["validation_features"].copy(), bank["truth"].copy(), bank["indexes"].copy()
        train_indexes = bank["train_indexes"].copy()
    assert all(old_rows[int(i)]["partition"] == "train" for i in train_indexes)
    assert all(old_rows[int(i)]["partition"] == "validation" for i in val_indexes)
    assert np.array_equal(old_y, [CLASSES.index(old_rows[int(i)]["source_label"]) for i in train_indexes])
    assert np.array_equal(val_y, [CLASSES.index(old_rows[int(i)]["source_label"]) for i in val_indexes])
    training_x = np.concatenate([old_x, features[eligible]])
    training_y = np.concatenate([old_y, truth[eligible]])
    best, estimator = None, None
    for spec in specs:
        candidate = LogisticRegression(C=spec["C"], class_weight="balanced", max_iter=3000, random_state=42)
        weights = np.concatenate([np.ones(len(old_y)), np.full(int(eligible.sum()), spec["local_weight"])])
        candidate.fit(training_x, training_y, sample_weight=weights)
        record = {**spec, "validation": metrics_for(val_y, candidate.predict(val_x), CLASSES)}
        with (output / "candidates.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        if best is None or selection_key(record["validation"]) > selection_key(best["validation"]):
            best, estimator = record, candidate
        print(json.dumps({"stage": "candidate", "C": spec["C"], "local_weight": spec["local_weight"], "validation_macro_f1": record["validation"]["macro_f1"]}), flush=True)
    coefficient, intercept = estimator.coef_.astype(np.float32), estimator.intercept_.astype(np.float32)
    val_scores = val_x @ coefficient.T + intercept
    assert np.array_equal(val_scores.argmax(1), estimator.predict(val_x))
    policy = copy.deepcopy(json.loads((baseline / "gate-policy.json").read_text()))
    policy["minimum_margin"], policy["validation_margin_gate_counts"] = learn_margin_thresholds(val_scores, val_y)
    policy["minimum_training_cosine"] = {label: float(np.quantile((val_x[val_y == i] @ training_x[training_y == i].T).max(1), .01)) for i, label in enumerate(CLASSES)}
    policy["calibration_scope"] = "Historical validation heuristic only; no independent local-age accuracy evidence"
    validate_policy(policy, training_x, training_y)
    np.savez_compressed(output / "head.npz", coefficient=coefficient, intercept=intercept)
    np.savez_compressed(output / "training-references.npz", features=training_x, labels=training_y)
    write_json(output / "gate-policy.json", policy)
    selection = {**best, "experiment_plan_sha256": sha256(output / "experiment-plan.json"),
                 "head_sha256": sha256(output / "head.npz"), "gate_policy_sha256": sha256(output / "gate-policy.json"),
                 "references_sha256": sha256(output / "training-references.npz"), "local_feature_sha256": sha256(output / "local-features.npz")}
    write_json(output / "selection-lock.json", selection)
    candidate_config = {"status": "EXPLORATORY_USER_LABEL_ADAPTATION", "operational_use_authorized": False,
                        "class_order": CLASSES, "encoder_onnx": str((baseline / "best.onnx").resolve()),
                        "encoder_onnx_sha256": plan["baseline_onnx_sha256"], "selection_lock_sha256": sha256(output / "selection-lock.json"),
                        "input_contract": "RGB framed/cropped egg JPEG, resize224, ImageNet normalization; encoder output named embedding",
                        "local_framing": audit["preprocessing"], "requires_existing_encoder_file": True,
                        "limitations": plan["limitations"]}
    write_json(output / "config.json", candidate_config)
    print("Selection and gates locked. Evaluating historical holdout once.", flush=True)

    # This test cache is accessed only after the chosen head and gates are frozen.
    with np.load(baseline / "selected-test.npz", allow_pickle=False) as bank:
        test_x, test_y, test_indexes = bank["features"], bank["truth"], bank["indexes"]
        assert all(old_rows[int(i)]["partition"] == "test" for i in test_indexes)
        assert np.array_equal(test_y, [CLASSES.index(old_rows[int(i)]["source_label"]) for i in test_indexes])
        historical, outcomes = summarize([old_rows[int(i)] for i in test_indexes], test_x @ coefficient.T + intercept, test_x, test_y, policy, training_x, training_y)
    write_json(output / "historical-test-outcomes.json", outcomes)
    baseline_policy = json.loads((baseline / "gate-policy.json").read_text())
    local_before, before_outcomes = summarize(local_rows, before_scores, features, truth, baseline_policy, old_x, old_y)
    local_after, after_outcomes = summarize(local_rows, features @ coefficient.T + intercept, features, truth, policy, training_x, training_y)
    write_json(output / "local-before-outcomes.json", before_outcomes)
    write_json(output / "local-after-training-outcomes.json", after_outcomes)
    baseline_metrics = json.loads((baseline / "metrics.json").read_text())
    report = {"training_counts": {label: int((training_y == i).sum()) for i, label in enumerate(CLASSES)},
              "local_imported": len(local_rows), "local_used_for_training": int(eligible.sum()), "local_quality_excluded": int((~eligible).sum()),
              "historical_validation": best["validation"], "historical_test": historical,
              "retained_historical_test": {"raw": baseline_metrics["test_raw"], "selective": baseline_metrics["test_selective"]},
              "local_before_training": local_before, "local_after_training_resubstitution": local_after,
              "local_after_training_is_independent_accuracy": False,
              "independent_local_test_eggs": 0, "activated": False,
              "decision": "Keep retained release. Candidate requires verified egg/batch-disjoint local evaluation before activation.",
              "selection_lock_sha256": sha256(output / "selection-lock.json"), "limitations": plan["limitations"]}
    write_json(output / "metrics.json", report)
    # GPU drift is diagnostic. Export parity must compare the same CPU runtime.
    parity_indexes = np.linspace(0, len(local_rows) - 1, 12, dtype=int)
    session = encoder_session(candidate_config)
    max_score_error, max_embedding_error, same = 0.0, 0.0, True
    for index in parity_indexes:
        with Image.open(local_rows[int(index)]["image_path"]) as image:
            tensor = transform(image.convert("RGB")).unsqueeze(0).numpy()
        _, portable_features = session.run(None, {"images": tensor})
        portable_scores = portable_features @ coefficient.T + intercept
        expected = features[index] @ coefficient.T + intercept
        max_score_error = max(max_score_error, float(np.abs(portable_scores[0] - expected).max()))
        max_embedding_error = max(max_embedding_error, float(np.abs(portable_features[0] - features[index]).max()))
        same &= int(portable_scores.argmax(1)[0]) == int(expected.argmax())
    parity = {"passed": max_score_error < 1e-3 and max_embedding_error < 1e-4 and same,
              "images": len(parity_indexes), "maximum_score_error": max_score_error,
              "maximum_embedding_error": max_embedding_error, "raw_predictions_identical": same}
    write_json(output / "gpu-comparison.json", parity)
    parity = verify_candidate(output)
    print(json.dumps({"historical_test": historical["selective"], "local_before": local_before["selective"],
                      "local_after_training_only": local_after["selective"], "local_training_images": int(eligible.sum()),
                      "parity": parity, "activated": False}, indent=2), flush=True)


def encoder_session(config):
    import onnxruntime as ort
    if sha256(Path(config["encoder_onnx"])) != config["encoder_onnx_sha256"]:
        raise ValueError("Pinned encoder changed")
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    options.inter_op_num_threads = 1
    return ort.InferenceSession(config["encoder_onnx"], sess_options=options, providers=["CPUExecutionProvider"])


def prepare_input(image):
    array = np.asarray(image.resize((224, 224), Image.Resampling.BILINEAR), dtype=np.float32) / 255
    return ((array - np.array([.485, .456, .406], dtype=np.float32)) / np.array([.229, .224, .225], dtype=np.float32)).transpose(2, 0, 1)[None]


def verify_candidate(run):
    """Verify the frozen candidate on CPU without fitting or reopening test data."""
    import torch
    from .feature_models import image_transform, load_classifier
    torch.set_num_threads(4)
    config = json.loads((run / "config.json").read_text())
    plan = json.loads((run / "experiment-plan.json").read_text())
    selection = json.loads((run / "selection-lock.json").read_text())
    if sha256(run / "selection-lock.json") != config["selection_lock_sha256"]:
        raise ValueError("Candidate lock changed")
    for name, key in (("head.npz", "head_sha256"), ("gate-policy.json", "gate_policy_sha256"), ("training-references.npz", "references_sha256")):
        if sha256(run / name) != selection[key]:
            raise ValueError("Candidate artifact changed")
    checkpoint = Path(plan["baseline"]) / "best.pt"
    if sha256(checkpoint) != plan["baseline_checkpoint_sha256"]:
        raise ValueError("Pinned checkpoint changed")
    rows, _ = load_local_rows(Path(plan["local_manifest"]))
    model, _ = load_classifier(checkpoint)
    session = encoder_session(config)
    transform = image_transform()
    policy = json.loads((run / "gate-policy.json").read_text())
    with np.load(run / "head.npz", allow_pickle=False) as head:
        coefficient, intercept = head["coefficient"], head["intercept"]
    with np.load(run / "training-references.npz", allow_pickle=False) as bank:
        references, labels = bank["features"], bank["labels"]
    max_score, max_embedding, same_raw, same_gates = 0.0, 0.0, True, True
    indexes = np.linspace(0, len(rows) - 1, 12, dtype=int)
    with torch.inference_mode():
        for index in indexes:
            with Image.open(rows[int(index)]["image_path"]) as original:
                image = ImageOps.exif_transpose(original).convert("RGB")
            _, cpu = model(transform(image).unsqueeze(0))
            cpu = cpu.numpy()
            _, portable = session.run(None, {"images": prepare_input(image)})
            a, b = cpu @ coefficient.T + intercept, portable @ coefficient.T + intercept
            max_score = max(max_score, float(np.abs(a - b).max()))
            max_embedding = max(max_embedding, float(np.abs(cpu - portable).max()))
            same_raw &= int(a.argmax(1)[0]) == int(b.argmax(1)[0])
            x = decide(a[0], cpu[0], image, policy, references, labels)
            y = decide(b[0], portable[0], image, policy, references, labels)
            same_gates &= (x["sourcePrediction"], x["recaptureReasons"]) == (y["sourcePrediction"], y["recaptureReasons"])
    report = {"passed": max_score < 1e-3 and max_embedding < 1e-4 and same_raw and same_gates,
              "images": len(indexes), "comparison": "CPU PyTorch versus CPU ONNX with compact trained head",
              "maximum_score_error": max_score, "maximum_embedding_error": max_embedding,
              "raw_predictions_identical": same_raw, "selective_decisions_identical": same_gates,
              "head_sha256": selection["head_sha256"], "selection_lock_sha256": config["selection_lock_sha256"]}
    write_json(run / "compact-inference-parity.json", report)
    if not report["passed"]:
        raise RuntimeError("Compact candidate failed CPU inference parity")
    return report


def predict(run, image_path, apply_framing=False):
    config = json.loads((run / "config.json").read_text())
    if sha256(run / "selection-lock.json") != config["selection_lock_sha256"]:
        raise ValueError("Candidate selection lock changed")
    lock = json.loads((run / "selection-lock.json").read_text())
    for name, key in (("head.npz", "head_sha256"), ("gate-policy.json", "gate_policy_sha256"), ("training-references.npz", "references_sha256")):
        if sha256(run / name) != lock[key]:
            raise ValueError("Candidate artifact changed")
    with Image.open(image_path) as original:
        image = frame_image(original)[0] if apply_framing else ImageOps.exif_transpose(original).convert("RGB")
    if apply_framing:
        encoded = io.BytesIO()
        image.save(encoded, format="JPEG", quality=95, subsampling=0)
        encoded.seek(0)
        with Image.open(encoded) as stored:
            image = stored.convert("RGB")
    tensor = prepare_input(image)
    _, features = encoder_session(config).run(None, {"images": tensor})
    with np.load(run / "head.npz", allow_pickle=False) as head:
        scores = features @ head["coefficient"].T + head["intercept"]
    policy = json.loads((run / "gate-policy.json").read_text())
    with np.load(run / "training-references.npz", allow_pickle=False) as references:
        validate_policy(policy, references["features"], references["labels"])
        result = decide(scores[0], features[0], image, policy, references["features"], references["labels"])
    return {"status": config["status"], "operational_use_authorized": False, "scores": scores[0].tolist(), **result}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    fitting = subparsers.add_parser("train")
    fitting.add_argument("manifest", type=Path)
    fitting.add_argument("output", type=Path)
    prediction = subparsers.add_parser("predict")
    prediction.add_argument("run", type=Path)
    prediction.add_argument("image", type=Path)
    prediction.add_argument("--frame-photo", action="store_true")
    verification = subparsers.add_parser("verify")
    verification.add_argument("run", type=Path)
    args = parser.parse_args()
    if args.command == "train":
        train(args.manifest, args.output)
    elif args.command == "verify":
        print(json.dumps(verify_candidate(args.run), indent=2))
    else:
        print(json.dumps(predict(args.run, args.image, args.frame_photo), indent=2))
