"""Train a retained-encoder classifier in genuine epochs with recorded metrics."""
from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
PARENT = ROOT / "ml/runs/retained-unfertilized-serving-20261019"
DATA = ROOT / "data/local/retained-camera-epochs-reject-20261019"
RUN = ROOT / "ml/runs/retained-epochs-reject-20261019"
CLASSES = ["DAY_16", "DAY_18", "REJECT"]
SOURCE_CLASSES = ["DAY_16", "DAY_18", "UNFERTILIZED"]


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def target_rows(rows):
    result, groups, identities = [], {}, {}
    for row in rows:
        if row["source_label"] not in SOURCE_CLASSES or (row.get("physical_egg_id") or "").startswith("physical-reject"):
            raise ValueError("Only the explicit age/Unfertilized dataset may enter this experiment")
        identity = (row["partition"], row["source_label"])
        for key in ("source_sha256", "pixel_sha256"):
            if identities.setdefault((key, row[key]), identity) != identity:
                raise ValueError("Conflicting label or cross-partition image")
        group = row.get("physical_egg_id") or row["duplicate_group"]
        if groups.setdefault(group, row["partition"]) != row["partition"]:
            raise ValueError("Physical egg or source family crosses partitions")
        result.append({**row, "training_label": "REJECT" if row["source_label"] == "UNFERTILIZED" else row["source_label"],
                       "output_label_authority": "Operator-requested Reject name; third class contains only original Unfertilized annotations, not general defects"})
    return result


def metrics(scores, truth):
    from sklearn.metrics import confusion_matrix, precision_recall_fscore_support
    shifted = scores - scores.max(1, keepdims=True)
    loss = np.mean(np.log(np.exp(shifted).sum(1)) - shifted[np.arange(len(truth)), truth])
    prediction = scores.argmax(1)
    precision, recall, f1, _ = precision_recall_fscore_support(truth, prediction, labels=[0, 1, 2], zero_division=0)
    return {"loss": float(loss), "accuracy": float(np.mean(prediction == truth)),
            "precision": float(precision.mean()), "recall": float(recall.mean()), "f1": float(f1.mean()),
            "confusion_matrix": confusion_matrix(truth, prediction, labels=[0, 1, 2]).tolist()}


def groups_report(rows, scores, outcomes=None):
    groups = {}
    for index, row in enumerate(rows):
        group = ("camera:" if row.get("physical_egg_id") else "source:") + row["training_label"]
        groups.setdefault(group, []).append(index)
    return {name: {"images": len(indexes),
                   "raw_correct": sum(CLASSES[int(scores[i].argmax())] == rows[i]["training_label"] for i in indexes),
                   **({"classified": sum(outcomes[i]["sourcePrediction"] is not None for i in indexes),
                       "correct_classified": sum(outcomes[i]["sourcePrediction"] == rows[i]["training_label"] for i in indexes),
                       "wrong_classified": sum(outcomes[i]["sourcePrediction"] not in (None, rows[i]["training_label"]) for i in indexes)} if outcomes is not None else {})}
            for name, indexes in groups.items()}


