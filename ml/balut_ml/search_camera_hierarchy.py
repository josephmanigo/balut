"""CPU grouped comparison of an age specialist and an unchanged Reject detector."""
from collections import Counter
import json
from pathlib import Path
import time

import numpy as np
from sklearn.svm import SVC
from threadpoolctl import threadpool_limits

from .train_grouped_camera import ROOT, DATA, sha, write, metrics
from .train_grouped_kernel import fit_models, scores_for

BASE = ROOT / "ml/runs/grouped-camera-20261019"
REPS = ROOT / "ml/runs/representation-search-20261019"
RUN = ROOT / "ml/runs/camera-hierarchy-20261019"
PROFILES = ["fused-interior", "dino-interior", "efficient-interior", "fused-dual", "dino-dual", "efficient-dual"]
GRID = [{"C": c, "gamma": g, "camera_only": camera} for c in (1., 10., 100.) for g in (.2, 1., 5.) for camera in (True, False)]


def hierarchical_scores(age, general):
    age = np.asarray(age, dtype=np.float32)
    general = np.asarray(general, dtype=np.float32)
    if general.shape != (len(age), 3) or not np.isfinite(general).all() or not np.isfinite(age).all():
        raise ValueError("Expected finite binary age scores and three general scores")
    reject_difference = general[:, 2] - general[:, :2].max(1)
    return np.stack((-age / 2, age / 2, np.abs(age) / 2 + reject_difference), axis=1)


def fit_age(features, truth, rows, spec):
    if set(truth) != {0, 1}:
        raise ValueError("An age fit needs both age labels and no Reject rows")
    counts = Counter(r["physical_egg_id"] for r in rows if r.get("physical_egg_id"))
    weights = np.array([20 / counts[r["physical_egg_id"]] if r.get("physical_egg_id") else 1. for r in rows])
    for label in range(2):
        selected = truth == label
        weights[selected] *= 1128 / weights[selected].sum()
    model = SVC(C=spec["C"], gamma=spec["gamma"], kernel="rbf", cache_size=128)
    model.fit(features, truth, sample_weight=weights)
    return model


