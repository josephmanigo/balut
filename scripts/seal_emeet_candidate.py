"""Calibrate on development data, verify CPU serving, then lock before test capture."""
import argparse
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "ml"), str(ROOT / "apps/edge_api")]
import numpy as np
import onnxruntime as ort
from PIL import Image, ImageOps
from balut_api.model_service import decode_jpeg, preprocess
from balut_api.selective_gate import decide, image_quality, validate_policy
from scripts.capture_emeet_egg import sha, write

CLASSES = ["DAY_16", "DAY_18", "REJECT"]


def jpeg_body(path):
    body = path.read_bytes()
    with Image.open(io.BytesIO(body)) as image:
        if image.format != "JPEG":
            target = io.BytesIO()
            ImageOps.exif_transpose(image).convert("RGB").save(target, "JPEG", quality=95)
            body = target.getvalue()
    return body


def calibrate(scores, truth, nearest, quality):
    winner = scores.argmax(1)
    sorted_scores = np.sort(scores, axis=1)
    margins = sorted_scores[:, -1] - sorted_scores[:, -2]
    policy = {"schema_version": 1, "class_order": CLASSES, "review_required": False,
              "on_uncertain": "RECAPTURE_REQUIRED", "minimum_margin": {}, "minimum_training_cosine": {},
              "quality": quality, "calibration_scope": "Development validation only; test excluded. Scores are not probabilities."}
    for i, label in enumerate(CLASSES):
        wrong = (winner == i) & (truth != i)
        threshold = float(margins[wrong].max()) + .001 if wrong.any() else 0.
        policy["minimum_margin"][label] = threshold if ((winner == i) & (margins >= threshold)).sum() >= 5 else None
        policy["minimum_training_cosine"][label] = float(np.quantile(nearest[truth == i, i], .01))
    return policy


