"""Fit and lock one camera-specific age candidate; never activate it."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np

from .age_specialist import context_for, feature_view, head_arrays, head_scores, metrics
from balut_api.model_service import ModelService, preprocess

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "output/physical-pilot-20261018"
RUN = DATA / "candidate"
REGISTRY = ROOT / "deployment/releases/automatic-recapture-20260912/registry.json"
SPEC = {"kind": "logistic", "view": "fused", "C": 10.0}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, value):
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)


def records(partitions):
    plan = json.loads((DATA / "capture-plan.json").read_text())
    rows = []
    for egg, partition in plan["split"].items():
        if partition not in partitions:
            continue
        row = json.loads((DATA / f"{egg}.json").read_text())
        if (row.get("freshness") not in {"queued_frame_discarded", "live_single_frame_prediction", "live_stream_refreshed"}
                or row["egg_id"] != egg or row["partition"] != partition or row["image"] != f"{egg}.jpg"
                or row["reported_age_days"] != int(egg.split("-")[0]) or row["sha256"] != sha(DATA / row["image"])):
            raise ValueError("Pilot image or identity changed")
        rows.append(row)
    if len(rows) != 10 * len(partitions) or len({r["sha256"] for r in rows}) != len(rows):
        raise ValueError("Incomplete or duplicate pilot images")
    if any(sum(r["partition"] == split and r["reported_age_days"] == age for r in rows) != 5
           for split in partitions for age in (16, 18)):
        raise ValueError("Each partition requires five distinct eggs per age")
    return rows


def extract(model, rows):
    from balut_api.model_service import decode_jpeg
    features, contexts = [], []
    for row in rows:
        body = (DATA / row["image"]).read_bytes()
        scores, embedding = model["session"].run(None, {model["input_name"]: preprocess(body, model["config"])})
        with decode_jpeg(body) as image:
            contexts.append(context_for(image, scores[0], embedding[0], model["policy"],
                                        model["references"], model["reference_labels"]))
        features.append(embedding[0])
    return np.stack(features), np.array([int(r["reported_age_days"] == 18) for r in rows]), contexts


def report(rows, features, truth, contexts, arrays):
    signed = head_scores(features, SPEC, arrays)
    predicted = (signed > 0).astype(int)
    baseline, baseline_rows = metrics(contexts, truth)
    return {"independent_eggs": len(rows), "candidate_raw_correct": int((predicted == truth).sum()),
            "candidate_raw_accuracy": float((predicted == truth).mean()),
            "candidate_classification_authorized": False,
            "baseline": baseline,
            "candidate_by_age": {str(age): {"eggs": int((truth == i).sum()),
                "correct": int(((predicted == truth) & (truth == i)).sum())} for i, age in enumerate((16, 18))},
            "eggs": [{"egg_id": row["egg_id"], "reported_age_days": row["reported_age_days"],
                      "candidate_raw_age": 18 if predicted[i] else 16, "signed_score": float(signed[i]),
                      "baseline": baseline_rows[i]} for i, row in enumerate(rows)]}


def run(stage):
    if stage == "fit" and RUN.exists():
        raise FileExistsError("Candidate already exists; never refit after opening the final test")
    if stage == "test":
        lock = json.loads((RUN / "selection-lock.json").read_text())
        if (RUN / "test-report.json").exists():
            raise FileExistsError("Final test already evaluated")
        if sha(Path(__file__)) != lock["evaluator_sha256"]:
            raise ValueError("Locked evaluation code changed")
        for name, digest in lock["artifacts"].items():
            if sha(RUN / name) != digest:
                raise ValueError("Locked candidate changed")
        if sha(REGISTRY) != lock["registry_sha256"] or sha(DATA / "capture-plan.json") != lock["plan_sha256"]:
            raise ValueError("Locked release or capture plan changed")
        development = records({"train", "validation"})
        if {r["egg_id"]: r["sha256"] for r in development} != lock["development_images"]:
            raise ValueError("Development images changed after lock")
        rows = records({"test"})
        if {r["sha256"] for r in rows} & set(lock["development_images"].values()):
            raise ValueError("Test image overlaps development")
        if any(datetime.fromisoformat(r.get("captured_at", r["recorded_at"])) <= datetime.fromisoformat(lock["locked_at"]) for r in rows):
            raise ValueError("Final test must be captured after candidate lock")
    else:
        development = records({"train", "validation"})
    service = ModelService()
    service.load(REGISTRY, None)
    try:
        model = service.models["egg-grade"]
        if stage == "fit":
            from sklearn.linear_model import LogisticRegression
            train_rows = [r for r in development if r["partition"] == "train"]
            validation_rows = [r for r in development if r["partition"] == "validation"]
            train_features, train_truth, _ = extract(model, train_rows)
            validation_features, validation_truth, contexts = extract(model, validation_rows)
            estimator = LogisticRegression(C=SPEC["C"], class_weight="balanced", max_iter=1000, random_state=0)
            estimator.fit(feature_view(train_features, SPEC["view"]), train_truth)
            arrays = head_arrays(estimator, SPEC["kind"])
            np.testing.assert_allclose(head_scores(validation_features, SPEC, arrays),
                                       estimator.decision_function(feature_view(validation_features, SPEC["view"])), atol=1e-10)
            result = report(validation_rows, validation_features, validation_truth, contexts, arrays)
            RUN.mkdir()
            np.savez(RUN / "age-head.npz", **arrays)
            write_new(RUN / "spec.json", {**SPEC, "candidate_count": 1, "class_order": [16, 18],
                      "scope": "EXPLORATORY_CAMERA_PILOT", "trained_on": [r["egg_id"] for r in train_rows],
                      "limitations": ["One farm and camera session", "No reject-class examples", "No automatic deployment"]})
            write_new(RUN / "validation-report.json", result)
            write_new(RUN / "selection-lock.json", {"locked_at": datetime.now(timezone.utc).isoformat(),
                      "evaluator_sha256": sha(Path(__file__)),
                      "registry_sha256": sha(REGISTRY), "plan_sha256": sha(DATA / "capture-plan.json"),
                      "development_images": {r["egg_id"]: r["sha256"] for r in development},
                      "artifacts": {name: sha(RUN / name) for name in ("age-head.npz", "spec.json", "validation-report.json")}})
        else:
            with np.load(RUN / "age-head.npz", allow_pickle=False) as bank:
                arrays = {key: bank[key] for key in bank.files}
            features, truth, contexts = extract(model, rows)
            result = report(rows, features, truth, contexts, arrays)
            write_new(RUN / "test-report.json", result)
        print(json.dumps({k: v for k, v in result.items() if k != "eggs"}), flush=True)
    finally:
        service.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("fit", "test"))
    run(parser.parse_args().stage)