def main():
    if RUN.exists() or DATA.exists():
        raise FileExistsError("Use a fresh version; preserve completed or interrupted runs")
    from .train_unfertilized import fit_weights, calibrate
    from balut_api.selective_gate import decide
    from PIL import Image
    lock = json.loads((PARENT / "selection-lock.json").read_text())
    assert all(sha(PARENT / name) == digest for name, digest in lock["artifacts"].items())
    manifest = ROOT / "data/local/retained-camera-unfertilized-20261019/manifest.jsonl"
    assert sha(manifest) == "01478d1619524c383539bf0d7bd3b730be5c5d82aa9f01a51db19e1018300885"
    rows = target_rows([json.loads(line) for line in manifest.read_text().splitlines()])
    DATA.mkdir()
    (DATA / "manifest.jsonl").write_bytes("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows).encode())
    audit = {"class_order": CLASSES, "total_rows": len(rows), "manifest_sha256": sha(DATA / "manifest.jsonl"),
             "parent_manifest_sha256": sha(manifest), "original_source_labels_preserved": True,
             "output_label_mapping": {"UNFERTILIZED": "REJECT"}, "general_reject_condition_validated": False,
             "vendor_reject_eggs_included": False,
             "partition_counts": {part: dict(Counter(row["training_label"] for row in rows if row["partition"] == part))
                                  for part in ("train", "validation", "test")}}
    write(DATA / "audit.json", audit)
    development = [row for row in rows if row["partition"] != "test"]
    with np.load(PARENT / "development.npz", allow_pickle=False) as bank:
        np.testing.assert_array_equal(bank["source_sha256"], [row["source_sha256"] for row in development])
        features = bank["features"].astype(np.float32)
    train_mask = np.array([row["partition"] == "train" for row in development])
    training_rows = [row for row in development if row["partition"] == "train"]
    validation_rows = [row for row in development if row["partition"] == "validation"]
    x, vx = features[train_mask], features[~train_mask]
    truth = np.array([CLASSES.index(row["training_label"]) for row in development])
    y, vy = truth[train_mask], truth[~train_mask]
    weights = fit_weights(training_rows, 20).astype(np.float32)
    assert len(x) == 2256 and len(vx) == 814 and len(rows) == 3719
    RUN.mkdir()
    protected = {str(path.relative_to(ROOT)): sha(path) for path in
                 [Path(__file__), PARENT / "selection-lock.json", PARENT / "development.npz", PARENT / "head.npz", DATA / "manifest.jsonl"]}
    write(RUN / "experiment-plan.json", {"class_order": CLASSES, "epochs_maximum": 100, "patience": 20,
          "batch_size": 128, "learning_rate": .03, "minimum_learning_rate": .0003, "weight_decay": .001,
          "input_dropout": .1, "seed": 42, "camera_weight_per_egg": 20,
          "architecture": "Retained frozen DINOv2/EfficientNet embedding; newly initialized linear classifier fitted in minibatch epochs",
          "selection": "Highest mean raw recall across five validation source/camera class groups; then macro F1; then minimum validation loss",
          "test_policy": "No test fitting/selection. Existing 649-image test was previously inspected and is historical regression evidence, not a fresh independent test.",
          "logging": "Unweighted clean train/validation cross-entropy, accuracy, macro precision, macro recall and macro F1 at each completed epoch; weighted training objective also recorded",
          "protected_files": protected, "dataset": audit,
          "limitations": ["Only five training physical eggs per age", "Reject means the renamed Unfertilized source class, not verified general defects",
                           "No physical Unfertilized/Reject check is available", "Epochs alone do not establish better accuracy"]})
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    import torch
    from torch import nn
    torch.set_num_threads(4)
    torch.manual_seed(42)
    torch.use_deterministic_algorithms(True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = nn.Sequential(nn.Dropout(.1), nn.Linear(x.shape[1], 3)).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=.03, weight_decay=.001)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=100, eta_min=.0003)
    tx, ty, tw = [torch.as_tensor(value, device=device) for value in (x, y, weights)]
    tvx = torch.as_tensor(vx, device=device)
    generator = torch.Generator().manual_seed(42)
    best_key, best_epoch, stale, history = None, 0, 0, []
    started = time.perf_counter()
    for epoch in range(1, 101):
        model.train()
        objective, seen = 0., 0
        for indexes in torch.randperm(len(x), generator=generator).split(128):
            indexes = indexes.to(device)
            optimizer.zero_grad(set_to_none=True)
            losses = nn.functional.cross_entropy(model(tx[indexes]), ty[indexes], reduction="none")
            loss = (losses * tw[indexes]).mean()
            loss.backward()
            optimizer.step()
            objective += float(loss.detach()) * len(indexes)
            seen += len(indexes)
        model.eval()
        with torch.inference_mode():
            train_scores = model(tx).cpu().numpy()
            validation_scores = model(tvx).cpu().numpy()
        train_metrics, validation_metrics = metrics(train_scores, y), metrics(validation_scores, vy)
        groups = groups_report(validation_rows, validation_scores)
        score = float(np.mean([group["raw_correct"] / group["images"] for group in groups.values()]))
        key = (score, validation_metrics["f1"], -validation_metrics["loss"])
        record = {"epoch": epoch, "learning_rate": optimizer.param_groups[0]["lr"], "weighted_training_objective": objective / seen,
                  "train": train_metrics, "validation": validation_metrics, "validation_group_score": score, "validation_groups": groups}
        history.append(record)
        with (RUN / "history.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, allow_nan=False) + "\n")
        if best_key is None or key > best_key:
            best_key, best_epoch, stale = key, epoch, 0
            best_state = copy.deepcopy(model.state_dict())
        else:
            stale += 1
        print(json.dumps({"epoch": epoch, "train_loss": train_metrics["loss"], "val_loss": validation_metrics["loss"],
                          "val_accuracy": validation_metrics["accuracy"], "val_group_score": score, "best_epoch": best_epoch}), flush=True)
        scheduler.step()
        if stale >= 20:
            break
    model.load_state_dict(best_state)
    model.eval()
    coefficient = model[1].weight.detach().cpu().numpy()
    intercept = model[1].bias.detach().cpu().numpy()
    scores = vx @ coefficient.T + intercept
    old_policy = json.loads((PARENT / "gate-policy.json").read_text())
    policy = calibrate(scores, vy, vx, x, y, old_policy["quality"])
    policy["class_order"] = CLASSES
    for name in ("minimum_margin", "minimum_training_cosine"):
        policy[name]["REJECT"] = policy[name].pop("UNFERTILIZED")
    provenance = json.loads((PARENT / "validation-inputs.json").read_text())
    inputs = {item["source_sha256"]: item for item in provenance}
    outcomes = []
    for row, score, feature in zip(validation_rows, scores, vx, strict=True):
        item = inputs[row["source_sha256"]]
        assert sha(Path(item["path"])) == item["serving_jpeg_sha256"]
        with Image.open(item["path"]) as image:
            outcomes.append(decide(score, feature, image, policy, x, y))
    selective = np.zeros((3, 4), dtype=int)
    for truth_id, outcome in zip(vy, outcomes, strict=True):
        selective[truth_id, CLASSES.index(outcome["sourcePrediction"]) if outcome["sourcePrediction"] else 3] += 1
    np.savez_compressed(RUN / "head.npz", coefficient=coefficient, intercept=intercept)
    np.savez_compressed(RUN / "training-references.npz", features=x, labels=y)
    write(RUN / "gate-policy.json", policy)
    write(RUN / "validation-inputs.json", provenance)
    write(RUN / "validation-outcomes.json", [{"source_sha256": row["source_sha256"], "source_label": row["training_label"], **outcome}
                                             for row, outcome in zip(validation_rows, outcomes, strict=True)])
    report = {"class_order": CLASSES, "epochs_completed": epoch, "selected_epoch": best_epoch,
              "elapsed_seconds": time.perf_counter() - started, "device": str(device),
              "validation": {**metrics(scores, vy), "raw_confusion_matrix": metrics(scores, vy)["confusion_matrix"],
                             "selective_confusion_matrix": selective.tolist(), "validation_groups": groups_report(validation_rows, scores, outcomes)},
              "test_images_opened": 0, "general_reject_condition_validated": False}
    write(RUN / "metrics.json", report)
    write(RUN / "config.json", {"class_order": CLASSES, "dataset_sha256": audit["manifest_sha256"],
          "encoder_onnx_sha256": "479211e3e587b0bce7d9bb1be1a318c48bdc62f632374f75d980ab1dbceda31e",
          "training_method": "MINIBATCH_EPOCH_CLASSIFIER_HEAD", "operational_use_authorized": False})
    assert all(sha(ROOT / name) == digest for name, digest in protected.items())
    names = ["experiment-plan.json", "history.jsonl", "head.npz", "training-references.npz", "gate-policy.json",
             "validation-inputs.json", "validation-outcomes.json", "metrics.json", "config.json"]
    write(RUN / "selection-lock.json", {"artifacts": {name: sha(RUN / name) for name in names}, "physical_reject_validation_passed": False})
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