def seal(dataset, run):
    import torch
    from balut_ml.train_emeet_mobilenetv2 import MobileNetEgg, measured

    lock_path = dataset / "candidate-lock.json"
    if lock_path.exists() or (run / "calibration").exists():
        raise FileExistsError("Preserve the locked candidate or interrupted calibration")
    lock = json.loads((run / "training-lock.json").read_text())
    if any(sha(run / name) != digest for name, digest in lock["artifacts"].items()):
        raise ValueError("Training artifacts changed")
    recipe = json.loads((run / "experiment-plan.json").read_text())
    if sha(dataset / "collection-plan.json") != recipe["collection_plan_sha256"]:
        raise ValueError("Collection plan changed")
    rows = json.loads((run / "development-manifest.json").read_text())
    if any(r["partition"] not in {"train", "validation"} for r in rows):
        raise ValueError("Test rows cannot calibrate the model")
    folder = run / "calibration"
    folder.mkdir()
    inputs = folder / "inputs"
    inputs.mkdir()
    config = {"input_size": 224, "normalization_mean": [.485, .456, .406], "normalization_std": [.229, .224, .225]}
    options = ort.SessionOptions(); options.intra_op_num_threads = 4; options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(run / "best.onnx"), sess_options=options, providers=["CPUExecutionProvider"])
    torch.set_num_threads(4)
    native = MobileNetEgg().eval()
    native.load_state_dict(torch.load(run / "best.pt", map_location="cpu", weights_only=True)["state_dict"])
    score_error, feature_error = 0., 0.
    scores, features, batch, provenance = [], [], [], []
    quality = {"minimum_short_side": 64, "minimum_grayscale_std": 8., "minimum_edge_variance": 20., "maximum_clipped_fraction": .85}
    clipping = []
    for index, row in enumerate(rows):
        source = Path(row["image_path"])
        if sha(source) != row["source_sha256"]:
            raise ValueError("Development image changed")
        body = jpeg_body(source)
        target = inputs / (row["source_sha256"] + ".jpg")
        target.write_bytes(body)
        provenance.append({"source_sha256": row["source_sha256"], "path": str(target), "serving_sha256": sha(target)})
        if row.get("physical_egg_id") and row["partition"] == "validation":
            with decode_jpeg(body) as image:
                clipping.append(image_quality(image, {"quality": quality})[0]["clippedFraction"])
        batch.append(preprocess(body, config))
        if len(batch) == 16 or index + 1 == len(rows):
            values = np.concatenate(batch)
            output = session.run(None, {"images": values})
            with torch.inference_mode():
                expected = [value.numpy() for value in native(torch.from_numpy(values))]
            np.testing.assert_allclose(expected[0], output[0], atol=1e-4, rtol=1e-4)
            np.testing.assert_allclose(expected[1], output[1], atol=1e-5, rtol=1e-4)
            np.testing.assert_array_equal(expected[0].argmax(1), output[0].argmax(1))
            score_error = max(score_error, float(np.abs(expected[0] - output[0]).max()))
            feature_error = max(feature_error, float(np.abs(expected[1] - output[1]).max()))
            scores.extend(output[0]); features.extend(output[1]); batch = []
        if (index + 1) % 500 == 0:
            print(json.dumps({"cpu_development_frames": index + 1, "total": len(rows)}), flush=True)
    scores, features = np.asarray(scores), np.asarray(features)
    truth = np.array([CLASSES.index(r["source_label"]) for r in rows])
    train = np.array([r["partition"] == "train" for r in rows]); val = ~train
    nearest = np.column_stack([(features[val] @ features[train & (truth == label)].T).max(1) for label in range(3)])
    # Opaque candling eggs can occupy most of the dark image; calibrate that fraction on known validation eggs.
    quality["maximum_clipped_fraction"] = min(.99, max(.85, float(np.quantile(clipping, .99)) + .005))
    policy = calibrate(scores[val], truth[val], nearest, quality)
    validate_policy(policy, features[train], truth[train])
    write(folder / "gate-policy.json", policy)
    np.savez_compressed(folder / "training-references.npz", features=features[train], labels=truth[train])
    np.savez_compressed(folder / "development-cpu.npz", scores=scores, features=features, truth=truth, train=train)
    write(folder / "serving-inputs.json", provenance)
    with np.load(run / "development.npz", allow_pickle=False) as trained:
        parity = float(np.max(np.abs(trained["scores"] - scores)))
        gpu_prediction_changes = int((trained["scores"].argmax(1) != scores.argmax(1)).sum())
    outcomes = []
    for index in np.flatnonzero(val):
        with decode_jpeg(Path(provenance[index]["path"]).read_bytes()) as image:
            result = decide(scores[index], features[index], image, policy, features[train], truth[train])
        outcomes.append({"row_index": int(index), "truth": CLASSES[truth[index]], **result})
    write(folder / "validation-outcomes.json", outcomes)
    write(folder / "verification.json", {"cpu_gpu_max_score_difference": parity, "gpu_cpu_raw_prediction_changes": gpu_prediction_changes,
          "cpu_pytorch_onnx_max_score_difference": score_error, "cpu_pytorch_onnx_max_embedding_difference": feature_error,
          "cpu_pytorch_onnx_prediction_agreement": len(rows), "development_images_verified": len(rows),
          "export_verification": "Full development set: CPU PyTorch versus CPU ONNX, identical input tensors; strict numeric and argmax checks passed",
          "training_backend_difference": "Epoch logs used GPU cuDNN with TF32 enabled; serving uses CPU float32. Both measurements are retained, not substituted",
          "serving_train": measured(scores[train], truth[train]), "serving_validation": measured(scores[val], truth[val]), "test_images_opened": 0,
          "quality_calibration": "Only clipping fraction adapted using validation eggs; blur, contrast and size limits unchanged",
          "maximum_clipped_fraction": quality["maximum_clipped_fraction"], "field_accuracy_established": False})
    artifacts = [run / "training-lock.json", run / "best.onnx", run / "development-manifest.json",
                 folder / "gate-policy.json", folder / "training-references.npz", folder / "development-cpu.npz",
                 folder / "validation-outcomes.json", folder / "verification.json"]
    write(lock_path, {"schema_version": 1, "architecture": "MobileNetV2", "run": str(run),
          "collection_plan_sha256": sha(dataset / "collection-plan.json"), "test_images_opened": 0,
          "artifacts": [{"path": str(path), "sha256": sha(path)} for path in artifacts],
          "field_accuracy_established": False})
    print(json.dumps({"candidate_locked": True, "path": str(lock_path), "test_images_opened": 0}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path); parser.add_argument("run", type=Path)
    args = parser.parse_args()
    seal(args.dataset.resolve(), args.run.resolve())
