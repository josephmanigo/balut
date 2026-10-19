"""Fine-tune the retained encoder's final blocks using training images only."""
import copy
import json
import os
from pathlib import Path
import random
import time

import numpy as np
from .train_epoch_head import ROOT, PARENT, DATA, CLASSES, sha, write, metrics, groups_report
from .train_unfertilized import fit_weights

RUN = ROOT / "ml/runs/finetuned-epochs-reject-20261019"


def main():
    if RUN.exists():
        raise FileExistsError("Preserve the completed or interrupted image-training run")
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    import torch
    from torch import nn
    from torch.utils.data import Dataset, DataLoader
    from torchvision import transforms
    from PIL import Image, ImageOps
    from .feature_models import load_classifier, MEAN, STD
    random.seed(42); np.random.seed(42); torch.manual_seed(42)
    torch.set_num_threads(4)
    torch.use_deterministic_algorithms(True)
    torch.backends.cudnn.benchmark = False
    if not torch.cuda.is_available():
        raise RuntimeError("This fixed fine-tuning protocol requires the available CUDA GPU")
    rows = [json.loads(line) for line in (DATA / "manifest.jsonl").read_text().splitlines()]
    audit = json.loads((DATA / "audit.json").read_text())
    assert sha(DATA / "manifest.jsonl") == audit["manifest_sha256"]
    train_rows = [row for row in rows if row["partition"] == "train"]
    val_rows = [row for row in rows if row["partition"] == "validation"]
    assert len(train_rows) == 2256 and len(val_rows) == 814
    provenance = json.loads((PARENT / "validation-inputs.json").read_text())
    canonical = {item["source_sha256"]: item for item in provenance}
    normalized = transforms.Compose([transforms.ToTensor(), transforms.Normalize(MEAN, STD)])
    augmented = transforms.Compose([transforms.RandomRotation(8), transforms.ColorJitter(brightness=.08, contrast=.08), normalized])
    class Images(Dataset):
        def __init__(self, items, training):
            self.items, self.transform = items, augmented if training else normalized
            self.weights = fit_weights(items, 20).astype(np.float32) if training else np.ones(len(items), dtype=np.float32)
            self.images = []
            for row in items:
                path = Path(row["image_path"]) if training else Path(canonical[row["source_sha256"]]["path"])
                assert sha(path) == (row["source_sha256"] if training else canonical[row["source_sha256"]]["serving_jpeg_sha256"])
                with Image.open(path) as image:
                    self.images.append(ImageOps.exif_transpose(image).convert("RGB").resize((224, 224), Image.Resampling.BILINEAR))
        def __len__(self): return len(self.items)
        def __getitem__(self, index):
            return self.transform(self.images[index]), CLASSES.index(self.items[index]["training_label"]), self.weights[index]
    train_data, val_data = Images(train_rows, True), Images(val_rows, False)
    generator = torch.Generator().manual_seed(42)
    loaders = {"train": DataLoader(train_data, batch_size=16, shuffle=True, num_workers=0, generator=generator, pin_memory=True),
               "validation": DataLoader(val_data, batch_size=16, shuffle=False, num_workers=0, pin_memory=True)}
    base = ROOT / "ml/runs/selective-v2/best.pt"
    model, config = load_classifier(base)
    with np.load(PARENT / "head.npz", allow_pickle=False) as bank, torch.no_grad():
        model.head.linear.weight.copy_(torch.from_numpy(bank["coefficient"]) * .25)
        model.head.linear.bias.copy_(torch.from_numpy(bank["intercept"]) * .25)
    for parameter in model.parameters(): parameter.requires_grad_(False)
    blocks = [model.encoder.encoders[0].backbone.blocks[-2:], model.encoder.encoders[1].backbone.features[-2:]]
    for block in [*blocks, model.head]:
        for parameter in block.parameters(): parameter.requires_grad_(True)
    model.cuda().eval()
    optimizer = torch.optim.AdamW([{"params": [p for block in blocks for p in block.parameters()], "lr": 1e-5},
                                  {"params": model.head.parameters(), "lr": 5e-4}], weight_decay=.01)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, 15, eta_min=1e-6)
    protected = {str(path.relative_to(ROOT)): sha(path) for path in
                 [Path(__file__), ROOT / "ml/balut_ml/feature_models.py", base, PARENT / "head.npz", DATA / "manifest.jsonl"]}
    RUN.mkdir()
    config.update(status="EXPLORATORY_EPOCH_FINETUNED_CLASSIFIER", class_order=CLASSES,
                  training_method="FINAL_ENCODER_BLOCKS_AND_HEAD_EPOCH_FINETUNING", operational_use_authorized=False,
                  manifest_sha256=audit["manifest_sha256"])
    write(RUN / "experiment-plan.json", {"epochs_maximum": 15, "patience": 5, "batch_size": 16, "seed": 42,
          "encoder_learning_rate": 1e-5, "head_learning_rate": 5e-4, "weight_decay": .01,
          "trainable_layers": "Last two DINOv2 transformer blocks, last two EfficientNet feature blocks, classifier head",
          "normalization_state": "Frozen batch-normalization statistics; gradients enabled only in declared blocks",
          "initial_head": "Current deployed classifier scores scaled by 0.25; initial argmax unchanged",
          "augmentations": "Training only: rotation +/-8 degrees, brightness/contrast +/-8%; no label-changing crops",
          "weighting": "Equal effective class weight and weight20 per physical training egg shared across views",
          "selection": "Mean raw recall over five validation source/camera class groups; then minimum camera-age recall, macro F1 and lower validation loss",
          "test_policy": "No test-image fitting or selection; prior 649-image test can only be a later historical regression",
          "prior_experiment": "retained-epochs-selective-reject-20261019 failed historical regression; no historical images enter this run",
          "label_scope": "Reject output name uses source Unfertilized examples only; no general defect or food-safety validation",
          "protected_files": protected})
    best_key, best_epoch, stale = None, 0, 0
    started = time.perf_counter()
    for epoch in range(1, 16):
        # Evaluation mode preserves pretrained normalization while declared weights still receive gradients.
        model.eval()
        train_scores, train_truth = [], []
        objective = 0.
        for batch, (images, targets, weights) in enumerate(loaders["train"], 1):
            images, targets, weights = images.cuda(), targets.cuda(), weights.cuda()
            optimizer.zero_grad(set_to_none=True)
            scores, _ = model(images)
            loss = (nn.functional.cross_entropy(scores, targets, reduction="none") * weights).mean()
            loss.backward()
            nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 5.)
            optimizer.step()
            train_scores.extend(scores.detach().cpu().numpy())
            train_truth.extend(targets.cpu().numpy())
            objective += float(loss.detach()) * len(targets)
            if batch % 20 == 0:
                progress = {"epoch": epoch, "training_batch": batch, "batches": len(loaders["train"]), "elapsed_seconds": time.perf_counter() - started}
                write(RUN / "progress.json", progress)
                print(json.dumps(progress), flush=True)
        validation_scores = []
        with torch.inference_mode():
            for images, _, _ in loaders["validation"]:
                scores, _ = model(images.cuda())
                validation_scores.extend(scores.cpu().numpy())
        scores = np.asarray(validation_scores)
        val_truth = np.array([CLASSES.index(row["training_label"]) for row in val_rows])
        train_metrics = metrics(np.asarray(train_scores), np.asarray(train_truth))
        validation_metrics = metrics(scores, val_truth)
        groups = groups_report(val_rows, scores)
        mean_recall = float(np.mean([g["raw_correct"] / g["images"] for g in groups.values()]))
        key = (mean_recall, min(groups[f"camera:{label}"]["raw_correct"] / 270 for label in CLASSES[:2]), validation_metrics["f1"], -validation_metrics["loss"])
        record = {"epoch": epoch, "learning_rate": optimizer.param_groups[0]["lr"], "weighted_training_objective": objective / len(train_rows),
                  "train": train_metrics, "validation": validation_metrics, "validation_group_score": mean_recall, "validation_groups": groups}
        with (RUN / "history.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, allow_nan=False) + "\n")
        if best_key is None or key > best_key:
            best_key, best_epoch, stale = key, epoch, 0
            torch.save({"state_dict": {name: value.detach().cpu() for name, value in model.state_dict().items()}, "config": config}, RUN / "best.pt")
            write(RUN / "selected-validation.json", record)
            np.savez_compressed(RUN / "selected-validation.npz", scores=scores, truth=val_truth)
        else:
            stale += 1
        print(json.dumps({"completed_epoch": epoch, "train_loss": train_metrics["loss"], "validation_loss": validation_metrics["loss"],
                          "validation_accuracy": validation_metrics["accuracy"], "group_score": mean_recall,
                          "best_epoch": best_epoch, "elapsed_seconds": time.perf_counter() - started}), flush=True)
        scheduler.step()
        if stale >= 5: break
    assert all(sha(ROOT / name) == digest for name, digest in protected.items())
    write(RUN / "training-summary.json", {"epochs_completed": epoch, "selected_epoch": best_epoch,
          "elapsed_seconds": time.perf_counter() - started, "trainable_parameters": sum(p.numel() for p in model.parameters() if p.requires_grad),
          "test_images_opened": 0, "selected_validation": json.loads((RUN / "selected-validation.json").read_text())})
    names = ["experiment-plan.json", "history.jsonl", "best.pt", "selected-validation.json", "selected-validation.npz", "training-summary.json"]
    write(RUN / "training-lock.json", {"artifacts": {name: sha(RUN / name) for name in names}})
    print(json.dumps({"completed": True, "epochs_completed": epoch, "selected_epoch": best_epoch}), flush=True)


if __name__ == "__main__":
    main()
