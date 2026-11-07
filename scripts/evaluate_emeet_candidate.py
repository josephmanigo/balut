"""Evaluate the locked model once on reserved eggs and historical public Reject."""
import argparse
import json
import math
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "ml"), str(ROOT / "apps/edge_api")]
import numpy as np
import onnxruntime as ort
from balut_api.model_service import decode_jpeg, preprocess, view_consensus
from balut_api.selective_gate import decide
from balut_ml.emeet_development import validate_rows
from balut_ml.scientific_metrics import classification_metrics, cluster_intervals
from scripts.capture_emeet_egg import finish, sha, verify_candidate, write
from scripts.seal_emeet_candidate import CLASSES, jpeg_body


def wilson(correct, total):
    if not total:
        return None
    z = 1.959963984540054
    p = correct / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return {"lower": max(0., centre - half), "upper": min(1., centre + half),
            "method": "95% Wilson interval over eggs; ignores unknown batch dependence"}


def evaluate(dataset):
    lock = verify_candidate(dataset)
    run = Path(lock["run"])
    output = run / "test"
    if output.exists():
        raise FileExistsError("Preserve the first locked test; do not tune using its results")
    plan = json.loads((dataset / "collection-plan.json").read_text())
    rows = []
    for egg, assignment in sorted(plan["eggs"].items()):
        if assignment["partition"] != "test":
            continue
        completed = [p for p in (dataset / "captures" / egg).glob("*/record.json")
                     if json.loads(p.read_text())["status"] == "complete"]
        if len(completed) != 1:
            raise ValueError(f"Need exactly one complete reserved capture for {egg}")
        record = finish(dataset, completed[0].parent)
        if len(record["views"]) != assignment["sampled_frames"]:
            raise ValueError("Unexpected reserved frame count")
        for view in record["views"]:
            rows.append({"egg_id": egg, "physical_egg_id": record["physical_egg_id"], "source_label": record["source_label"],
                         "partition": "test", "view_index": view["view_index"], "image_path": str(completed[0].parent / view["image"]),
                         "source_sha256": view["sha256"], "pixel_sha256": view["pixel_sha256"]})
    if len(rows) != 600:
        raise ValueError("Require 600 reserved age frames from the six planned test eggs")
    reject_path = dataset / "reject/manifest.jsonl"
    if sha(reject_path) != json.loads((dataset / "reject/audit.json").read_text())["manifest_sha256"]:
        raise ValueError("Reject manifest changed")
    rows += [r for r in map(json.loads, reject_path.read_text().splitlines()) if r["partition"] == "test"]
    development = json.loads((run / "development-manifest.json").read_text())
    validate_rows(development + rows, allow_test=True)
    output.mkdir()
    write(output / "test-manifest.json", rows)
    config = {"normalization_mean": [.485, .456, .406], "normalization_std": [.229, .224, .225]}
    options = ort.SessionOptions(); options.intra_op_num_threads = 4; options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(run / "best.onnx"), sess_options=options, providers=["CPUExecutionProvider"])
    policy = json.loads((run / "calibration/gate-policy.json").read_text())
    with np.load(run / "calibration/training-references.npz", allow_pickle=False) as bank:
        references, labels = bank["features"], bank["labels"]
    matrix = np.zeros((3, 3), dtype=int); gated = np.zeros((3, 4), dtype=int)
    results = []
    for index, row in enumerate(rows):
        source = Path(row["image_path"])
        if sha(source) != row["source_sha256"]:
            raise ValueError("Test evidence changed")
        body = jpeg_body(source); started = time.perf_counter()
        scores, embedding = session.run(None, {"images": preprocess(body, config)})
        with decode_jpeg(body) as image:
            result = decide(scores[0], embedding[0], image, policy, references, labels)
        truth = CLASSES.index(row["source_label"]); prediction = int(scores[0].argmax())
        matrix[truth, prediction] += 1
        gated[truth, CLASSES.index(result["sourcePrediction"]) if result["sourcePrediction"] else 3] += 1
        results.append({**row, "truth": row["source_label"], "raw_prediction": CLASSES[prediction],
                        "scores": scores[0].tolist(), "inference_seconds": time.perf_counter() - started, **result})
        if (index + 1) % 100 == 0:
            print(json.dumps({"test_frames": index + 1, "total": len(rows)}), flush=True)
    write(output / "predictions.json", results)
    eggs = []
    for egg in sorted({r["egg_id"] for r in results if r.get("physical_egg_id")}):
        views = [r for r in results if r.get("egg_id") == egg]
        attempts = []
        for offset in (0, 3, 6):
            selected = views[offset:offset + 3]
            prediction, reasons, accepted = view_consensus(selected, [v["source_sha256"] for v in selected])
            attempts.append({"sourcePrediction": prediction, "reasons": reasons, "accepted_views": accepted,
                             "raw_prediction": CLASSES[int(np.asarray([v["scores"] for v in selected]).mean(0).argmax())]})
        eggs.append({"egg_id": egg, "truth": views[0]["truth"], "attempts": attempts,
                     "first_attempt_correct": attempts[0]["sourcePrediction"] == views[0]["truth"],
                     "bounded_retry_prediction": next((a["sourcePrediction"] for a in attempts if a["sourcePrediction"]), None)})
    first_correct = sum(e["first_attempt_correct"] for e in eggs)
    summary = {"class_order": CLASSES, "overall": classification_metrics(matrix, gated),
               "age_test_eggs": len(eggs), "age_test_frames": 600, "historical_reject_test_frames": len(rows) - 600,
               "controlled_age_pilot": {"eggs": eggs, "first_attempt_correct": first_correct, "total": len(eggs),
                   "first_attempt_correct_over_all": first_correct / len(eggs), "interval": wilson(first_correct, len(eggs)),
                   "scope": "Reserved physical eggs, replayed three-frame groups from first video capture; not separate live scan repeats"},
               "image_metrics_uncertainty": cluster_intervals(results, CLASSES, repeats=2000),
               "field_accuracy_established": False, "confirmed_physical_reject_test_eggs": 0,
               "test_used_for_tuning": False, "promoted": False}
    write(output / "metrics.json", summary)
    verify_candidate(dataset)
    write(output / "evaluation-lock.json", {"candidate_lock_sha256": sha(dataset / "candidate-lock.json"),
          "artifacts": {name: sha(output / name) for name in ["test-manifest.json", "predictions.json", "metrics.json"]}})
    print(json.dumps({"complete": True, "raw_accuracy": summary["overall"]["raw_accuracy"],
                      "macro_f1": summary["overall"]["macro_f1"], "first_attempt_eggs_correct": first_correct,
                      "test_eggs": len(eggs), "field_accuracy_established": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("dataset", type=Path)
    args = parser.parse_args(); evaluate(args.dataset.resolve())
