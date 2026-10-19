"""Fit explicit Unfertilized heads from verified development caches; keep test closed."""
from collections import Counter
import copy
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps
from sklearn.linear_model import LogisticRegression

from balut_api.model_service import ModelService, active_registry, preprocess
from balut_api.selective_gate import decide, image_quality, validate_policy
from .unfertilized_data import CLASSES, DATA, ROOT, sha

RUN = ROOT / "ml/runs/retained-unfertilized-serving-20261019"
CPU_CACHE = ROOT / "ml/runs/retained-unfertilized-cpu-20261019"
WEIGHTS = (20, 50, 100)


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def fit_weights(rows, camera_weight):
    counts = Counter(r["physical_egg_id"] for r in rows if r.get("physical_egg_id"))
    weights = np.array([camera_weight / counts[r["physical_egg_id"]] if r.get("physical_egg_id") else 1.0 for r in rows])
    truth = np.array([CLASSES.index(r["source_label"]) for r in rows])
    for label in range(3):
        selected = truth == label
        weights[selected] /= weights[selected].sum()
    return weights * len(weights) / 3


def calibrate(scores, truth, features, references, labels, quality):
    winner = scores.argmax(1)
    margins = np.sort(scores, axis=1)[:, -1] - np.sort(scores, axis=1)[:, -2]
    policy = {"schema_version": 1, "class_order": CLASSES, "review_required": False,
              "on_uncertain": "RECAPTURE_REQUIRED", "minimum_margin": {}, "minimum_training_cosine": {},
              "quality": quality, "calibration_scope": "Development validation only; not a probability or field accuracy guarantee"}
    for index, label in enumerate(CLASSES):
        wrong = (winner == index) & (truth != index)
        threshold = float(margins[wrong].max()) + 1e-3 if wrong.any() else 0.0
        accepted = (winner == index) & (margins >= threshold)
        policy["minimum_margin"][label] = threshold if accepted.sum() >= 5 else None
        policy["minimum_training_cosine"][label] = float(np.quantile((features[truth == index] @ references[labels == index].T).max(1), .01))
    validate_policy(policy, references, labels)
    return policy