def main():
    if RUN.exists():
        raise FileExistsError("Preserve the completed or interrupted hierarchy comparison")
    for folder in (BASE, REPS):
        lock = json.loads((folder / "selection-lock.json").read_text())
        assert all(sha(folder / name) == digest for name, digest in lock["artifacts"].items())
    rows = [json.loads(line) for line in (DATA / "manifest.jsonl").read_text().splitlines()]
    rows = [r for r in rows if r["partition"] in ("train", "validation")]
    with np.load(BASE / "development.npz", allow_pickle=False) as bank:
        full, truth, folds = bank["features"], bank["truth"], bank["folds"]
        np.testing.assert_array_equal(bank["source_sha256"], [r["source_sha256"] for r in rows])
    with np.load(REPS / "dino-interior.npz", allow_pickle=False) as bank:
        dino = bank["features"]
    with np.load(REPS / "efficient-interior.npz", allow_pickle=False) as bank:
        efficient = bank["features"]
    combine = lambda *x: np.concatenate(x, axis=1) / np.float32(len(x) ** .5)
    interior = combine(dino, efficient)
    with np.load(REPS / "selected-features.npz", allow_pickle=False) as bank:
        np.testing.assert_array_equal(interior, bank["features"])
    features = {"fused-interior": interior, "dino-interior": dino, "efficient-interior": efficient,
                "fused-dual": combine(full, interior), "dino-dual": combine(full[:, :384] * np.float32(2 ** .5), dino),
                "efficient-dual": combine(full[:, 384:] * np.float32(2 ** .5), efficient)}
    for x in features.values():
        np.testing.assert_allclose(np.linalg.norm(x, axis=1), 1, atol=1e-4)
    physical = np.array([bool(r.get("physical_egg_id")) for r in rows])
    groups = np.array([r.get("physical_egg_id") or r["duplicate_group"] for r in rows])
    protected = {str(p.relative_to(ROOT)): sha(p) for p in (Path(__file__), DATA / "manifest.jsonl", BASE / "selection-lock.json",
                 REPS / "selection-lock.json", REPS / "dino-interior.npz", REPS / "efficient-interior.npz", ROOT / "deployment/active-release.txt")}
    RUN.mkdir()
    write(RUN / "experiment-plan.json", {"method": "CPU_GROUPED_AGE_SPECIALIST_WITH_FIXED_REJECT_DETECTOR", "profiles": PROFILES,
          "grid": GRID, "age_weights": "1128 per age; physical egg total weight20 before age balancing; source family image weight1",
          "reject_detector": "Fixed fused-interior C10 gamma1 camera_weight20 general three-class classifier, fit separately in each fold",
          "selection": "Both camera-age recalls and raw overall >=96%, then weaker age recall, mean age recall, source macro F1",
          "folds": 5, "development_images": len(rows), "physical_development_eggs": 20, "test_images_opened": 0,
          "source_label_scope": "Reject denotes original Unfertilized labels, not general defects. R1/R2/R3 excluded.",
          "score_scope": "Hierarchical decision scores, not calibrated probabilities; no data or labels depend on model predictions",
          "historical_role": "Already-inspected regression is kept closed during search; development scores are not field accuracy",
          "protected_files": protected})
    started = time.perf_counter()
    general = np.full((len(rows), 3), np.nan, dtype=np.float32)
    for fold in range(5):
        fit, held = np.flatnonzero(folds != fold), np.flatnonzero(folds == fold)
        assert not set(groups[fit]) & set(groups[held])
        models = fit_models(interior[fit], truth[fit], [rows[i] for i in fit], {"C": 10., "gamma": 1., "camera_weight": 20})
        general[held] = scores_for(models, interior[held])
    best = None
    selected = None
    for profile in PROFILES:
        x = features[profile]
        for spec in GRID:
            age_scores = np.full(len(rows), np.nan, dtype=np.float32)
            for fold in range(5):
                fit = np.flatnonzero((folds != fold) & (truth < 2) & (physical if spec["camera_only"] else True))
                held = np.flatnonzero(folds == fold)
                assert not set(groups[fit]) & set(groups[held])
                model = fit_age(x[fit], truth[fit], [rows[i] for i in fit], spec)
                age_scores[held] = model.decision_function(x[held])
            scores = hierarchical_scores(age_scores, general)
            pred = scores.argmax(1)
            age_recall = [float(np.mean(pred[physical & (truth == label)] == label)) for label in range(2)]
            measured = metrics(scores, truth)
            source = metrics(scores[~physical], truth[~physical])
            target = measured["accuracy"] >= .96 and min(age_recall) >= .96
            key = (target, min(age_recall), float(np.mean(age_recall)), source["f1"])
            record = {"profile": profile, "spec": spec, "camera_age_recall": age_recall, "raw": measured,
                      "source_raw": source, "development_target_passed": target, "selection_key": key}
            with (RUN / "search.jsonl").open("a") as stream:
                stream.write(json.dumps(record, allow_nan=False) + "\n")
            if best is None or key > best:
                best, selected = key, record
                np.savez_compressed(RUN / "selected-oof.npz", scores=scores, truth=truth, folds=folds, age_scores=age_scores, general_scores=general)
                write(RUN / "selected.json", selected)
            print(json.dumps({"profile": profile, "spec": spec, "camera_age_recall": age_recall,
                              "overall_raw": measured["accuracy"], "development_target_passed": target}), flush=True)
    assert all(sha(ROOT / name) == digest for name, digest in protected.items())
    write(RUN / "metrics.json", {"selected": selected, "candidates": len(PROFILES) * len(GRID), "test_images_opened": 0,
          "promoted": False, "elapsed_seconds": time.perf_counter() - started})
    names = ["experiment-plan.json", "search.jsonl", "selected.json", "selected-oof.npz", "metrics.json"]
    write(RUN / "selection-lock.json", {"artifacts": {name: sha(RUN / name) for name in names}, "test_images_opened": 0})
    print(json.dumps({"complete": True, "selected": selected}), flush=True)


if __name__ == "__main__":
    with threadpool_limits(limits=2):
        main()
