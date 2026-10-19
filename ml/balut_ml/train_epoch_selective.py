"""Select epoch checkpoints using validation classification and recapture coverage."""
import copy
import json
import os
from pathlib import Path
import time

import numpy as np
from .train_epoch_head import ROOT, PARENT, DATA, CLASSES, sha, write, metrics, groups_report
from .train_unfertilized import fit_weights

RUN = ROOT / "ml/runs/retained-epochs-selective-reject-20261019"


def main():
    if RUN.exists():
        raise FileExistsError("Preserve earlier epoch experiments")
    parent_lock = json.loads((PARENT / "selection-lock.json").read_text())
    assert all(sha(PARENT / name) == digest for name, digest in parent_lock["artifacts"].items())
    rows = [json.loads(line) for line in (DATA / "manifest.jsonl").read_text().splitlines()]
    development = [row for row in rows if row["partition"] != "test"]
    with np.load(PARENT / "development.npz", allow_pickle=False) as bank:
        np.testing.assert_array_equal(bank["source_sha256"], [row["source_sha256"] for row in development])
        features = bank["features"].astype(np.float32)
    training_rows = [row for row in development if row["partition"] == "train"]
    validation_rows = [row for row in development if row["partition"] == "validation"]
    train_mask = np.array([row["partition"] == "train" for row in development])
    labels = np.array([CLASSES.index(row["training_label"]) for row in development])
    x, vx, y, vy = features[train_mask], features[~train_mask], labels[train_mask], labels[~train_mask]
    assert len(x) == 2256 and len(vx) == 814
    provenance = json.loads((PARENT / "validation-inputs.json").read_text())
    inputs = {item["source_sha256"]: item for item in provenance}
    from PIL import Image
    from balut_api.selective_gate import image_quality, validate_policy, decide
    quality = json.loads((PARENT / "gate-policy.json").read_text())["quality"]
    quality_reasons = []
    for row in validation_rows:
        item = inputs[row["source_sha256"]]
        assert sha(Path(item["path"])) == item["serving_jpeg_sha256"]
        with Image.open(item["path"]) as image:
            quality_reasons.append(image_quality(image, {"quality": quality})[1])
    RUN.mkdir()
    protected = {str(path.relative_to(ROOT)): sha(path) for path in
                 [Path(__file__), ROOT / "ml/balut_ml/train_epoch_head.py", DATA / "manifest.jsonl", PARENT / "head.npz", PARENT / "development.npz"]}
    write(RUN / "experiment-plan.json", {"epochs_maximum": 100, "patience": 20, "seed": 42,
          "batch_size": 128, "learning_rate": .03, "minimum_learning_rate": .0003, "weight_decay": .001, "input_dropout": .1,
          "class_order": CLASSES, "training": "Same fixed weighted minibatch head-training protocol as first epoch run; encoder frozen",
          "selection": "Admissible checkpoints first; then mean correct-over-all over five validation groups, minimum camera-age correct-over-all, raw mean group recall, macro F1, lower validation loss",
          "admission": "No decrease in either camera age accepted-correct count (226/263), each full-class accepted-correct count (235/267/159), or total coverage versus active model; raw age-camera correct count must exceed 525/540; no additional accepted validation errors",
          "calibration": "Each epoch uses unchanged quality/cosine definitions and margins above its own validation mistakes. Validation gates are development-calibrated, not independent accuracy.",
          "historical_test_policy": "Previously inspected 649-image set remains closed during training/selection; one later locked regression comparison, not independent field accuracy",
          "protected_files": protected, "first_raw_selection_run": "retained-epochs-reject-20261019",
          "label_scope": "Reject is an operator-requested output name for source Unfertilized examples; no vendor rejects or general defect validation"})
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    import torch
    from torch import nn
    torch.manual_seed(42)
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = nn.Sequential(nn.Dropout(.1), nn.Linear(1664, 3)).to(device)
    tx, tvx, ty, tw = [torch.as_tensor(value, device=device) for value in (x, vx, y, fit_weights(training_rows, 20).astype(np.float32))]
    with torch.inference_mode():
        similarities = np.stack([(tvx @ tx[ty == c].T).amax(1).cpu().numpy() for c in range(3)], axis=1)
    cosine = {label: float(np.quantile(similarities[vy == c, c], .01)) for c, label in enumerate(CLASSES)}
    optimizer = torch.optim.AdamW(model.parameters(), lr=.03, weight_decay=.001)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, 100, eta_min=.0003)
    generator = torch.Generator().manual_seed(42)
    best_key, stale, best_epoch = None, 0, 0
    started = time.perf_counter()
    for epoch in range(1, 101):
        model.train()
        objective = 0.
        for indexes in torch.randperm(len(x), generator=generator).split(128):
            indexes = indexes.to(device)
            optimizer.zero_grad(set_to_none=True)
            loss = (nn.functional.cross_entropy(model(tx[indexes]), ty[indexes], reduction="none") * tw[indexes]).mean()
            loss.backward()
            optimizer.step()
            objective += float(loss.detach()) * len(indexes)
        model.eval()
        with torch.inference_mode():
            train_scores, scores = model(tx).cpu().numpy(), model(tvx).cpu().numpy()
        train_metrics, val_metrics = metrics(train_scores, y), metrics(scores, vy)
        winner = scores.argmax(1)
        margin = np.sort(scores, axis=1)[:, -1] - np.sort(scores, axis=1)[:, -2]
        thresholds = {}
        for c, label in enumerate(CLASSES):
            wrong = (winner == c) & (vy != c)
            threshold = float(margin[wrong].max()) + .001 if wrong.any() else 0.
            thresholds[label] = threshold if ((winner == c) & (margin >= threshold)).sum() >= 5 else None
        policy = {"schema_version": 1, "class_order": CLASSES, "review_required": False, "on_uncertain": "RECAPTURE_REQUIRED",
                  "minimum_margin": thresholds, "minimum_training_cosine": cosine, "quality": quality}
        outcomes = []
        selective = np.zeros((3, 4), dtype=int)
        for i, row in enumerate(validation_rows):
            prediction = CLASSES[int(winner[i])]
            reasons = list(quality_reasons[i])
            if thresholds[prediction] is None: reasons.append("INSUFFICIENT_VALIDATION_SUPPORT")
            elif margin[i] <= 0 or margin[i] < thresholds[prediction]: reasons.append("AMBIGUOUS_APPEARANCE")
            if similarities[i, winner[i]] < cosine[prediction]: reasons.append("UNFAMILIAR_APPEARANCE")
            outcomes.append({"sourcePrediction": None if reasons else prediction, "recaptureReasons": reasons,
                             "recaptureRequested": bool(reasons), "analysisOutcome": "RECAPTURE_REQUIRED" if reasons else "CLASSIFIED"})
            selective[vy[i], 3 if reasons else winner[i]] += 1
        groups = groups_report(validation_rows, scores, outcomes)
        correct = sum(selective[c, c] for c in range(3))
        wrong = int(selective[:, :3].sum()) - correct
        age_camera_correct = groups["camera:DAY_16"]["raw_correct"] + groups["camera:DAY_18"]["raw_correct"]
        admitted = bool(groups["camera:DAY_16"]["correct_classified"] >= 226 and groups["camera:DAY_18"]["correct_classified"] >= 263
                        and all(selective[c, c] >= minimum for c, minimum in enumerate([235, 267, 159]))
                        and correct >= 661 and wrong == 0 and age_camera_correct > 525)
        utility = float(np.mean([g["correct_classified"] / g["images"] for g in groups.values()]))
        key = (admitted, utility, min(groups[f"camera:{label}"]["correct_classified"] / 270 for label in CLASSES[:2]),
               float(np.mean([g["raw_correct"] / g["images"] for g in groups.values()])), val_metrics["f1"], -val_metrics["loss"])
        record = {"epoch": epoch, "learning_rate": optimizer.param_groups[0]["lr"], "weighted_training_objective": objective / len(x),
                  "train": train_metrics, "validation": val_metrics, "validation_groups": groups, "validation_group_score": utility,
                  "selective_confusion_matrix": selective.tolist(), "admission_passed": admitted}
        with (RUN / "history.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, allow_nan=False) + "\n")
        if best_key is None or key > best_key:
            best_key, best_epoch, stale = key, epoch, 0
            best = (copy.deepcopy(model.state_dict()), copy.deepcopy(policy), outcomes, record)
        else:
            stale += 1
        if epoch % 5 == 0 or admitted:
            print(json.dumps({"epoch": epoch, "val_accuracy": val_metrics["accuracy"], "utility": utility,
                              "correct_per_class": [int(selective[c, c]) for c in range(3)], "admitted": admitted, "best_epoch": best_epoch}), flush=True)
        scheduler.step()
        if stale >= 20: break
    state, policy, outcomes, selected = best
    model.load_state_dict(state)
    coefficient, intercept = model[1].weight.detach().cpu().numpy(), model[1].bias.detach().cpu().numpy()
    validate_policy(policy, x, y)
    for row, feature, outcome, score in zip(validation_rows, vx, outcomes, vx @ coefficient.T + intercept, strict=True):
        with Image.open(inputs[row["source_sha256"]]["path"]) as image:
            actual = decide(score, feature, image, policy, x, y)
        assert actual["sourcePrediction"] == outcome["sourcePrediction"]
        assert actual["recaptureReasons"] == outcome["recaptureReasons"]
    np.savez_compressed(RUN / "head.npz", coefficient=coefficient, intercept=intercept)
    np.savez_compressed(RUN / "training-references.npz", features=x, labels=y)
    write(RUN / "gate-policy.json", policy)
    write(RUN / "validation-inputs.json", provenance)
    write(RUN / "validation-outcomes.json", [{"source_sha256": row["source_sha256"], "source_label": row["training_label"], **outcome}
                                             for row, outcome in zip(validation_rows, outcomes, strict=True)])
    report = {"class_order": CLASSES, "epochs_completed": epoch, "selected_epoch": best_epoch, "validation_admission_passed": selected["admission_passed"],
              "elapsed_seconds": time.perf_counter() - started, "device": str(device), "validation": selected,
              "test_images_opened": 0, "general_reject_condition_validated": False}
    write(RUN / "metrics.json", report)
    write(RUN / "config.json", {"class_order": CLASSES, "dataset_sha256": sha(DATA / "manifest.jsonl"),
          "encoder_onnx_sha256": "479211e3e587b0bce7d9bb1be1a318c48bdc62f632374f75d980ab1dbceda31e",
          "training_method": "MINIBATCH_EPOCH_CLASSIFIER_HEAD", "operational_use_authorized": False})
    assert all(sha(ROOT / name) == digest for name, digest in protected.items())
    names = ["experiment-plan.json", "history.jsonl", "head.npz", "training-references.npz", "gate-policy.json", "validation-inputs.json", "validation-outcomes.json", "metrics.json", "config.json"]
    write(RUN / "selection-lock.json", {"artifacts": {name: sha(RUN / name) for name in names}, "physical_reject_validation_passed": False})
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
