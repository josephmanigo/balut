"""Validation-selected frozen-feature benchmark; preserve historical test partitions."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

import numpy as np
import torch
import torchvision
from PIL import Image, ImageOps
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.multiclass import OneVsRestClassifier
from sklearn.svm import SVC
from torch.utils.data import DataLoader, Dataset

from .feature_models import DINO_REVISION, MEAN, STD, FeatureEncoder, SourceClassifier, build_backbone, build_head, image_transform, portable_head
from .train_public import load_audited_rows

TASKS = {
    "duck-candling": ("data/public/duck-egg-candling/audit-v2/manifest.jsonl", "ml/runs/duck-candling-v1"),
    "source-age16-18": ("data/public/thesis-egg-candling/audit-v1/manifest.jsonl", "ml/runs/source-age16-18-v1"),
    "pat-balut": ("data/public/pat-balut/audit-v2/manifest.jsonl", "ml/runs/pat-balut-v1"),
}
BACKBONES = ["dinov2_vits14", "convnext_tiny", "efficientnet_b0"]
GRID = ([{"kind": "logistic", "C": c, "class_weight": weight} for c in [0.01, 0.1, 1.0, 10.0] for weight in [None, "balanced"]]
        + [{"kind": "rbf_ovr", "C": c, "class_weight": weight} for c in [0.1, 1.0, 10.0] for weight in [None, "balanced"]])


def write_json(path: Path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def selection_key(metrics):
    # Fixed before any candidate test inference; stable first-candidate tie break.
    return tuple(metrics[key] for key in ["macro_f1", "balanced_accuracy", "accuracy"])


def metrics_for(truth, predicted, classes):
    return {"image_count": len(truth), "accuracy": accuracy_score(truth, predicted),
            "correct": int(np.sum(np.asarray(truth) == np.asarray(predicted))),
            "balanced_accuracy": balanced_accuracy_score(truth, predicted),
            "macro_f1": f1_score(truth, predicted, average="macro", zero_division=0),
            "confusion_matrix": confusion_matrix(truth, predicted, labels=range(len(classes))).tolist(),
            "per_class": classification_report(truth, predicted, labels=range(len(classes)), target_names=classes,
                                               output_dict=True, zero_division=0)}


class PartitionImages(Dataset):
    def __init__(self, rows, partitions, classes):
        self.items = [(i, r) for i, r in enumerate(rows) if r["partition"] in partitions]
        self.transform = image_transform()
        self.classes = classes

    def __len__(self):
        return len(self.items)

    def __getitem__(self, index):
        original_index, row = self.items[index]
        with Image.open(row["image_path"]) as original:
            img = ImageOps.exif_transpose(original).convert("RGB")
        return self.transform(img), self.classes.index(row["source_label"]), original_index


def extract(encoder, rows, partitions, classes, device, batch_size):
    loader = DataLoader(PartitionImages(rows, partitions, classes), batch_size=batch_size, shuffle=False, num_workers=0)
    features, labels, indexes = [], [], []
    with torch.inference_mode():
        for images, targets, idx in loader:
            features.append(encoder(images.to(device)).cpu().numpy())
            labels.extend(targets.tolist())
            indexes.extend(idx.tolist())
    return np.concatenate(features), np.array(labels), np.array(indexes)


def make_estimator(spec):
    if spec["kind"] == "logistic":
        return LogisticRegression(C=spec["C"], class_weight=spec["class_weight"], max_iter=2000, random_state=42)
    return OneVsRestClassifier(SVC(C=spec["C"], class_weight=spec["class_weight"], kernel="rbf", gamma="scale", cache_size=512), n_jobs=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a fresh directory to preserve experiments and the selection lock")
    if args.batch_size < 1:
        parser.error("batch-size must be positive")
    torch.set_num_threads(4)
    torch.manual_seed(42)
    np.random.seed(42)
    torch.use_deterministic_algorithms(True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    args.output.mkdir(parents=True)
    plan = {"backbones": BACKBONES, "grid": GRID, "seed": 42, "view_policy": "resize224_plus_horizontal_flip_mean_then_L2",
            "selection": ["validation.macro_f1", "validation.balanced_accuracy", "validation.accuracy", "first_candidate"],
            "promotion": "candidate validation selection key must strictly exceed original baseline",
            "test_policy": "All task selections locked before extracting test features; evaluate promoted candidate once.",
            "test_interpretation": "Historical holdout, previously inspected in baseline report; not new independent field validation.",
            "dinov2_revision": DINO_REVISION, "torch": str(torch.__version__), "torchvision": str(torchvision.__version__),
            "gpu": torch.cuda.get_device_name(0) if device.type == "cuda" else None}
    write_json(args.output / "experiment-plan.json", plan)
    datasets, best = {}, {}
    for task, (manifest, baseline_path) in TASKS.items():
        rows, audit = load_audited_rows(Path(manifest))
        datasets[task] = {"rows": rows, "audit": audit, "classes": sorted({r["source_label"] for r in rows})}
        baseline = json.loads((Path(baseline_path) / "metrics.json").read_text(encoding="utf-8"))
        datasets[task]["baseline"] = baseline
        directory = args.output / task
        directory.mkdir()
        best[task] = None
    started = time.monotonic()
    for backbone in BACKBONES:
        print(json.dumps({"stage": "load_backbone", "backbone": backbone}), flush=True)
        encoder = FeatureEncoder(build_backbone(backbone, pretrained=True)).eval().to(device)
        torch.save({k: v.cpu() for k, v in encoder.state_dict().items()}, args.output / f"{backbone}-encoder.pt")
        for task, dataset in datasets.items():
            print(json.dumps({"stage": "development_features", "backbone": backbone, "task": task}), flush=True)
            rows, classes = dataset["rows"], dataset["classes"]
            features, labels, indexes = extract(encoder, rows, {"train", "validation"}, classes, device, args.batch_size)
            mask = np.array([rows[i]["partition"] == "train" for i in indexes])
            if any(rows[i]["partition"] == "test" for i in indexes):
                raise RuntimeError("Test features entered development")
            np.savez_compressed(args.output / task / f"{backbone}-development.npz", features=features, labels=labels,
                                indexes=indexes, manifest_sha256=dataset["audit"]["manifest_sha256"])
            for spec in GRID:
                estimator = make_estimator(spec)
                estimator.fit(features[mask], labels[mask])
                predicted = estimator.predict(features[~mask])
                measured = metrics_for(labels[~mask], predicted, classes)
                head, head_spec = portable_head(estimator, spec["kind"])
                with torch.inference_mode():
                    portable_scores = head(torch.from_numpy(features[~mask])).numpy()
                if not np.array_equal(portable_scores.argmax(1), predicted):
                    raise RuntimeError("Portable classifier predictions differ from sklearn on validation")
                record = {"backbone": backbone, "hyperparameters": spec, "head": head_spec, "validation": measured,
                          "portable_validation_argmax_agreement": 1.0}
                with (args.output / task / "candidates.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record) + "\n")
                if best[task] is None or selection_key(measured) > selection_key(best[task]["validation"]):
                    best[task] = record
                    torch.save({"state_dict": head.state_dict(), "spec": head_spec}, args.output / task / "selected-head.pt")
                    np.savez_compressed(args.output / task / "selected-validation.npz", scores=portable_scores,
                                        truth=labels[~mask], indexes=indexes[~mask])
            print(json.dumps({"stage": "development_complete", "task": task, "backbone": backbone,
                              "best_backbone_so_far": best[task]["backbone"],
                              "best_val_macro_f1": best[task]["validation"]["macro_f1"],
                              "elapsed_seconds": round(time.monotonic()-started, 1)}), flush=True)
        del encoder
        if device.type == "cuda":
            torch.cuda.empty_cache()
    selections = {}
    for task, record in best.items():
        baseline = datasets[task]["baseline"]["validation"]
        selections[task] = {**record, "promoted": selection_key(record["validation"]) > selection_key(baseline),
                            "baseline_validation": baseline, "manifest_sha256": datasets[task]["audit"]["manifest_sha256"]}
    lock = args.output / "selection-lock.json"
    write_json(lock, selections)
    lock_hash = hashlib.sha256(lock.read_bytes()).hexdigest()
    print(json.dumps({"stage": "all_selections_locked", "sha256": lock_hash,
                      "choices": {k: {"backbone": v["backbone"], "promoted": v["promoted"]} for k, v in selections.items()}}), flush=True)
    for task, chosen in selections.items():
        if not chosen["promoted"]:
            write_json(args.output / task / "metrics.json", {"status": "BASELINE_RETAINED_BY_VALIDATION", "selection": chosen,
                       "baseline_test": datasets[task]["baseline"]["test"], "candidate_test": None})
            continue
        if hashlib.sha256(lock.read_bytes()).hexdigest() != lock_hash:
            raise RuntimeError("Selection lock changed before test")
        dataset = datasets[task]
        encoder = FeatureEncoder(build_backbone(chosen["backbone"])).eval()
        encoder.load_state_dict(torch.load(args.output / f"{chosen['backbone']}-encoder.pt", weights_only=True, map_location="cpu"))
        head_payload = torch.load(args.output / task / "selected-head.pt", weights_only=True, map_location="cpu")
        head = build_head(head_payload["spec"])
        head.load_state_dict(head_payload["state_dict"])
        encoder.to(device)
        print(json.dumps({"stage": "selected_historical_test", "task": task, "backbone": chosen["backbone"]}), flush=True)
        features, labels, indexes = extract(encoder, dataset["rows"], {"test"}, dataset["classes"], device, args.batch_size)
        with torch.inference_mode():
            scores = head(torch.from_numpy(features)).numpy()
        test = metrics_for(labels, scores.argmax(1), dataset["classes"])
        config = {"status": "EXPLORATORY_FROZEN_FEATURE_CLASSIFIER", "operational_use_authorized": False,
                  "backbone": chosen["backbone"], "head": head_payload["spec"], "class_order": dataset["classes"],
                  "input_size": 224, "normalization_mean": MEAN, "normalization_std": STD,
                  "view_policy": plan["view_policy"], "hyperparameters": chosen["hyperparameters"],
                  "manifest_sha256": dataset["audit"]["manifest_sha256"], "selection_lock_sha256": lock_hash,
                  "dinov2_revision": DINO_REVISION if chosen["backbone"] == "dinov2_vits14" else None,
                  "provenance": dataset["audit"]["provenance"], "limitations": dataset["audit"]["limitations"],
                  "output_semantics": "Uncalibrated decision scores; never probabilities or verified biological outcomes."}
        model = SourceClassifier(encoder.cpu(), head.cpu()).eval()
        torch.save({"state_dict": model.state_dict(), "config": config}, args.output / task / "best.pt")
        write_json(args.output / task / "config.json", config)
        checkpoint_hash = hashlib.sha256((args.output / task / "best.pt").read_bytes()).hexdigest()
        write_json(args.output / task / "metrics.json", {"status": "EXPLORATORY_ONLY", "validation": chosen["validation"],
                   "test": test, "baseline_test": dataset["baseline"]["test"], "selection_lock_sha256": lock_hash,
                   "checkpoint_sha256": checkpoint_hash, "elapsed_seconds": time.monotonic()-started,
                   "test_interpretation": plan["test_interpretation"]})
        with (args.output / task / "test-predictions.jsonl").open("w", encoding="utf-8") as handle:
            for idx, y, score in zip(indexes, labels, scores):
                handle.write(json.dumps({"row_index": int(idx), "true_source_label": dataset["classes"][y],
                                         "predicted_source_label": dataset["classes"][int(score.argmax())],
                                         "decision_scores": dict(zip(dataset["classes"], score.tolist()))}) + "\n")
        np.savez_compressed(args.output / task / "selected-test.npz", features=features, scores=scores, truth=labels, indexes=indexes)
        print(json.dumps({"stage": "test_complete", "task": task, "accuracy": test["accuracy"],
                          "correct": test["correct"], "count": test["image_count"], "macro_f1": test["macro_f1"]}), flush=True)
        del model, encoder, head
        if device.type == "cuda":
            torch.cuda.empty_cache()
    write_json(args.output / "completion.json", {"completed": True, "selection_lock_sha256": lock_hash,
               "elapsed_seconds": time.monotonic()-started})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
