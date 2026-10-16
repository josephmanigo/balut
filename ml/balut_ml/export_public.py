"""Export a public-source checkpoint to float32 ONNX and verify CPU parity."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    args = parser.parse_args()
    import numpy as np
    import onnx
    import onnxruntime as ort
    import torch
    from PIL import Image, ImageOps
    from torch import nn
    from torchvision import models, transforms
    torch.set_num_threads(4)
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    config = checkpoint["config"]
    if config["status"] != "EXPLORATORY_PUBLIC_SOURCE_CLASSIFIER" or config["operational_use_authorized"]:
        raise ValueError("Unexpected checkpoint contract")
    model = models.mobilenet_v3_small(weights=None)
    model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, len(config["class_order"]))
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    torch.manual_seed(42)
    dummy = torch.randn(1, 3, config["input_size"], config["input_size"])
    # Keep the exported artifact next to its matching checkpoint.
    output = args.checkpoint.with_suffix(".onnx")
    torch.onnx.export(model, dummy, str(output), input_names=["images"], output_names=["logits"],
                      dynamic_axes={"images": {0: "batch"}, "logits": {0: "batch"}}, opset_version=18, dynamo=False)
    onnx.checker.check_model(str(output))
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    session = ort.InferenceSession(str(output), sess_options=options, providers=["CPUExecutionProvider"])
    transform = transforms.Compose([transforms.Resize((config["input_size"], config["input_size"])), transforms.ToTensor(),
                                    transforms.Normalize(config["normalization_mean"], config["normalization_std"])])
    rows = [json.loads(line) for line in Path(config["manifest"]).read_text(encoding="utf-8").splitlines()]
    test_rows = [row for row in rows if row["partition"] == "test"]
    max_error, agreement = 0.0, 0
    with torch.inference_mode():
        for row in test_rows:
            with Image.open(row["image_path"]) as original:
                tensor = transform(ImageOps.exif_transpose(original).convert("RGB")).unsqueeze(0)
            native = model(tensor).numpy()
            exported = session.run(["logits"], {"images": tensor.numpy()})[0]
            max_error = max(max_error, float(np.abs(native - exported).max()))
            agreement += int(native.argmax(1)[0] == exported.argmax(1)[0])
    report = {"onnx_file": str(output.resolve()), "onnx_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
              "format": "float32 ONNX opset 18", "input": "NCHW RGB resized to 224x224 then ImageNet normalization",
              "output": "source-class logits; apply softmax for uncalibrated probabilities",
              "class_order": config["class_order"], "test_images_compared": len(test_rows),
              "argmax_agreement_count": agreement, "maximum_absolute_logit_error": max_error,
              "passed": agreement == len(test_rows) and max_error < 1e-4,
              "operational_use_authorized": False, "esp32_int8_validated": False}
    output.with_name("onnx-parity.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit("ONNX parity failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
