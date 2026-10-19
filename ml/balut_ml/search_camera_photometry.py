"""Test fixed egg-crop photometry without CUDA or historical test images."""
import io
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image, ImageOps
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from .train_grouped_camera import ROOT, DATA, sha, write, metrics
from .train_grouped_kernel import fit_models, scores_for
from .search_camera_representation import INTERIOR

BASE = ROOT / "ml/runs/grouped-camera-20261019"
REPS = ROOT / "ml/runs/representation-search-20261019"
RUN = ROOT / "ml/runs/camera-photometry-20261019"
GRID = [{"photometry_weight": w, "C": c, "gamma": g, "camera_weight": 20}
        for w in (.1, .25, .5) for c in (1., 10., 100.) for g in (.2, 1., 5.)]


def photometry(body):
    with Image.open(io.BytesIO(body)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB").resize((224, 224), Image.Resampling.BILINEAR)
        left, top, right, bottom = INTERIOR
        crop = np.asarray(image, dtype=np.float32)[top:bottom, left:right] / 255
    values = []
    for strip in np.array_split(crop, 3, axis=0):
        for tile in np.array_split(strip, 4, axis=1):
            gray = tile @ np.array([.299, .587, .114], dtype=np.float32)
            values.extend(tile.mean((0, 1)))
            values.extend(tile.std((0, 1)))
            values.extend(float(np.mean(gray < limit)) for limit in (.1, .25, .5))
            values.extend([float(np.mean(tile[:, :, 0] > tile[:, :, 1] + .15)),
                           float(np.mean(tile[:, :, 0] > tile[:, :, 2] + .15)), float(np.mean(tile.max(2) > .95))])
    result = np.asarray(values, dtype=np.float32)
    assert result.shape == (144,) and np.isfinite(result).all()
    return result


def combine(deep, color, weight):
    normalized = color / np.maximum(np.linalg.norm(color, axis=1, keepdims=True), 1e-8)
    return np.concatenate((deep * np.float32((1 - weight) ** .5), normalized * np.float32(weight ** .5)), axis=1)


def main():
    if RUN.exists():
        raise FileExistsError("Preserve the completed or interrupted photometry experiment")
    for folder in (BASE, REPS):
        lock = json.loads((folder / "selection-lock.json").read_text())
        assert all(sha(folder / name) == digest for name, digest in lock["artifacts"].items())
    rows = [json.loads(line) for line in (DATA / "manifest.jsonl").read_text().splitlines()]
    rows = [r for r in rows if r["partition"] in ("train", "validation")]
    with np.load(REPS / "selected-features.npz", allow_pickle=False) as bank:
        deep, truth = bank["features"], bank["truth"]
    with np.load(BASE / "development.npz", allow_pickle=False) as bank:
        folds = bank["folds"]
        np.testing.assert_array_equal(truth, bank["truth"])
        np.testing.assert_array_equal(bank["source_sha256"], [r["source_sha256"] for r in rows])
    groups = np.array([r.get("physical_egg_id") or r["duplicate_group"] for r in rows])
    physical = np.array([bool(r.get("physical_egg_id")) for r in rows])
    protected = {str(p.relative_to(ROOT)): sha(p) for p in (Path(__file__), DATA / "manifest.jsonl", BASE / "selection-lock.json",
                 REPS / "selection-lock.json", ROOT / "deployment/active-release.txt")}
    RUN.mkdir()
    write(RUN / "experiment-plan.json", {"method": "CPU_FIXED_CROP_PHOTOMETRY_PLUS_FROZEN_FEATURES", "grid": GRID,
          "crop_224": INTERIOR, "descriptor": "3x4 tiles: RGB mean/std, gray dark fractions at0.1/0.25/0.5, red-green/red-blue dominance0.15, saturated fraction0.95; 144 values",
          "reason": "Generic retained image features may miss subtle crop transmission/color differences. This is exploratory image measurement, not calibrated opacity or biological age proof.",
          "normalization": "StandardScaler fitted only on fold training images, row L2 normalization, weighted concatenation with fused-interior deep features",
          "selection": "Raw overall and both camera-age recalls >=96%, then weaker age recall, mean age recall, source macro F1",
          "folds": 5, "development_images": len(rows), "physical_development_eggs": 20, "test_images_opened": 0,
          "development_caveat": "Repeated development research is not independent field accuracy; all known physical eggs and source families remain grouped",
          "reject_scope": "Public Unfertilized renamed Reject, R1/R2/R3 excluded", "protected_files": protected})
    started = time.perf_counter(); colors = []
    inputs = json.loads((BASE / "serving-inputs.json").read_text())
    for item in inputs:
        path = Path(item["path"]); assert sha(path) == item["serving_jpeg_sha256"]
        colors.append(photometry(path.read_bytes()))
    colors = np.stack(colors)
    np.savez_compressed(RUN / "photometry.npz", features=colors, source_sha256=np.array([r["source_sha256"] for r in rows]))
    normalized = {}
    for fold in range(5):
        fit, held = np.flatnonzero(folds != fold), np.flatnonzero(folds == fold)
        assert not set(groups[fit]) & set(groups[held])
        scaler = StandardScaler().fit(colors[fit])
        normalized[fold] = scaler.transform(colors).astype(np.float32)
    best = None; selected = None
    for spec in GRID:
        scores = np.full((len(rows), 3), np.nan, dtype=np.float32)
        for fold in range(5):
            fit, held = np.flatnonzero(folds != fold), np.flatnonzero(folds == fold)
            x = combine(deep, normalized[fold], spec["photometry_weight"])
            models = fit_models(x[fit], truth[fit], [rows[i] for i in fit], spec)
            scores[held] = scores_for(models, x[held])
        assert np.isfinite(scores).all(); pred = scores.argmax(1)
        age = [float(np.mean(pred[physical & (truth == label)] == label)) for label in range(2)]
        measured = metrics(scores, truth); source = metrics(scores[~physical], truth[~physical])
        target = measured["accuracy"] >= .96 and min(age) >= .96
        key = (target, min(age), float(np.mean(age)), source["f1"])
        record = {"spec": spec, "raw": measured, "camera_age_recall": age, "source_raw": source, "development_target_passed": target}
        with (RUN / "search.jsonl").open("a") as stream:
            stream.write(json.dumps(record, allow_nan=False) + "\n")
        if best is None or key > best:
            best, selected = key, record
            np.savez_compressed(RUN / "selected-oof.npz", scores=scores, truth=truth, folds=folds)
            write(RUN / "selected.json", record)
        print(json.dumps({"spec": spec, "camera_age_recall": age, "overall_raw": measured["accuracy"], "development_target_passed": target}), flush=True)
    assert all(sha(ROOT / name) == digest for name, digest in protected.items())
    write(RUN / "metrics.json", {"selected": selected, "candidates": len(GRID), "test_images_opened": 0, "promoted": False,
          "elapsed_seconds": time.perf_counter() - started})
    names = ["experiment-plan.json", "photometry.npz", "search.jsonl", "selected.json", "selected-oof.npz", "metrics.json"]
    write(RUN / "selection-lock.json", {"artifacts": {name: sha(RUN / name) for name in names}, "test_images_opened": 0})
    print(json.dumps({"complete": True, "selected": selected}), flush=True)


if __name__ == "__main__":
    with threadpool_limits(limits=2):
        main()
