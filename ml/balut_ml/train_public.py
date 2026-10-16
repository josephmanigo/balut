"""Train an exploratory public-source classifier; never activate device decisions."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import time
from pathlib import Path


def load_audited_rows(manifest: Path) -> tuple[list[dict], dict]:
    audit = json.loads(manifest.with_name("audit.json").read_text(encoding="utf-8"))
    if audit.get("status") != "EXPLORATORY_PUBLIC_DATA_ONLY":
        raise ValueError("Expected an exploratory public-source audit")
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != audit["manifest_sha256"]:
        raise ValueError("Manifest changed since audit")
    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()]
    groups, hashes = {}, {}
    for row in rows:
        partition = row["partition"]
        if partition not in {"train", "validation", "test"}:
            raise ValueError("Unknown partition")
        for key, seen in (("duplicate_group", groups), ("pixel_sha256", hashes)):
            if row[key] in seen and seen[row[key]] != partition:
                raise ValueError(f"Leakage across partitions: {key}")
            seen[row[key]] = partition
        path = Path(row["image_path"])
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row["source_sha256"]:
            raise ValueError(f"Missing or changed image: {path}")
    classes = {r["source_label"] for r in rows}
    if len(classes) < 2:
        raise ValueError("At least two classes are required")
    for partition in ("train", "validation", "test"):
        if {r["source_label"] for r in rows if r["partition"] == partition} != classes:
            raise ValueError(f"Missing class in {partition}")
    return rows, audit


def evaluate(model, loader, criterion, device, classes):
    import torch
    from sklearn.metrics import accuracy_score, balanced_accuracy_score, classification_report, confusion_matrix, f1_score
    model.eval()
    truth, predictions, probabilities, indexes = [], [], [], []
    loss_sum = 0.0
    with torch.inference_mode():
        for images, targets, sample_indexes in loader:
            logits = model(images.to(device))
            loss_sum += criterion(logits, targets.to(device)).item() * len(targets)
            probs = logits.softmax(1).cpu()
            truth.extend(targets.tolist())
            predictions.extend(probs.argmax(1).tolist())
            probabilities.extend(probs.tolist())
            indexes.extend(sample_indexes.tolist())
    metrics = {"image_count": len(truth), "loss": loss_sum / len(truth),
               "accuracy": accuracy_score(truth, predictions),
               "balanced_accuracy": balanced_accuracy_score(truth, predictions),
               "macro_f1": f1_score(truth, predictions, average="macro", zero_division=0),
               "confusion_matrix": confusion_matrix(truth, predictions, labels=list(range(len(classes)))).tolist(),
               "per_class": classification_report(truth, predictions, labels=list(range(len(classes))), target_names=classes, output_dict=True, zero_division=0)}
    return metrics, [{"row_index": idx, "true_source_label": classes[y], "predicted_source_label": classes[p], "probabilities": dict(zip(classes, probs))}
                     for idx, y, p, probs in zip(indexes, truth, predictions, probabilities)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=25)
    parser.add_argument("--patience", type=int, default=7)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.epochs < 1 or args.batch_size < 1 or args.patience < 1:
        parser.error("epochs, batch size, and patience must be positive")
    if args.output.exists():
        parser.error("Use a fresh output directory to preserve earlier experiments")
    rows, audit = load_audited_rows(args.manifest)
    # Heavy imports follow the integrity checks.
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    import numpy as np
    import torch
    import torchvision
    from PIL import Image, ImageOps
    from torch import nn
    from torch.utils.data import DataLoader, Dataset
    from torchvision import models, transforms
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = False
    torch.use_deterministic_algorithms(True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    classes = sorted({row["source_label"] for row in rows})
    class_ids = {label: i for i, label in enumerate(classes)}
    normalization = transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])
    evaluation_transform = transforms.Compose([transforms.Resize((224, 224)), transforms.ToTensor(), normalization])
    training_transform = transforms.Compose([transforms.Resize((224, 224)), transforms.RandomHorizontalFlip(),
                                             transforms.RandomRotation(10), transforms.ColorJitter(brightness=0.08, contrast=0.08),
                                             transforms.ToTensor(), normalization])

    class Images(Dataset):
        def __init__(self, partition):
            self.items = [(i, row) for i, row in enumerate(rows) if row["partition"] == partition]
            self.transform = training_transform if partition == "train" else evaluation_transform

        def __len__(self):
            return len(self.items)

        def __getitem__(self, index):
            original_index, row = self.items[index]
            with Image.open(row["image_path"]) as original:
                image = ImageOps.exif_transpose(original).convert("RGB")
            return self.transform(image), class_ids[row["source_label"]], original_index

    loaders = {p: DataLoader(Images(p), batch_size=args.batch_size, shuffle=p == "train", num_workers=0,
                            generator=torch.Generator().manual_seed(args.seed), pin_memory=device.type == "cuda")
               for p in ("train", "validation")}
    model = models.mobilenet_v3_small(weights=models.MobileNet_V3_Small_Weights.IMAGENET1K_V1)
    model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, len(classes))
    model = model.to(device)
    optimizer = torch.optim.AdamW([{"params": model.features.parameters(), "lr": 3e-5},
                                  {"params": model.classifier.parameters(), "lr": 3e-4}], weight_decay=1e-4)
    criterion = nn.CrossEntropyLoss()
    args.output.mkdir(parents=True)
    config = {"status": "EXPLORATORY_PUBLIC_SOURCE_CLASSIFIER", "architecture": "mobilenet_v3_small",
              "initial_weights": "MobileNet_V3_Small_Weights.IMAGENET1K_V1", "input_size": 224, "class_order": classes,
              "normalization_mean": [0.485, 0.456, 0.406], "normalization_std": [0.229, 0.224, 0.225],
              "manifest_sha256": audit["manifest_sha256"], "manifest": str(args.manifest.resolve()),
              "seed": args.seed, "max_epochs": args.epochs, "early_stopping_patience": args.patience,
              "device": str(device), "gpu": torch.cuda.get_device_name(0) if device.type == "cuda" else None,
              "python": platform.python_version(), "torch": str(torch.__version__), "torchvision": str(torchvision.__version__),
              "operational_use_authorized": False, "provenance": audit["provenance"], "limitations": audit["limitations"]}
    (args.output / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    best_loss, best_epoch, stale = float("inf"), 0, 0
    start = time.monotonic()
    for epoch in range(1, args.epochs + 1):
        model.train()
        # First three epochs adapt the classification head; then fine-tune features.
        frozen = epoch <= 3
        for param in model.features.parameters():
            param.requires_grad_(not frozen)
        if frozen:
            model.features.eval()
        train_loss, seen = 0.0, 0
        for images, targets, _ in loaders["train"]:
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(images.to(device)), targets.to(device))
            loss.backward()
            optimizer.step()
            train_loss += loss.item() * len(targets)
            seen += len(targets)
        validation, _ = evaluate(model, loaders["validation"], criterion, device, classes)
        record = {"epoch": epoch, "train_loss": train_loss / seen, "validation": validation,
                  "elapsed_seconds": time.monotonic() - start}
        with (args.output / "history.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        print(json.dumps({"epoch": epoch, "train_loss": round(train_loss / seen, 4),
                          "val_loss": round(validation["loss"], 4), "val_accuracy": round(validation["accuracy"], 4)}), flush=True)
        if validation["loss"] < best_loss:
            best_loss, best_epoch, stale = validation["loss"], epoch, 0
            torch.save({"state_dict": model.state_dict(), "config": config, "best_epoch": epoch,
                        "validation_loss": best_loss}, args.output / "best.pt")
        else:
            stale += 1
        if stale >= args.patience:
            break
    checkpoint = torch.load(args.output / "best.pt", map_location=device, weights_only=True)
    model.load_state_dict(checkpoint["state_dict"])
    validation, _ = evaluate(model, loaders["validation"], criterion, device, classes)
    # Test images are loaded for inference only after checkpoint selection is complete.
    test_loader = DataLoader(Images("test"), batch_size=args.batch_size, shuffle=False, num_workers=0)
    test, predictions = evaluate(model, test_loader, criterion, device, classes)
    for prediction in predictions:
        prediction["image_path"] = rows[prediction.pop("row_index")]["image_path"]
    metrics = {"status": "TRAINED_EXPLORATORY_ONLY", "best_epoch": best_epoch, "epochs_completed": epoch,
               "elapsed_seconds": time.monotonic() - start, "class_order": classes, "validation": validation, "test": test,
               "majority_class_test_baseline": max(np.bincount([class_ids[r["source_label"]] for r in rows if r["partition"] == "test"])) / test["image_count"],
               "checkpoint_sha256": hashlib.sha256((args.output / "best.pt").read_bytes()).hexdigest(),
               "limitations": audit["limitations"], "operational_use_authorized": False}
    (args.output / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    (args.output / "test-predictions.jsonl").write_text("".join(json.dumps(p) + "\n" for p in predictions), encoding="utf-8")
    print(json.dumps(metrics, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
