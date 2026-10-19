"""Refit the retained logistic head on its sealed training features without deployment."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ml"), str(ROOT / "apps/edge_api")]
import numpy as np
from sklearn.linear_model import LogisticRegression
from balut_ml.train_unfertilized import fit_weights, CLASSES
from balut_ml.unfertilized_data import sha


def main(output):
    run = ROOT / "ml/runs/retained-unfertilized-serving-20261019"
    lock = json.loads((run / "selection-lock.json").read_text())
    assert all(sha(run / name) == digest for name, digest in lock["artifacts"].items())
    config = json.loads((run / "config.json").read_text())
    manifest = Path(config["dataset_manifest"])
    assert sha(manifest) == config["dataset_sha256"]
    rows = [json.loads(line) for line in manifest.read_text().splitlines() if json.loads(line)["partition"] == "train"]
    with np.load(run / "development.npz", allow_pickle=False) as data:
        bank = dict(zip(data["source_sha256"].tolist(), data["features"], strict=True))
    x = np.stack([bank[r["source_sha256"]] for r in rows]); y = np.array([CLASSES.index(r["source_label"]) for r in rows])
    model = LogisticRegression(C=100, max_iter=3000, random_state=42)
    model.fit(x, y, sample_weight=fit_weights(rows, 20))
    with np.load(run / "head.npz", allow_pickle=False) as data:
        differences = {"coefficient": float(np.max(np.abs(model.coef_.astype(np.float32)-data["coefficient"]))),
                       "intercept": float(np.max(np.abs(model.intercept_.astype(np.float32)-data["intercept"])))}
    assert max(differences.values()) == 0.0 and model.n_iter_.max() < 3000
    report = {"method": "CPU_REPRODUCTION_OF_RETAINED_LOGISTIC_FIT", "solver": "lbfgs", "maximum_iterations": 3000,
              "reproduced_iterations": model.n_iter_.tolist(), "converged_before_limit": True,
              "float32_parameter_maximum_differences": differences, "original_solver_iteration_count_was_saved": False,
              "training_images": len(rows), "active_artifacts_changed": False,
              "versions": {name: importlib.metadata.version(name) for name in ("numpy", "scikit-learn", "scipy", "torch", "onnxruntime")},
              "source_sha256": sha(Path(__file__)), "manifest_sha256": sha(manifest), "selection_lock_sha256": sha(run / "selection-lock.json")}
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output)
