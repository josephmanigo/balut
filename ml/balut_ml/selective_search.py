"""Bounded validation-selected feature fusion; never tune on historical test labels."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier
from sklearn.svm import SVC

from .benchmark_public import metrics_for, selection_key, write_json
from .feature_models import build_head, portable_head
from .train_three_class import CLASSES

FUSIONS = [["dinov2_vits14"], ["dinov2_vits14", "convnext_tiny"], ["dinov2_vits14", "efficientnet_b0"]]
GRID = ([{"kind":"logistic", "C": c, "class_weight":"balanced"} for c in [0.1,1.0,10.0,100.0]]
        + [{"kind":"rbf_ovr", "C":c, "gamma":g, "class_weight":"balanced"} for c in [0.1,1.0,10.0] for g in ["scale",0.1,1.0,10.0]])


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def learn_margin_thresholds(scores, truth, minimum_examples=5):
    """Choose maximum coverage with zero observed validation errors per class.

    Scores are not calibrated probabilities. This is a development heuristic,
    not a certification that accepted unseen predictions are error free.
    """
    predictions = scores.argmax(1)
    margins = np.sort(scores,axis=1)[:,-1] - np.sort(scores,axis=1)[:,-2]
    thresholds, summary = {}, {}
    for class_id, label in enumerate(CLASSES):
        selected = predictions == class_id
        wrong = selected & (truth != class_id)
        threshold = float(margins[wrong].max()) + 1e-5 if wrong.any() else 0.0
        accepted = selected & (margins >= threshold)
        if int(accepted.sum()) < minimum_examples:
            thresholds[label] = None
            summary[label] = {"accepted":0,"correct":0,"reason":"insufficient validation support"}
        else:
            thresholds[label] = threshold
            summary[label] = {"accepted":int(accepted.sum()),"correct":int((accepted & (truth==class_id)).sum())}
    return thresholds, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--extended", action="store_true", help="Compare three-backbone fusion and intermediate regularization values on development data only")
    args = parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    fusions = FUSIONS + ([["dinov2_vits14", "convnext_tiny", "efficientnet_b0"]] if args.extended else [])
    grid = GRID + ([{"kind":"logistic", "C":c, "class_weight":"balanced"} for c in [0.3,3.0,30.0,300.0]] if args.extended else [])
    torch.set_num_threads(4)
    root = Path(__file__).resolve().parents[2]
    baseline = root / "ml/runs/three-class-v1"
    manifest = baseline / "manifest.jsonl"
    baseline_config = json.loads((baseline / "config.json").read_text())
    assert sha(manifest) == baseline_config["manifest_sha256"]
    rows = [json.loads(line) for line in manifest.read_text().splitlines()]
    indexes = np.array([i for i,row in enumerate(rows) if row["partition"] != "test"])
    train = np.array([rows[i]["partition"] == "train" for i in indexes])
    labels = np.array([CLASSES.index(rows[i]["source_label"]) for i in indexes])
    sources = {"age":"source-age16-18","pat":"pat-balut"}
    source_hashes = json.loads((baseline / "experiment-plan.json").read_text())["source_manifests"]
    features = {}
    cache_hashes = {}
    for backbone in sorted({name for fusion in fusions for name in fusion}):
        bank = {}
        for source, task in sources.items():
            cache_path = root / "ml/runs/accuracy-v2" / task / f"{backbone}-development.npz"
            cache_hashes[str(cache_path.relative_to(root))] = sha(cache_path)
            with np.load(cache_path, allow_pickle=False) as cache:
                assert str(cache["manifest_sha256"]) == source_hashes[source]
                for index, vector in zip(cache["indexes"],cache["features"]):
                    bank[(source,int(index))] = vector
        features[backbone] = np.stack([bank[(rows[i]["source_dataset"],rows[i]["original_row_index"])] for i in indexes])
    plan = {"candidate_limit":len(fusions)*len(grid),"fusions":fusions,"grid":grid,"development_cache_sha256":cache_hashes,
            "selection":"validation macro F1, balanced accuracy, accuracy; stable first candidate tie break",
            "historical_test_policy":"Never accessed in search. One evaluation after selection, gate settings, and hashes are locked.",
            "manifest_sha256":sha(manifest),"gate_policy":"Per-class raw-score margin above all validation mistakes; at least five correctly accepted validation samples; no certainty guarantee",
            "limitations":baseline_config["limitations"]}
    write_json(args.output / "experiment-plan.json",plan)
    best = None
    for fusion in fusions:
        vectors = np.concatenate([features[name] for name in fusion],axis=1) / np.sqrt(len(fusion))
        vectors = vectors.astype(np.float32)
        for spec in grid:
            estimator = (LogisticRegression(C=spec["C"],class_weight="balanced",max_iter=3000,random_state=42)
                         if spec["kind"]=="logistic" else OneVsRestClassifier(SVC(C=spec["C"],gamma=spec["gamma"],class_weight="balanced",kernel="rbf",cache_size=512),n_jobs=1))
            estimator.fit(vectors[train],labels[train])
            predicted = estimator.predict(vectors[~train])
            measured = metrics_for(labels[~train],predicted,CLASSES)
            head, head_spec = portable_head(estimator,spec["kind"])
            with torch.inference_mode():
                scores = head(torch.from_numpy(vectors[~train])).numpy()
            assert np.array_equal(scores.argmax(1),predicted)
            record = {"backbones":fusion,"hyperparameters":spec,"head":head_spec,"validation":measured}
            with (args.output / "candidates.jsonl").open("a") as file:
                file.write(json.dumps(record)+"\n")
            if best is None or selection_key(measured)>selection_key(best["validation"]):
                best = record
                torch.save({"state_dict":head.state_dict(),"spec":head_spec},args.output / "selected-head.pt")
                np.savez_compressed(args.output / "selected-development.npz",train_features=vectors[train],train_truth=labels[train],train_indexes=indexes[train],
                                    validation_features=vectors[~train],scores=scores,truth=labels[~train],indexes=indexes[~train])
        print(json.dumps({"completed_fusion":fusion,"best_fusion":best["backbones"],"best_validation":best["validation"]["macro_f1"]}),flush=True)
    data = np.load(args.output / "selected-development.npz")
    thresholds, accepted = learn_margin_thresholds(data["scores"],data["truth"])
    # Nearest training embedding distance is another abstention heuristic.
    novelty = {}
    for class_id,label in enumerate(CLASSES):
        matching = data["validation_features"][data["truth"]==class_id]
        references = data["train_features"][data["train_truth"]==class_id]
        similarities = (matching @ references.T).max(1)
        novelty[label] = float(np.quantile(similarities,0.01))
    gate = {"schema_version":1,"minimum_margin":thresholds,"minimum_training_cosine":novelty,
            "validation_margin_gate_counts":accepted,"review_required":False,"on_uncertain":"RECAPTURE_REQUIRED",
            "calibration_scope":"Development-selected raw-score/feature-distance heuristic; not guaranteed probabilities or independent acceptance evidence",
            "quality":{"minimum_short_side":64,"minimum_grayscale_std":8.0,"minimum_edge_variance":20.0,"maximum_clipped_fraction":0.85}}
    write_json(args.output / "gate-policy.json",gate)
    lock = {**best,"manifest_sha256":sha(manifest),"gate_policy_sha256":sha(args.output / "gate-policy.json"),
            "development_data_sha256":sha(args.output / "selected-development.npz"),
            "selected_head_sha256":sha(args.output / "selected-head.pt"),
            "experiment_plan_sha256":sha(args.output / "experiment-plan.json"),
            "baseline_validation":json.loads((baseline / "metrics.json").read_text())["validation"]}
    write_json(args.output / "selection-lock.json",lock)
    print(json.dumps({"selected":best["backbones"],"validation":best["validation"],"gate":gate,"selection_lock_sha256":sha(args.output / "selection-lock.json")}),flush=True)


if __name__ == "__main__":
    main()
