"""Portable frozen-feature classifiers for exploratory source labels."""
from __future__ import annotations

import os
from pathlib import Path

import torch
from torch import nn
from torch.nn import functional as F
from torchvision import models, transforms

DINO_REVISION = "7764ea0f912e53c92e82eb78a2a1631e92725fc8"
MEAN = [0.485, 0.456, 0.406]
STD = [0.229, 0.224, 0.225]


def build_backbone(name: str, pretrained: bool = False):
    if name == "dinov2_vits14":
        os.environ["XFORMERS_DISABLED"] = "1"
        vendored = Path(__file__).resolve().parent.parent / "vendor" / "dinov2"
        if vendored.is_dir():
            return torch.hub.load(str(vendored), name, source="local", pretrained=pretrained)
        return torch.hub.load(f"facebookresearch/dinov2:{DINO_REVISION}", name,
                              pretrained=pretrained, trust_repo=True)
    if name == "convnext_tiny":
        model = models.convnext_tiny(weights=models.ConvNeXt_Tiny_Weights.IMAGENET1K_V1 if pretrained else None)
        model.classifier[-1] = nn.Identity()
        return model
    if name == "efficientnet_b0":
        model = models.efficientnet_b0(weights=models.EfficientNet_B0_Weights.IMAGENET1K_V1 if pretrained else None)
        model.classifier = nn.Identity()
        return model
    raise ValueError(f"Unknown backbone: {name}")


def image_transform():
    return transforms.Compose([transforms.Resize((224, 224)), transforms.ToTensor(), transforms.Normalize(MEAN, STD)])


class FeatureEncoder(nn.Module):
    def __init__(self, backbone):
        super().__init__()
        self.backbone = backbone

    def forward(self, images):
        # A fixed view policy shared by training, validation, test, and deployment.
        features = (self.backbone(images) + self.backbone(torch.flip(images, dims=[3]))) * 0.5
        return F.normalize(features, p=2, dim=1)


class LinearHead(nn.Module):
    def __init__(self, feature_dim: int, outputs: int):
        super().__init__()
        self.linear = nn.Linear(feature_dim, outputs)
        self.binary = outputs == 1

    def forward(self, features):
        scores = self.linear(features)
        return torch.cat([torch.zeros_like(scores), scores], dim=1) if self.binary else scores


class RBFDecision(nn.Module):
    def __init__(self, count: int, feature_dim: int):
        super().__init__()
        self.register_buffer("vectors", torch.zeros(count, feature_dim))
        self.register_buffer("dual", torch.zeros(count))
        self.register_buffer("intercept", torch.zeros(1))
        self.register_buffer("gamma", torch.ones(1))

    def forward(self, features):
        distance = (features.square().sum(1, keepdim=True) + self.vectors.square().sum(1).unsqueeze(0)
                    - 2 * features @ self.vectors.T).clamp_min(0)
        return torch.exp(-self.gamma * distance) @ self.dual + self.intercept


class RBFHead(nn.Module):
    def __init__(self, feature_dim: int, support_counts: list[int]):
        super().__init__()
        self.decisions = nn.ModuleList([RBFDecision(n, feature_dim) for n in support_counts])

    def forward(self, features):
        scores = torch.stack([decision(features) for decision in self.decisions], dim=1)
        return torch.cat([torch.zeros_like(scores), scores], dim=1) if len(self.decisions) == 1 else scores


def build_head(spec: dict):
    if spec["kind"] == "logistic":
        return LinearHead(spec["feature_dim"], spec["outputs"])
    if spec["kind"] == "rbf_ovr":
        return RBFHead(spec["feature_dim"], spec["support_counts"])
    raise ValueError("Unknown head type")


def portable_head(estimator, kind: str):
    if kind == "logistic":
        spec = {"kind": kind, "feature_dim": estimator.coef_.shape[1], "outputs": estimator.coef_.shape[0]}
        head = build_head(spec)
        with torch.no_grad():
            head.linear.weight.copy_(torch.as_tensor(estimator.coef_, dtype=torch.float32))
            head.linear.bias.copy_(torch.as_tensor(estimator.intercept_, dtype=torch.float32))
    elif kind == "rbf_ovr":
        spec = {"kind": kind, "feature_dim": estimator.n_features_in_,
                "support_counts": [len(e.support_vectors_) for e in estimator.estimators_]}
        head = build_head(spec)
        for target, source in zip(head.decisions, estimator.estimators_):
            target.vectors.copy_(torch.as_tensor(source.support_vectors_, dtype=torch.float32))
            target.dual.copy_(torch.as_tensor(source.dual_coef_[0], dtype=torch.float32))
            target.intercept.copy_(torch.as_tensor(source.intercept_, dtype=torch.float32))
            target.gamma.fill_(source._gamma)
    else:
        raise ValueError("Unknown head type")
    return head.eval(), spec


class SourceClassifier(nn.Module):
    def __init__(self, encoder, head):
        super().__init__()
        self.encoder = encoder
        self.head = head

    def forward(self, images):
        return self.head(self.encoder(images))


class FusedEncoder(nn.Module):
    def __init__(self, encoders):
        super().__init__()
        self.encoders = nn.ModuleList(encoders)

    def forward(self, images):
        return torch.cat([encoder(images) for encoder in self.encoders], dim=1) / len(self.encoders) ** 0.5


class SelectiveClassifier(SourceClassifier):
    def forward(self, images):
        features = self.encoder(images)
        return self.head(features), features


def load_classifier(checkpoint: Path):
    payload = torch.load(checkpoint, weights_only=True, map_location="cpu")
    config = payload["config"]
    if config["status"] != "EXPLORATORY_FROZEN_FEATURE_CLASSIFIER" or config["operational_use_authorized"]:
        raise ValueError("Unexpected checkpoint contract")
    if config.get("selective_inference"):
        model = SelectiveClassifier(FusedEncoder([FeatureEncoder(build_backbone(name)) for name in config["backbones"]]), build_head(config["head"]))
    else:
        model = SourceClassifier(FeatureEncoder(build_backbone(config["backbone"])), build_head(config["head"]))
    model.load_state_dict(payload["state_dict"])
    return model.eval(), config
