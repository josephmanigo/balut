from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a gated float checkpoint to fixed-shape ONNX opset 18")
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        import torch
        from torchvision import models
    except ImportError as error:
        raise SystemExit("PyTorch and torchvision are required for export") from error

    payload = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    if payload.get("class_order") != ["DAY_16_LIKE", "DAY_18_LIKE", "REJECT_SUSPECT"]:
        raise SystemExit("checkpoint class order is incompatible")
    input_size = int(payload["input_size"])
    model = models.mobilenet_v2(weights=None, width_mult=0.35, num_classes=3)
    model.load_state_dict(payload["state_dict"])
    model.eval()
    dummy = torch.zeros(1, 3, input_size, input_size)
    torch.onnx.export(
        model,
        dummy,
        args.output,
        input_names=["rgb_input"],
        output_names=["appearance_logits"],
        opset_version=18,
        dynamo=False,
    )
    print(f"wrote {args.output}; ESP-DL conversion and physical known-answer parity are still required")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
