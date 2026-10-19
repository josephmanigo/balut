"""Fixed, exportable full-image/interior feature representations."""
import math
from pathlib import Path
import torch
from torch import nn

from .feature_models import FeatureEncoder,build_backbone
from .search_camera_representation import INTERIOR,interior_view

ROOT=Path(__file__).resolve().parents[2]
BACKBONES={"dino":"dinov2_vits14","efficient":"efficientnet_b0","convnext":"convnext_tiny"}
SPECS={
    "fused-full":[("dino","full"),("efficient","full")],
    "fused-interior":[("dino","interior"),("efficient","interior")],
    "convnext-efficient-interior":[("convnext","interior"),("efficient","interior")],
    **{f"{name}-{view}":[(name,view)] for name in BACKBONES for view in ("full","interior")},
    **{f"{name}-dual":[(name,"full"),(name,"interior")] for name in BACKBONES},
}


class CameraRepresentation(nn.Module):
    def __init__(self,profile,encoders):
        super().__init__()
        if profile not in SPECS:raise ValueError("Unknown camera representation")
        self.pairs=SPECS[profile]
        self.encoders=nn.ModuleDict(encoders)
        if set(self.encoders)!=set(name for name,_ in self.pairs):raise ValueError("Incomplete representation encoders")

    def forward(self,images):
        values=[self.encoders[name](interior_view(images) if view=="interior" else images) for name,view in self.pairs]
        return torch.cat(values,dim=1)/math.sqrt(len(values))


def load_representation(profile):
    encoders={}
    for name in sorted({name for name,_ in SPECS[profile]}):
        backbone=BACKBONES[name]
        encoder=FeatureEncoder(build_backbone(backbone))
        encoder.load_state_dict(torch.load(ROOT/"ml/runs/accuracy-v2"/(backbone+"-encoder.pt"),weights_only=True,map_location="cpu"))
        encoders[name]=encoder
    return CameraRepresentation(profile,encoders).eval()


def unfreeze_tail(encoder):
    for p in encoder.parameters():p.requires_grad_(False)
    for name,unit in encoder.encoders.items():
        backbone=unit.backbone
        blocks=([backbone.blocks[-2:],backbone.norm] if name=="dino" else
                [backbone.features[-2:],backbone.classifier[0]] if name=="convnext" else [backbone.features[-3:]])
        for block in blocks:
            for p in block.parameters():p.requires_grad_(True)


def patch_state(model):return {name:p.detach().cpu().clone() for name,p in model.named_parameters() if p.requires_grad}


def restore_patch(model,patch):
    expected={name for name,p in model.named_parameters() if p.requires_grad}
    if set(patch)!=expected:raise ValueError("Adapted parameter names differ from declared training scope")
    with torch.no_grad():
        for name,p in model.named_parameters():
            if name in patch:p.copy_(patch[name])
