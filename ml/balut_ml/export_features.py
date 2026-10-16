"""Export a selected feature classifier and compare representations on fixed inputs."""
from __future__ import annotations
import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch
from PIL import Image, ImageOps

from .benchmark_public import TASKS
from .feature_models import image_transform, load_classifier


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    torch.set_num_threads(4)
    model, config = load_classifier(args.checkpoint)
    task = args.checkpoint.parent.name
    manifest = args.manifest or Path(TASKS[task][0])
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != config["manifest_sha256"]:
        raise ValueError("Manifest changed")
    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
    frozen = np.load(args.checkpoint.with_name("selected-test.npz"))
    indexes, reference_scores = frozen["indexes"], frozen["scores"]
    if any(rows[i]["partition"] != "test" for i in indexes):
        raise ValueError("Expected historical test inputs for parity")
    output = args.checkpoint.with_suffix(".onnx")
    torch.manual_seed(42)
    with torch.inference_mode():
        torch.onnx.export(model, torch.randn(1, 3, 224, 224), str(output), input_names=["images"],
                          output_names=["decision_scores"], dynamic_axes={"images": {0: "batch"}, "decision_scores": {0: "batch"}},
                          opset_version=18, dynamo=False)
    onnx.checker.check_model(str(output))
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    session = ort.InferenceSession(str(output), sess_options=options, providers=["CPUExecutionProvider"])
    transform = image_transform()
    errors, cpu_agreement, onnx_agreement, runtimes = [], 0, 0, []
    for start in range(0, len(indexes), 8):
        tensors = []
        for index in indexes[start:start+8]:
            with Image.open(rows[index]["image_path"]) as original:
                tensors.append(transform(ImageOps.exif_transpose(original).convert("RGB")))
        images = torch.stack(tensors)
        with torch.inference_mode():
            native = model(images).numpy()
        began = time.perf_counter()
        exported = session.run(["decision_scores"], {"images": images.numpy()})[0]
        runtimes.append(time.perf_counter() - began)
        original_scores = reference_scores[start:start+len(images)]
        errors.append(float(np.abs(native-exported).max()))
        cpu_agreement += int(np.sum(native.argmax(1) == original_scores.argmax(1)))
        onnx_agreement += int(np.sum(exported.argmax(1) == original_scores.argmax(1)))
    report = {"passed": cpu_agreement == onnx_agreement == len(indexes) and max(errors) < 1e-4,
              "onnx_sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "test_images_compared": len(indexes),
              "cpu_torch_matches_frozen_gpu_count": cpu_agreement, "onnx_matches_frozen_gpu_count": onnx_agreement,
              "maximum_absolute_torch_onnx_score_error": max(errors),
              "onnx_cpu_batch8_ms_per_image": sum(runtimes) / len(indexes) * 1000,
              "format": "float32 ONNX opset 18", "input": "RGB NCHW 224x224 ImageNet normalization; horizontal flip ensemble is inside graph",
              "output": config["output_semantics"], "class_order": config["class_order"],
              "operational_use_authorized": False, "esp32_int8_validated": False}
    args.checkpoint.with_name("onnx-parity.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    if not report["passed"]:
        raise SystemExit("Export parity failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
