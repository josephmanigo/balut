"""Real MobileNetV2 image epochs on the new, physical-egg-disjoint EMEET study."""
import argparse
from collections import Counter
import io
import json
import os
from pathlib import Path
import random
import sys
import time

os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "ml"), str(ROOT / "apps/edge_api")]
import numpy as np
from PIL import Image, ImageOps
import torch
from torch import nn
from torch.nn import functional as F
from torch.utils.data import Dataset, DataLoader
from torchvision import models, transforms
from balut_ml.emeet_development import development_rows, validate_rows
from balut_ml.scientific_metrics import classification_metrics
from scripts.capture_emeet_egg import sha, write

CLASSES = ["DAY_16", "DAY_18", "REJECT"]
MEAN, STD = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]


class MobileNetEgg(nn.Module):
    def __init__(self, pretrained=False):
        super().__init__()
        network = models.mobilenet_v2(weights=models.MobileNet_V2_Weights.IMAGENET1K_V2 if pretrained else None)
        self.features = network.features
        self.classifier = nn.Sequential(nn.Dropout(.2), nn.Linear(1280, 3))

    def forward(self, images):
        values = self.features(images).mean((2, 3))
        return self.classifier(values), F.normalize(values, p=2, dim=1)


def measured(scores, truth):
    scores, truth = np.asarray(scores), np.asarray(truth, dtype=int)
    if scores.shape != (len(truth), 3) or not np.isfinite(scores).all() or not len(truth):
        raise ValueError("Invalid score matrix")
    matrix = np.zeros((3, 3), dtype=int)
    np.add.at(matrix, (truth, scores.argmax(1)), 1)
    result = classification_metrics(matrix, np.column_stack([matrix, np.zeros(3, dtype=int)]))
    shifted = scores - scores.max(1, keepdims=True)
    result["loss"] = float(np.mean(np.log(np.exp(shifted).sum(1)) - shifted[np.arange(len(truth)), truth]))
    return result


def training_weights(rows):
    groups = [r.get("physical_egg_id") or r["duplicate_group"] for r in rows]
    count = Counter(groups)
    weights = np.asarray([1 / count[group] for group in groups])
    labels = np.asarray([CLASSES.index(r["source_label"]) for r in rows])
    if set(labels) != {0, 1, 2}:
        raise ValueError("Training needs all three classes")
    for label in range(3):
        mask = labels == label
        weights[mask] *= len(rows) / (3 * weights[mask].sum())
    return weights.astype(np.float32)


def load_development(dataset):
    rows = development_rows(dataset, require_complete=True)
    age_counts = Counter((r["partition"], r["source_label"]) for r in rows)
    expected = {(part, label): count for part, count in [("train", 900), ("validation", 300)] for label in CLASSES[:2]}
    if age_counts != expected:
        raise ValueError("Require exactly 2400 new age development images under the frozen split")
    reject = dataset / "reject"
    audit = json.loads((reject / "audit.json").read_text())
    if sha(reject / "manifest.jsonl") != audit["manifest_sha256"]:
        raise ValueError("Reject manifest changed")
    rows += [r for r in map(json.loads, (reject / "manifest.jsonl").read_text().splitlines()) if r["partition"] != "test"]
    validate_rows(rows)
    for row in rows:
        if sha(Path(row["image_path"])) != row["source_sha256"]:
            raise ValueError("Dataset image changed")
    return rows


class Images(Dataset):
    def __init__(self, images, rows, indexes, augment=False, weights=None):
        self.images, self.rows, self.indexes = images, rows, list(indexes)
        self.weights = np.ones(len(indexes), dtype=np.float32) if weights is None else weights
        ops = [transforms.RandomAffine(7, translate=(.02, .02), scale=(.97, 1.03),
               interpolation=transforms.InterpolationMode.BILINEAR), transforms.ColorJitter(brightness=.15, contrast=.15)] if augment else []
        self.transform = transforms.Compose(ops + [transforms.ToTensor(), transforms.Normalize(MEAN, STD)])

    def __len__(self):
        return len(self.indexes)

    def __getitem__(self, index):
        i = self.indexes[index]
        return self.transform(self.images[i]), CLASSES.index(self.rows[i]["source_label"]), float(self.weights[index])


def infer(model, dataset, device, batch_size=32):
    model.eval()
    scores, features, truth = [], [], []
    with torch.inference_mode():
        for images, labels, _ in DataLoader(dataset, batch_size=batch_size, shuffle=False, num_workers=0):
            logits, embedding = model(images.to(device))
            scores.extend(logits.cpu().numpy())
            features.extend(embedding.cpu().numpy())
            truth.extend(labels.numpy())
    return np.asarray(scores), np.asarray(features), np.asarray(truth)


