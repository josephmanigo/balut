"""Export the selected image fine-tune and calibrate serving gates on validation."""
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ml"), str(ROOT / "apps/edge_api")]
import numpy as np
import torch
import onnx
import onnxruntime as ort
from PIL import Image, ImageOps
from balut_ml.feature_models import load_classifier
from balut_ml.train_epoch_head import DATA, PARENT, CLASSES, sha, write, metrics, groups_report
from balut_ml.train_unfertilized import calibrate
from balut_api.model_service import preprocess, decode_jpeg
from balut_api.selective_gate import decide

RUN = ROOT / "ml/runs/finetuned-epochs-reject-20261019"


def main():
    lock = json.loads((RUN / "training-lock.json").read_text())
    assert all(sha(RUN / name) == digest for name, digest in lock["artifacts"].items())
    if (RUN / "best.onnx").exists():
        raise FileExistsError("Preserve an interrupted or completed export")
    payload = torch.load(RUN / "best.pt", weights_only=True, map_location="cpu")
    model, _ = load_classifier(ROOT / "ml/runs/selective-v2/best.pt")
    model.load_state_dict(payload["state_dict"])
    model.eval()
    config = payload["config"]
    torch.set_num_threads(4)
    with torch.inference_mode():
        torch.onnx.export(model, torch.randn(1, 3, 224, 224), str(RUN / "best.onnx"), input_names=["images"],
                          output_names=["decision_scores", "embedding"], opset_version=18, dynamo=False,
                          dynamic_axes={"images": {0: "batch"}, "decision_scores": {0: "batch"}, "embedding": {0: "batch"}})
    onnx.checker.check_model(str(RUN / "best.onnx"))
    options = ort.SessionOptions(); options.intra_op_num_threads = 4; options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(RUN / "best.onnx"), sess_options=options, providers=["CPUExecutionProvider"])
    rows = [json.loads(line) for line in (DATA / "manifest.jsonl").read_text().splitlines()]
    train_rows = [row for row in rows if row["partition"] == "train"]
    val_rows = [row for row in rows if row["partition"] == "validation"]
    provenance = json.loads((PARENT / "validation-inputs.json").read_text())
    inputs = {item["source_sha256"]: item for item in provenance}
    def body(row, validation):
        if validation:
            item = inputs[row["source_sha256"]]
            path = Path(item["path"])
            assert sha(path) == item["serving_jpeg_sha256"]
            return path.read_bytes()
        path = Path(row["image_path"])
        assert sha(path) == row["source_sha256"]
        data = path.read_bytes()
        with Image.open(io.BytesIO(data)) as image:
            if image.format != "JPEG":
                out = io.BytesIO(); ImageOps.exif_transpose(image).convert("RGB").save(out, "JPEG", quality=95)
                data = out.getvalue()
        return data
    references = []
    model.cuda()
    with torch.inference_mode():
        for start in range(0, len(train_rows), 16):
            batch = np.concatenate([preprocess(body(row, False), config) for row in train_rows[start:start + 16]])
            _, features = model(torch.from_numpy(batch).cuda())
            references.extend(features.cpu().numpy())
    model.cpu()
    references = np.asarray(references, dtype=np.float32)
    train_labels = np.array([CLASSES.index(row["training_label"]) for row in train_rows])
    scores, features, cpu_errors = [], [], []
    for index, row in enumerate(val_rows):
        values = preprocess(body(row, True), config)
        output, embedding = session.run(None, {"images": values})
        if index < 3:
            with torch.inference_mode():
                native = model(torch.from_numpy(values))
            cpu_errors.append(float(np.abs(native[0].numpy() - output).max()))
            np.testing.assert_allclose(native[0].numpy(), output, atol=1e-4, rtol=1e-4)
            np.testing.assert_allclose(native[1].numpy(), embedding, atol=1e-5, rtol=1e-4)
        scores.append(output[0]); features.append(embedding[0])
        if (index + 1) % 50 == 0:
            print(json.dumps({"validation_cpu_embeddings": index + 1, "total": len(val_rows)}), flush=True)
    scores, features = np.asarray(scores), np.asarray(features)
    truth = np.array([CLASSES.index(row["training_label"]) for row in val_rows])
    with np.load(RUN / "selected-validation.npz", allow_pickle=False) as bank:
        gpu_agreement = int((bank["scores"].argmax(1) == scores.argmax(1)).sum())
    assert gpu_agreement == len(val_rows), "GPU/CPU prediction difference requires a separate audit"
    quality = json.loads((PARENT / "gate-policy.json").read_text())["quality"]
    policy = calibrate(scores, truth, features, references, train_labels, quality)
    policy["class_order"] = CLASSES
    for key in ("minimum_margin", "minimum_training_cosine"):
        policy[key]["REJECT"] = policy[key].pop("UNFERTILIZED")
    outcomes = [decide(score, feature, decode_jpeg(body(row, True)), policy, references, train_labels)
                for row, score, feature in zip(val_rows, scores, features, strict=True)]
    selective = np.zeros((3, 4), dtype=int)
    for target, outcome in zip(truth, outcomes, strict=True):
        selective[target, CLASSES.index(outcome["sourcePrediction"]) if outcome["sourcePrediction"] else 3] += 1
    np.savez_compressed(RUN / "head.npz", coefficient=model.head.linear.weight.detach().numpy(), intercept=model.head.linear.bias.detach().numpy())
    np.savez_compressed(RUN / "training-references.npz", features=references, labels=train_labels)
    write(RUN / "gate-policy.json", policy)
    write(RUN / "validation-inputs.json", provenance)
    write(RUN / "validation-outcomes.json", [{"source_sha256": row["source_sha256"], "source_label": row["training_label"], **outcome}
                                             for row, outcome in zip(val_rows, outcomes, strict=True)])
    summary = json.loads((RUN / "training-summary.json").read_text())
    config.update(initial_model_sha256="479211e3e587b0bce7d9bb1be1a318c48bdc62f632374f75d980ab1dbceda31e",
                  dataset_sha256=sha(DATA / "manifest.jsonl"), epochs_completed=summary["epochs_completed"], selected_epoch=summary["selected_epoch"])
    write(RUN / "config.json", config)
    report = {"class_order": CLASSES, "epochs_completed": summary["epochs_completed"], "selected_epoch": summary["selected_epoch"],
              "validation": {**metrics(scores, truth), "raw_confusion_matrix": metrics(scores, truth)["confusion_matrix"],
                             "selective_confusion_matrix": selective.tolist(), "validation_groups": groups_report(val_rows, scores, outcomes)},
              "export": {"cpu_pytorch_onnx_maximum_score_error": max(cpu_errors), "validation_gpu_cpu_raw_agreement": gpu_agreement},
              "test_images_opened": 0, "general_reject_condition_validated": False}
    write(RUN / "metrics.json", report)
    names = ["training-lock.json", "history.jsonl", "best.onnx", "head.npz", "training-references.npz", "gate-policy.json",
             "validation-inputs.json", "validation-outcomes.json", "config.json", "metrics.json"]
    write(RUN / "selection-lock.json", {"artifacts": {name: sha(RUN / name) for name in names}, "physical_reject_validation_passed": False})
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
