"""Predict original source classes with an exploratory checkpoint."""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    import torch
    from PIL import Image, ImageOps
    from torch import nn
    from torchvision import models, transforms
    torch.set_num_threads(4)
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    config = checkpoint["config"]
    if config["status"] == "EXPLORATORY_FROZEN_FEATURE_CLASSIFIER":
        from .feature_models import image_transform, load_classifier
        model, config = load_classifier(args.checkpoint)
        with Image.open(args.image) as original:
            tensor = image_transform()(ImageOps.exif_transpose(original).convert("RGB")).unsqueeze(0)
        with torch.inference_mode():
            scores = model(tensor)[0].tolist()
        print(json.dumps({"status": "EXPLORATORY_ONLY", "backbone": config["backbone"],
                          "source_prediction": config["class_order"][scores.index(max(scores))],
                          "source_class_decision_scores": dict(zip(config["class_order"], scores)),
                          "operational_outcome": "REVIEW_RECAPTURE", "operational_use_authorized": False,
                          "note": config["output_semantics"]}, indent=2))
        return 0
    if config["status"] != "EXPLORATORY_PUBLIC_SOURCE_CLASSIFIER" or config["operational_use_authorized"]:
        raise ValueError("Unexpected checkpoint contract")
    model = models.mobilenet_v3_small(weights=None)
    model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, len(config["class_order"]))
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    transform = transforms.Compose([transforms.Resize((config["input_size"], config["input_size"])), transforms.ToTensor(),
                                    transforms.Normalize(config["normalization_mean"], config["normalization_std"])])
    with Image.open(args.image) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
    with torch.inference_mode():
        probabilities = model(transform(image).unsqueeze(0)).softmax(1)[0].tolist()
    print(json.dumps({"status": "EXPLORATORY_ONLY", "source_prediction": config["class_order"][probabilities.index(max(probabilities))],
                      "source_class_probabilities": dict(zip(config["class_order"], probabilities)),
                      "operational_outcome": "REVIEW_RECAPTURE", "operational_use_authorized": False,
                      "note": "Uncalibrated source-class scores; no verified age, viability, or food-safety determination."}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