def plot_history(output):
    sys.path.insert(0, str(ROOT / "tmp/pdfdeps"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    history = [json.loads(line) for line in (output / "history.jsonl").read_text().splitlines()]
    fig, axes = plt.subplots(2, 3, figsize=(15, 8), constrained_layout=True)
    for axis, key, title in zip(axes.flat, ["loss", "raw_accuracy", "macro_precision", "macro_recall", "macro_f1", "balanced_accuracy"],
                               ["Cross-entropy loss", "Accuracy", "Macro precision", "Macro recall", "Macro F1", "Balanced accuracy"], strict=True):
        for split, color in [("train", "#1f776a"), ("validation", "#bd6b20")]:
            axis.plot([r["epoch"] for r in history], [r[split][key] for r in history], label=split, color=color)
        axis.set(title=title, xlabel="Completed epoch")
        if key != "loss":
            axis.set_ylim(0, 1.02)
        axis.grid(alpha=.2)
        axis.legend()
    fig.suptitle("MobileNetV2 · actual epoch measurements · test data excluded", fontsize=15)
    fig.savefig(output / "epoch-curves.png", dpi=180)
    plt.close(fig)


def train(args):
    dataset, output = args.dataset.resolve(), args.output.resolve()
    if output.exists() or (dataset / "candidate-lock.json").exists():
        raise FileExistsError("Preserve previous runs and the locked test boundary")
    rows = load_development(dataset)
    if not torch.cuda.is_available():
        raise RuntimeError("This study's training recipe requires the available CUDA GPU")
    random.seed(42); np.random.seed(42); torch.manual_seed(42); torch.cuda.manual_seed_all(42)
    torch.set_num_threads(4); torch.use_deterministic_algorithms(True); torch.backends.cudnn.benchmark = False
    output.mkdir(parents=True)
    model = MobileNetEgg(pretrained=True).cuda()
    write(output / "development-manifest.json", rows)
    recipe = {"architecture": "MobileNetV2", "pretrained_weights": "torchvision.IMAGENET1K_V2", "class_order": CLASSES,
              "maximum_epochs": args.epochs, "patience": args.patience, "minimum_f1_improvement": .001,
              "warmup_epochs": 3, "batch_size": 32, "seed": 42, "optimizer": "AdamW", "head_lr": .0003,
              "encoder_lr": .00001, "weight_decay": .0001, "input_size": 224,
              "normalization_mean": MEAN, "normalization_std": STD,
              "trainable_encoder": "features[14:] after three head-only warmup epochs; batch-normalization statistics frozen",
              "selection": "Validation macro F1 improvement greater than .001; lower loss breaks equal-F1 checkpoint ties without resetting patience",
              "early_stop": "Eight stale epochs after warmup, or maximum epoch cap; restore best validation checkpoint",
              "training_weights": "Equal weight per egg/source family within each class; equal total weight per class",
              "augmentation": "Training only: affine +/-7deg, translation +/-2%, scale97-103%, brightness/contrast +/-15%; never counted as new photos",
              "metrics": "Clean train and validation inference after each epoch; full confusion counts, per-class precision/recall/F1, macro and weighted averages",
              "test_images_opened": 0, "field_accuracy_established": False,
              "collection_plan_sha256": sha(dataset / "collection-plan.json"),
              "development_manifest_sha256": sha(output / "development-manifest.json"),
              "trainer_sha256": sha(Path(__file__)), "torch": str(torch.__version__), "device": torch.cuda.get_device_name(0),
              "pretrained_weights_sha256": sha(Path(torch.hub.get_dir()) / "checkpoints/mobilenet_v2-7ebf99e0.pth"),
              "model_parameters": sum(p.numel() for p in model.parameters())}
    write(output / "experiment-plan.json", recipe)
    images = []
    for row in rows:
        with Image.open(row["image_path"]) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            if source.format != "JPEG":
                encoded = io.BytesIO(); image.save(encoded, "JPEG", quality=95)
                image = Image.open(io.BytesIO(encoded.getvalue())).convert("RGB")
            images.append(image.resize((224, 224), Image.Resampling.BILINEAR))
    fit = [i for i, r in enumerate(rows) if r["partition"] == "train"]
    held = [i for i, r in enumerate(rows) if r["partition"] == "validation"]
    clean_train = Images(images, rows, fit)
    validation = Images(images, rows, held)
    augmented = Images(images, rows, fit, True, training_weights([rows[i] for i in fit]))
    loader = DataLoader(augmented, batch_size=32, shuffle=True, num_workers=0, generator=torch.Generator().manual_seed(42))
    for parameter in model.features.parameters():
        parameter.requires_grad_(False)
    optimizer = torch.optim.AdamW([{"params": model.classifier.parameters(), "lr": .0003},
                                  {"params": model.features[14:].parameters(), "lr": .00001}], weight_decay=.0001)
    best_f1, best_loss, best_epoch, stale = -1., float("inf"), 0, 0
    started = time.perf_counter()
    for epoch in range(1, args.epochs + 1):
        if epoch == 4:
            for parameter in model.features[14:].parameters():
                parameter.requires_grad_(True)
            stale = 0
        model.train()
        for layer in model.modules():
            if isinstance(layer, nn.BatchNorm2d):
                layer.eval()
        objective = 0.
        for batch, (samples, labels, weights) in enumerate(loader, 1):
            optimizer.zero_grad(set_to_none=True)
            scores, _ = model(samples.cuda())
            loss = (F.cross_entropy(scores, labels.cuda(), reduction="none") * weights.cuda()).mean()
            if not torch.isfinite(loss):
                raise RuntimeError("Nonfinite training loss")
            loss.backward(); nn.utils.clip_grad_norm_(model.parameters(), 5.); optimizer.step()
            objective += float(loss.detach()) * len(labels)
            if batch % 25 == 0:
                write(output / "progress.json", {"epoch": epoch, "batch": batch, "batches": len(loader)})
        train_scores, _, train_truth = infer(model, clean_train, "cuda")
        val_scores, _, val_truth = infer(model, validation, "cuda")
        train_metrics, val_metrics = measured(train_scores, train_truth), measured(val_scores, val_truth)
        record = {"epoch": epoch, "train": train_metrics, "validation": val_metrics,
                  "weighted_augmentation_loss": objective / len(fit), "elapsed_seconds": time.perf_counter() - started}
        with (output / "history.jsonl").open("a") as stream:
            stream.write(json.dumps(record, allow_nan=False) + "\n")
        improved = val_metrics["macro_f1"] > best_f1 + .001
        tie = abs(val_metrics["macro_f1"] - best_f1) < 1e-12 and val_metrics["loss"] < best_loss
        stale = 0 if improved else stale + 1
        if improved or tie:
            best_f1, best_loss, best_epoch = val_metrics["macro_f1"], val_metrics["loss"], epoch
            temporary = output / "best.tmp"
            torch.save({"state_dict": model.cpu().state_dict(), "epoch": epoch, "recipe": recipe}, temporary)
            temporary.replace(output / "best.pt"); model.cuda()
            write(output / "selected.json", record)
        print(json.dumps({"epoch": epoch, "validation_f1": val_metrics["macro_f1"], "validation_recall": val_metrics["macro_recall"],
                          "best_epoch": best_epoch, "stale": stale, "elapsed_seconds": record["elapsed_seconds"]}), flush=True)
        if epoch >= 3 + args.patience and stale >= args.patience:
            break
    model.load_state_dict(torch.load(output / "best.pt", map_location="cpu", weights_only=True)["state_dict"])
    model.cuda().eval()
    scores, features, truth = infer(model, Images(images, rows, range(len(rows))), "cuda")
    np.savez_compressed(output / "development.npz", scores=scores, features=features, truth=truth)
    summary = {"architecture": "MobileNetV2", "epochs_completed": epoch, "selected_epoch": best_epoch,
               "stop_reason": "validation_patience" if epoch < args.epochs else "maximum_epochs",
               "training_images": len(fit), "validation_images": len(held), "test_images_opened": 0,
               "age_training_eggs": len({rows[i]["physical_egg_id"] for i in fit if rows[i].get("physical_egg_id")}),
               "age_validation_eggs": len({rows[i]["physical_egg_id"] for i in held if rows[i].get("physical_egg_id")}),
               "train": measured(scores[fit], truth[fit]), "validation": measured(scores[held], truth[held]),
               "promoted": False, "field_accuracy_established": False, "elapsed_seconds": time.perf_counter() - started}
    write(output / "metrics.json", summary)
    plot_history(output)
    model.cpu().eval()
    torch.onnx.export(model, torch.zeros(1, 3, 224, 224), str(output / "best.onnx"), input_names=["images"],
                      output_names=["decision_scores", "embedding"], opset_version=17, dynamo=False,
                      dynamic_axes={"images": {0: "batch"}, "decision_scores": {0: "batch"}, "embedding": {0: "batch"}})
    write(output / "training-lock.json", {"artifacts": {name: sha(output / name) for name in
          ["experiment-plan.json", "development-manifest.json", "best.pt", "best.onnx", "development.npz", "history.jsonl", "metrics.json", "selected.json", "epoch-curves.png"]},
          "test_images_opened": 0, "gate_calibration_pending": True, "field_accuracy_established": False})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--patience", type=int, default=8)
    args = parser.parse_args()
    if args.epochs < 1 or args.patience < 1:
        parser.error("Epochs and patience must be positive")
    train(args)
