"""Optional physical-dataset training entry point.

This module deliberately refuses to train until a manifest passes the leakage
and provenance audit. PyTorch and Pillow are optional, heavy dependencies and
are imported only after that gate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .dataset import audit_manifest, read_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(description="Train the MobileNetV2-0.35 Balut appearance baseline")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--input-size", type=int, choices=(96, 128), default=128)
    args = parser.parse_args()

    report = audit_manifest(args.manifest, require_files=True)
    if not report.valid:
        print(json.dumps(report.as_dict(), indent=2))
        raise SystemExit("training blocked: dataset manifest audit failed")
    if "prospective_test" not in report.partition_counts:
        raise SystemExit("training blocked: prospective-test partition has not been designated")

    try:
        import torch
        from PIL import Image
        from torch import nn
        from torch.utils.data import DataLoader, Dataset
        from torchvision import models, transforms
    except ImportError as error:
        raise SystemExit(
            "training dependencies are not installed; provision ml/requirements-training.txt"
        ) from error

    labels = {"DAY_16_LIKE": 0, "DAY_18_LIKE": 1, "REJECT_SUSPECT": 2}
    rows = [row for row in read_jsonl(args.manifest) if row.partition in {"train", "validation"}]
    root = args.manifest.parent
    train_transform = transforms.Compose([
        transforms.Resize((args.input_size, args.input_size)),
        transforms.ColorJitter(brightness=0.08, contrast=0.08),
        transforms.ToTensor(),
        transforms.Normalize([0.5] * 3, [0.5] * 3),
    ])
    evaluation_transform = transforms.Compose([
        transforms.Resize((args.input_size, args.input_size)),
        transforms.ToTensor(),
        transforms.Normalize([0.5] * 3, [0.5] * 3),
    ])

    class ManifestDataset(Dataset):
        def __init__(self, split: str) -> None:
            self.rows = [row for row in rows if row.partition == split]
            self.transform = train_transform if split == "train" else evaluation_transform

        def __len__(self) -> int:
            return len(self.rows)

        def __getitem__(self, index: int):
            row = self.rows[index]
            image = Image.open(root / row.image_path).convert("RGB")
            return self.transform(image), labels[row.label], row.inspection_id

    train_data = ManifestDataset("train")
    validation_data = ManifestDataset("validation")
    if len(train_data) == 0 or len(validation_data) == 0:
        raise SystemExit("training blocked: train and validation partitions must both contain frames")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = models.mobilenet_v2(weights=None, width_mult=0.35, num_classes=3).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=1e-4)
    criterion = nn.CrossEntropyLoss()
    train_loader = DataLoader(train_data, batch_size=32, shuffle=True, num_workers=0)
    validation_loader = DataLoader(validation_data, batch_size=32, shuffle=False, num_workers=0)
    best_loss = float("inf")
    args.output.mkdir(parents=True, exist_ok=True)

    for epoch in range(args.epochs):
        model.train()
        for images, targets, _session_ids in train_loader:
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(images.to(device)), targets.to(device))
            loss.backward()
            optimizer.step()

        model.eval()
        validation_loss = 0.0
        with torch.no_grad():
            for images, targets, _session_ids in validation_loader:
                validation_loss += criterion(model(images.to(device)), targets.to(device)).item()
        validation_loss /= max(1, len(validation_loader))
        print(f"epoch={epoch + 1} validation_frame_loss={validation_loss:.6f}")
        if validation_loss < best_loss:
            best_loss = validation_loss
            torch.save({
                "state_dict": model.state_dict(),
                "input_size": args.input_size,
                "class_order": list(labels),
                "dataset_manifest_sha256": report.manifest_sha256,
                "validation_frame_loss": best_loss,
            }, args.output / "best_float.pt")

    print("Float checkpoint produced. Egg-session metrics, calibration, int8 conversion, ESP-DL parity, and prospective testing remain separate release gates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
