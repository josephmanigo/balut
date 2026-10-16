"""Check CPU PyTorch versus ONNX, retaining the separate GPU numeric comparison."""
import json
import argparse
from pathlib import Path
import shutil

import numpy as np
import onnxruntime as ort
import torch
from PIL import Image, ImageOps

from .feature_models import image_transform, load_classifier
from .finish_selective import ROOT, evaluate
from .selective_search import sha
from .benchmark_public import write_json


def verify_cpu_export(run):
    original = run / "onnx-parity.json"
    if (run / "onnx-gpu-parity.json").exists():
        raise FileExistsError("Preserve verification evidence")
    shutil.copy2(original,run / "onnx-gpu-parity.json")
    torch.set_num_threads(4)
    model, config = load_classifier(run / "best.pt")
    frozen = np.load(run / "selected-test.npz")
    bank = np.load(run / "training-references.npz")
    policy = json.loads((run / "gate-policy.json").read_text())
    manifest = ROOT / "ml/runs/three-class-v1/manifest.jsonl"
    assert sha(manifest) == config["manifest_sha256"]
    assert sha(run / "gate-policy.json") == config["gate_policy_sha256"]
    rows = [json.loads(line) for line in manifest.read_text().splitlines()]
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    session = ort.InferenceSession(str(run / "best.onnx"),sess_options=options,providers=["CPUExecutionProvider"])
    transform = image_transform()
    score_error, feature_error, gpu_argmax_agreement = 0.0,0.0,0
    native_scores, native_features, onnx_scores, onnx_features = [],[],[],[]
    for start in range(0,len(frozen["indexes"]),8):
        tensors = []
        for index in frozen["indexes"][start:start+8]:
            with Image.open(rows[int(index)]["image_path"]) as image:
                tensors.append(transform(ImageOps.exif_transpose(image).convert("RGB")))
        batch = torch.stack(tensors)
        with torch.inference_mode():
            native, vectors = [item.numpy() for item in model(batch)]
        exported, embeddings = session.run(None,{"images":batch.numpy()})
        native_scores.extend(native); native_features.extend(vectors)
        onnx_scores.extend(exported); onnx_features.extend(embeddings)
        score_error = max(score_error,float(np.abs(native-exported).max()))
        feature_error = max(feature_error,float(np.abs(vectors-embeddings).max()))
        gpu_argmax_agreement += int((frozen["scores"][start:start+len(batch)].argmax(1)==exported.argmax(1)).sum())
    cpu_report, cpu_outcomes = evaluate(rows,frozen["indexes"],np.array(native_scores),np.array(native_features),frozen["truth"],policy,bank["features"],bank["labels"])
    onnx_report, onnx_outcomes = evaluate(rows,frozen["indexes"],np.array(onnx_scores),np.array(onnx_features),frozen["truth"],policy,bank["features"],bank["labels"])
    gpu_outcomes = json.loads((run / "test-outcomes.json").read_text())
    same = lambda left,right: all(a["sourcePrediction"]==b["sourcePrediction"] and a["recaptureReasons"]==b["recaptureReasons"] for a,b in zip(left,right))
    report = {"passed":score_error<1e-4 and feature_error<1e-4 and same(cpu_outcomes,onnx_outcomes) and same(gpu_outcomes,onnx_outcomes) and gpu_argmax_agreement==len(gpu_outcomes),
              "onnx_sha256":sha(run / "best.onnx"),"test_images_compared":len(gpu_outcomes),
              "cpu_torch_onnx_maximum_score_error":score_error,"cpu_torch_onnx_maximum_embedding_error":feature_error,
              "gpu_onnx_raw_prediction_agreement":gpu_argmax_agreement,"selective_decisions_identical":same(cpu_outcomes,onnx_outcomes) and same(gpu_outcomes,onnx_outcomes),
              "onnx_selective":onnx_report,"gpu_numerical_difference_report":"onnx-gpu-parity.json",
              "note":"GPU and CPU have measurable numerical differences. Float32 export parity is checked against CPU PyTorch; historical decisions must also match frozen GPU results. No model or gate parameters changed."}
    write_json(original,report)
    print(json.dumps(report),flush=True)
    assert report["passed"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run",type=Path,nargs="?",default=ROOT / "ml/runs/selective-v2")
    verify_cpu_export(parser.parse_args().run)
