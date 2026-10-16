"""Run a bundled exploratory ONNX classifier without Torch or source repository downloads."""
import argparse
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image, ImageOps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    config = json.loads(args.model.with_name("config.json").read_text(encoding="utf-8"))
    if config["operational_use_authorized"] or config["status"] not in {
            "EXPLORATORY_PUBLIC_SOURCE_CLASSIFIER", "EXPLORATORY_FROZEN_FEATURE_CLASSIFIER"}:
        raise ValueError("Unexpected checkpoint contract")
    with Image.open(args.image) as original:
        image = ImageOps.exif_transpose(original).convert("RGB").resize((224, 224), Image.Resampling.BILINEAR)
    values = np.asarray(image, dtype=np.float32) / 255.0
    values = (values - np.asarray(config["normalization_mean"], dtype=np.float32)) / np.asarray(config["normalization_std"], dtype=np.float32)
    tensor = np.ascontiguousarray(values.transpose(2, 0, 1)[None])
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    session = ort.InferenceSession(str(args.model), sess_options=options, providers=["CPUExecutionProvider"])
    scores = session.run(None, {"images": tensor})[0][0]
    print(json.dumps({"status": "EXPLORATORY_ONLY", "source_prediction": config["class_order"][int(scores.argmax())],
                      "source_class_decision_scores": dict(zip(config["class_order"], scores.tolist())),
                      "operational_outcome": "REVIEW_RECAPTURE", "operational_use_authorized": False,
                      "note": "Uncalibrated decision scores, not probabilities or verified biological outcomes."}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