def main():
    if RUN.exists():
        raise FileExistsError("Preserve the completed or interrupted Unfertilized run")
    manifest = DATA / "manifest.jsonl"
    audit = json.loads((DATA / "audit.json").read_text())
    assert sha(manifest) == audit["manifest_sha256"] and audit["reject_rows_relabelled_as_unfertilized"] == 0
    all_rows = [json.loads(line) for line in manifest.read_text().splitlines()]
    rows = [r for r in all_rows if r["partition"] in ("train", "validation")]
    assert not any(r.get("test_status") for r in rows)
    registry = active_registry(ROOT)
    registry_data = json.loads(registry.read_text())
    model_path = registry.parent / registry_data["models"][0]["model"]["path"]
    caches = [ROOT / "ml/runs/selective-v2/selected-development.npz",
              ROOT / "ml/runs/retained-camera-50views-rejects-20261019/development.npz"]
    caches += [ROOT / "ml/runs/accuracy-v2/pat-balut" / (name + "-development.npz") for name in ("dinov2_vits14", "efficientnet_b0")]
    cache_lock = json.loads((CPU_CACHE / "selection-lock.json").read_text())
    assert all(sha(CPU_CACHE/name)==digest for name,digest in cache_lock["artifacts"].items())
    assert json.loads((CPU_CACHE/"config.json").read_text())["encoder_onnx_sha256"]==sha(model_path)
    protected = {str(p.relative_to(ROOT)): sha(p) for p in caches + [manifest, registry, model_path, Path(__file__),
                 CPU_CACHE/"development.npz", CPU_CACHE/"validation-inputs.json", CPU_CACHE/"selection-lock.json"]}
    RUN.mkdir()
    write(RUN / "experiment-plan.json", {"class_order": CLASSES, "camera_weights_per_egg": WEIGHTS, "C": 100, "seed": 42,
          "training": "Training rows only; equal effective weight per class; camera weight distributed over each physical egg",
          "selection": "Highest mean correct-over-all across historical Day16/Day18/Unfertilized and physical Day16/Day18 validation groups; then raw macro recall; stable first tie",
          "policy": "Quality limits unchanged. Margins exceed validation mistakes by 0.001, with at least five supported predictions. Cosine threshold from validation first percentile.",
          "feature_sources": "Retained frozen GPU/camera caches for fitting; verified ONNX CPU vectors for validation. Quality measured on the exact serving JPEGs: PNG validation crops encoded at quality95, camera JPEGs unchanged.",
          "protected_files": protected, "dataset_sha256": audit["manifest_sha256"], "test_images_opened": 0,
          "limitations": audit["limitations"] + ["No confirmed Unfertilized physical egg is available for a live check"]})
    bank = {}
    historical = [json.loads(line) for line in (ROOT / "ml/runs/three-class-v1/manifest.jsonl").read_text().splitlines()]
    with np.load(caches[0], allow_pickle=False) as data:
        for indexes, name in (("train_indexes", "train_features"), ("indexes", "validation_features")):
            bank.update((historical[int(i)]["source_sha256"], x) for i, x in zip(data[indexes], data[name], strict=True))
    with np.load(caches[1], allow_pickle=False) as data:
        bank.update(zip(data["source_sha256"].tolist(), data["features"], strict=True))
    public_hash = audit["public_manifest_sha256"]
    with np.load(caches[2], allow_pickle=False) as dino, np.load(caches[3], allow_pickle=False) as efficient:
        assert str(dino["manifest_sha256"]) == str(efficient["manifest_sha256"]) == public_hash
        np.testing.assert_array_equal(dino["indexes"], efficient["indexes"])
        public_bank = dict(zip(dino["indexes"].tolist(), np.concatenate((dino["features"], efficient["features"]), axis=1) / np.float32(2 ** .5), strict=True))
    features = np.stack([public_bank[r["original_row_index"]] if r["source_dataset"] == "pat-unfertilized" else bank[r["source_sha256"]] for r in rows]).astype(np.float32)
    with np.load(CPU_CACHE/"development.npz",allow_pickle=False) as actual:
        np.testing.assert_array_equal(actual["source_sha256"], [r["source_sha256"] for r in rows])
        features = actual["features"].copy()
    np.testing.assert_allclose(np.linalg.norm(features, axis=1), 1, atol=1e-4)
    service = ModelService()
    try:
        service.load(registry, sha(registry))
        model = service.models["egg-grade"]
        quality = copy.deepcopy(model["camera"]["policy"]["quality"])
        provenance=json.loads((CPU_CACHE/"validation-inputs.json").read_text())
        assert len(provenance)==sum(r["partition"]=="validation" for r in rows)
        assert all(sha(Path(item["path"]))==item["serving_jpeg_sha256"] for item in provenance)
        write(RUN/"validation-inputs.json",provenance)
    finally:
        service.close()
    truth = np.array([CLASSES.index(r["source_label"]) for r in rows])
    train = np.array([r["partition"] == "train" and r.get("training_eligible", True) for r in rows])
    validation = np.array([r["partition"] == "validation" for r in rows])
    train_rows, val_rows = [[r for r, keep in zip(rows, mask, strict=True) if keep] for mask in (train, validation)]
    x, y, vx, vy = features[train], truth[train], features[validation], truth[validation]
    measurements=[]
    serving_inputs={item["source_sha256"]:item["path"] for item in provenance}
    for row in val_rows:
        with Image.open(serving_inputs[row["source_sha256"]]) as image:
            measurements.append(image_quality(image, {"quality": quality}))
    candidates, chosen, best_key = [], None, None
    for weight in WEIGHTS:
        estimator = LogisticRegression(C=100, max_iter=3000, random_state=42)
        estimator.fit(x, y, sample_weight=fit_weights(train_rows, weight))
        coefficient, intercept = estimator.coef_.astype(np.float32), estimator.intercept_.astype(np.float32)
        scores = vx @ coefficient.T + intercept
        policy = calibrate(scores, vy, vx, x, y, quality)
        outcomes=[]
        for i, row in enumerate(val_rows):
            winner=int(scores[i].argmax()); label=CLASSES[winner]
            margin=float(np.sort(scores[i])[-1]-np.sort(scores[i])[-2])
            similarity=float((x[y==winner] @ vx[i]).max())
            reasons=list(measurements[i][1])
            if policy["minimum_margin"][label] is None: reasons.append("INSUFFICIENT_VALIDATION_SUPPORT")
            elif margin <= 0 or margin < policy["minimum_margin"][label]: reasons.append("AMBIGUOUS_APPEARANCE")
            if similarity < policy["minimum_training_cosine"][label]: reasons.append("UNFAMILIAR_APPEARANCE")
            outcomes.append({"sourcePrediction":None if reasons else label,"analysisOutcome":"RECAPTURE_REQUIRED" if reasons else "CLASSIFIED",
                             "recaptureRequested":bool(reasons),"recaptureReasons":reasons})
        groups={}
        for i,row in enumerate(val_rows):
            group=("camera:" if row.get("physical_egg_id") else "source:")+row["source_label"]
            groups.setdefault(group,[]).append(i)
        reports={}
        for group,indexes in groups.items():
            reports[group]={"images":len(indexes),"raw_correct":sum(int(scores[i].argmax())==int(vy[i]) for i in indexes),
                            "classified":sum(not outcomes[i]["recaptureRequested"] for i in indexes),
                            "correct_classified":sum(outcomes[i]["sourcePrediction"]==val_rows[i]["source_label"] for i in indexes),
                            "wrong_classified":sum(outcomes[i]["sourcePrediction"] not in (None,val_rows[i]["source_label"]) for i in indexes)}
        raw_matrix=np.zeros((3,3),dtype=int)
        selective_matrix=np.zeros((3,4),dtype=int)
        for i,target in enumerate(vy):
            raw_matrix[target,int(scores[i].argmax())]+=1
            selective_matrix[target,CLASSES.index(outcomes[i]["sourcePrediction"]) if outcomes[i]["sourcePrediction"] else 3]+=1
        record={"camera_weight_per_egg":weight,"validation_groups":reports,"raw_confusion_matrix":raw_matrix.tolist(),
                "selective_confusion_matrix":selective_matrix.tolist(),"class_order":CLASSES}
        candidates.append(record)
        key=(float(np.mean([g["correct_classified"]/g["images"] for g in reports.values()])),
             float(np.mean([g["raw_correct"]/g["images"] for g in reports.values()])))
        if best_key is None or key>best_key:
            best_key, chosen=key,(record,coefficient,intercept,policy,outcomes)
        print(json.dumps({"stage":"candidate fitted","weight":weight,"validation":reports}),flush=True)
    selected, coefficient, intercept, policy, outcomes=chosen
    np.savez_compressed(RUN/"head.npz",coefficient=coefficient,intercept=intercept)
    np.savez_compressed(RUN/"training-references.npz",features=x,labels=y)
    np.savez_compressed(RUN/"development.npz",features=features,source_sha256=np.array([r["source_sha256"] for r in rows]))
    write(RUN/"gate-policy.json",policy)
    write(RUN/"candidates.json",candidates)
    write(RUN/"validation-outcomes.json",[{"source_sha256":r["source_sha256"],"source_label":r["source_label"],**v} for r,v in zip(val_rows,outcomes,strict=True)])
    write(RUN/"config.json",{"status":"EXPLORATORY_EXPLICIT_UNFERTILIZED_HEAD","class_order":CLASSES,
          "dataset_manifest":str(manifest),"dataset_sha256":audit["manifest_sha256"],"encoder_onnx_sha256":sha(model_path),
          "camera_weight_per_egg":selected["camera_weight_per_egg"],"operational_use_authorized":False,"limitations":audit["limitations"]})
    write(RUN/"metrics.json",{"scope":"DEVELOPMENT_VALIDATION_ONLY_NO_PHYSICAL_UNFERTILIZED_CHECK",
          "training_counts":dict(Counter(r["source_label"] for r in train_rows)),"validation":selected,
          "source_annotation_only":True,"test_images_opened":0,"claim_99_percent_supported":False})
    assert all(sha(ROOT/path)==digest for path,digest in protected.items())
    names=("head.npz","training-references.npz","development.npz","gate-policy.json","config.json","metrics.json","candidates.json","validation-outcomes.json","validation-inputs.json","experiment-plan.json")
    write(RUN/"selection-lock.json",{"scope":"LOCKED_EXPERIMENTAL_UNFERTILIZED_HEAD","physical_unfertilized_validation_passed":False,
          "artifacts":{name:sha(RUN/name) for name in names}})
    print(json.dumps({"stage":"complete","run":str(RUN),"selected_weight":selected["camera_weight_per_egg"],"validation":selected}),flush=True)


if __name__ == "__main__":
    main()
