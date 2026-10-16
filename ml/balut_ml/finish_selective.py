"""Export and evaluate the locked selective candidate once; never adjust its gates."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from collections import Counter

import numpy as np
import onnx
import onnxruntime as ort
import torch
from PIL import Image, ImageOps

from .benchmark_public import extract, metrics_for, write_json
from .feature_models import DINO_REVISION, FeatureEncoder, FusedEncoder, SelectiveClassifier, build_backbone, build_head, image_transform
from .selective_search import sha

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps/edge_api"))
from balut_api.selective_gate import CLASSES, decide, validate_policy


def evaluate(rows, indexes, scores, features, truth, policy, references, reference_labels):
    outcomes = []
    for index, values, embedding, target in zip(indexes, scores, features, truth):
        row = rows[int(index)]
        if sha(Path(row["image_path"])) != row["source_sha256"]:
            raise ValueError("Evaluation image identity changed")
        with Image.open(row["image_path"]) as original:
            result = decide(values, embedding, ImageOps.exif_transpose(original).convert("RGB"), policy, references, reference_labels)
        outcomes.append({"index":int(index), "truth":CLASSES[int(target)], **result})
    accepted = [item for item in outcomes if item["sourcePrediction"] is not None]
    correct = sum(item["sourcePrediction"] == item["truth"] for item in accepted)
    report = {"images":len(outcomes), "classified":len(accepted), "correct_classified":correct,
              "wrong_classified":len(accepted)-correct, "recapture_requested":len(outcomes)-len(accepted),
              "coverage":len(accepted)/len(outcomes), "accepted_accuracy":correct/len(accepted) if accepted else None,
              "correct_of_all_inputs":correct/len(outcomes),
              "recapture_reasons":dict(Counter(reason for item in outcomes for reason in item["recaptureReasons"])),
              "by_true_class":{label:{"images":sum(item["truth"]==label for item in outcomes),
                                      "classified":sum(item["truth"]==label for item in accepted),
                                      "correct_classified":sum(item["truth"]==label==item["sourcePrediction"] for item in accepted)} for label in CLASSES},
              "by_prediction":{label:{"classified":sum(item["sourcePrediction"]==label for item in accepted),
                                      "correct":sum(item["truth"]==label==item["sourcePrediction"] for item in accepted)} for label in CLASSES}}
    return report, outcomes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run",type=Path)
    args = parser.parse_args()
    run = args.run
    if (run / "metrics.json").exists():
        raise FileExistsError("Preserve the completed evaluation; do not loop on historical test labels")
    torch.set_num_threads(4)
    lock = json.loads((run / "selection-lock.json").read_text())
    policy = json.loads((run / "gate-policy.json").read_text())
    assert sha(run / "gate-policy.json") == lock["gate_policy_sha256"]
    assert sha(run / "selected-development.npz") == lock["development_data_sha256"]
    if "selected_head_sha256" in lock:
        if sha(run / "selected-head.pt") != lock["selected_head_sha256"] or sha(run / "experiment-plan.json") != lock["experiment_plan_sha256"]:
            raise ValueError("Selected head or experiment plan changed after selection")
    manifest = ROOT / "ml/runs/three-class-v1/manifest.jsonl"
    assert sha(manifest) == lock["manifest_sha256"]
    rows = [json.loads(line) for line in manifest.read_text().splitlines()]
    development = np.load(run / "selected-development.npz")
    references, reference_labels = development["train_features"], development["train_truth"]
    validate_policy(policy, references, reference_labels)
    np.savez_compressed(run / "training-references.npz", features=references, labels=reference_labels)
    encoders = []
    for name in lock["backbones"]:
        encoder = FeatureEncoder(build_backbone(name)).eval()
        encoder.load_state_dict(torch.load(ROOT / "ml/runs/accuracy-v2" / f"{name}-encoder.pt", weights_only=True, map_location="cpu"))
        encoders.append(encoder)
    encoder = FusedEncoder(encoders).eval()
    payload = torch.load(run / "selected-head.pt",weights_only=True,map_location="cpu")
    head = build_head(payload["spec"])
    head.load_state_dict(payload["state_dict"])
    model = SelectiveClassifier(encoder,head).eval()
    config = json.loads((ROOT / "ml/runs/three-class-v1/config.json").read_text())
    config.pop("backbone")
    config.pop("encoder_sha256")
    config.update(backbones=lock["backbones"], head=lock["head"], hyperparameters=lock["hyperparameters"],
                  selective_inference=True, selection_lock_sha256=sha(run / "selection-lock.json"),
                  gate_policy_sha256=sha(run / "gate-policy.json"), references_sha256=sha(run / "training-references.npz"),
                  dinov2_revision=DINO_REVISION, output_semantics="Uncalibrated decision scores and normalized feature vector; unclear images remain unclassified with automatic recapture request.")
    config["limitations"][-1] = "No mandatory human review in image analysis. Uncertain inputs request another image; physical sorting and food-safety authority remain unavailable."
    config["limitations"].append("Recapture thresholds were fitted to development data; accepted predictions can still be wrong. Coverage must be reported with accuracy.")
    write_json(run / "config.json",config)
    torch.save({"state_dict":model.state_dict(),"config":config},run / "best.pt")
    print("Selected model and gates frozen. Extracting historical test once.",flush=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    features, truth, indexes = extract(encoder.to(device),rows,{"test"},CLASSES,device,8)
    encoder.cpu()
    with torch.inference_mode():
        scores = head(torch.from_numpy(features)).numpy()
    np.savez_compressed(run / "selected-test.npz",features=features,truth=truth,indexes=indexes,scores=scores)
    validation, _ = evaluate(rows,development["indexes"],development["scores"],development["validation_features"],development["truth"],policy,references,reference_labels)
    measured, outcomes = evaluate(rows,indexes,scores,features,truth,policy,references,reference_labels)
    write_json(run / "test-outcomes.json",outcomes)
    report = {"validation_raw":lock["validation"],"test_raw":metrics_for(truth,scores.argmax(1),CLASSES),
              "validation_selective":validation,"test_selective":measured,"selection_lock_sha256":sha(run / "selection-lock.json"),
              "test_interpretation":"Previously inspected historical public holdout; not independent candler/egg validation",
              "limitations":config["limitations"]}
    write_json(run / "metrics.json",report)
    print(json.dumps(report),flush=True)
    output = run / "best.onnx"
    with torch.inference_mode():
        torch.onnx.export(model,torch.randn(1,3,224,224),str(output),input_names=["images"],
                          output_names=["decision_scores","embedding"],
                          dynamic_axes={"images":{0:"batch"},"decision_scores":{0:"batch"},"embedding":{0:"batch"}},opset_version=18,dynamo=False)
    onnx.checker.check_model(str(output))
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    session = ort.InferenceSession(str(output),sess_options=options,providers=["CPUExecutionProvider"])
    transform = image_transform()
    parity_scores, parity_features, errors = [], [], []
    for start in range(0,len(indexes),8):
        tensors = []
        for index in indexes[start:start+8]:
            with Image.open(rows[int(index)]["image_path"]) as image:
                tensors.append(transform(ImageOps.exif_transpose(image).convert("RGB")))
        batch = torch.stack(tensors)
        values, vectors = session.run(None,{"images":batch.numpy()})
        parity_scores.extend(values)
        parity_features.extend(vectors)
        errors.append(float(np.max(np.abs(values-scores[start:start+len(batch)]))))
    parity_report, parity_outcomes = evaluate(rows,indexes,np.array(parity_scores),np.array(parity_features),truth,policy,references,reference_labels)
    same_results = all(a["sourcePrediction"]==b["sourcePrediction"] and a["recaptureReasons"]==b["recaptureReasons"] for a,b in zip(outcomes,parity_outcomes))
    parity = {"passed":max(errors)<1e-4 and same_results,"onnx_sha256":sha(output),"test_images_compared":len(indexes),
              "maximum_score_error":max(errors),"selective_decisions_identical":same_results,"onnx_selective":parity_report,
              "embedding_maximum_error":float(np.abs(np.array(parity_features)-features).max())}
    write_json(run / "onnx-parity.json",parity)
    print(json.dumps(parity),flush=True)
    # GPU numerical differences are preserved separately; deployment export
    # accuracy is measured against the same CPU execution used on Windows.
    from .verify_selective_export import verify_cpu_export
    verify_cpu_export(run)


if __name__ == "__main__":
    main()
