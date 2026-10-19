"""Evaluate the locked epoch candidate on the previously inspected regression images."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/edge_api"))
from balut_api.model_service import ModelService, decode_jpeg
from PIL import Image, ImageOps

RUN = ROOT / "ml/runs/finetuned-epochs-reject-20261019"
OUT = ROOT / "ml/runs/finetuned-epochs-reject-historical-20261019"
DATA = ROOT / "data/local/retained-camera-epochs-reject-20261019"
RELEASE = ROOT / "deployment/releases/finetuned-epochs-reject-trial-20261019"
CLASSES = ["DAY_16", "DAY_18", "REJECT"]


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def summarize(records):
    raw = [[0] * 3 for _ in CLASSES]
    selective = [[0] * 4 for _ in CLASSES]
    for row in records:
        truth = CLASSES.index(row["truth"])
        raw[truth][CLASSES.index(row["raw_prediction"])] += 1
        prediction = row["sourcePrediction"]
        selective[truth][CLASSES.index(prediction) if prediction else 3] += 1
    total = len(records)
    correct = sum(selective[i][i] for i in range(3))
    accepted = sum(sum(row[:3]) for row in selective)
    return {"images": total, "raw_confusion_matrix": raw, "selective_confusion_matrix": selective,
            "raw_accuracy": sum(raw[i][i] for i in range(3)) / total,
            "classified": accepted, "correct_classified": correct, "wrong_classified": accepted - correct,
            "recapture": total - accepted, "accepted_accuracy": correct / accepted if accepted else None,
            "coverage": accepted / total, "correct_over_all": correct / total}


def main():
    if OUT.exists():
        raise FileExistsError("Preserve the completed or interrupted held-out evaluation")
    lock = json.loads((RUN / "selection-lock.json").read_text())
    assert all(sha(RUN / name) == digest for name, digest in lock["artifacts"].items())
    audit = json.loads((DATA / "audit.json").read_text())
    assert sha(DATA / "manifest.jsonl") == audit["manifest_sha256"]
    rows = [json.loads(line) for line in (DATA / "manifest.jsonl").read_text().splitlines()]
    partitions = {}
    for row in rows:
        group = row.get("physical_egg_id") or row["duplicate_group"]
        assert partitions.setdefault(group, row["partition"]) == row["partition"]
    test = [row for row in rows if row["partition"] == "test"]
    assert Counter(row["training_label"] for row in test) == {"DAY_16": 285, "DAY_18": 290, "REJECT": 74}
    registry = RELEASE / "registry.json"
    config = json.loads(registry.read_text())
    entry = config["models"][0]
    assert entry["model"]["sha256"] == "0da988f66d5c0bacd3d3a9acbbc839c165e319b4e0ad381686282609c2e2de46"
    protected = {str(path.relative_to(ROOT)): sha(path) for path in
                 [RUN / "selection-lock.json", RUN / "head.npz", RUN / "gate-policy.json", registry,
                  RELEASE / entry["model"]["path"], Path(__file__)]}
    OUT.mkdir()
    write(OUT / "evaluation-plan.json", {"started_at": datetime.now(timezone.utc).isoformat(),
          "class_order": CLASSES, "images": len(test), "dataset_sha256": audit["manifest_sha256"],
          "protected_files": protected,
          "protocol": "One locked evaluation of every test image; actual ONNX CPU camera head and gates. No fitting, candidate selection, threshold changes, or per-image retries.",
          "serving_inputs": "Native JPEG bytes unchanged; public PNG crops converted to RGB JPEG quality95 as for validation.",
          "limitations": ["Per-image decisions, not live three-view scan results",
              "Repeated age views represent ten physical test eggs, not 540 independent eggs",
              "Some reserved age eggs appeared in earlier live checks using the previous Reject release",
              "Public source families lack physical egg/batch identities and independently verified embryo status",
              "No confirmed Unfertilized physical egg is available for a live check"]})
    service = ModelService()
    records = []
    try:
        service.load(registry, sha(registry))
        assert service.describe()["models"][0]["classOrder"] == CLASSES
        with (OUT / "outcomes.jsonl").open("x", encoding="utf-8") as output:
            for index, row in enumerate(test):
                source = Path(row["image_path"])
                assert sha(source) == row["source_sha256"]
                body = source.read_bytes()
                with Image.open(io.BytesIO(body)) as image:
                    if image.format != "JPEG":
                        converted = io.BytesIO()
                        ImageOps.exif_transpose(image).convert("RGB").save(converted, "JPEG", quality=95)
                        body = converted.getvalue()
                decode_jpeg(body)
                result = service._predict("egg-grade", body, camera=True)
                scores = result["sourceClassDecisionScores"]
                record = {"source_sha256": row["source_sha256"], "serving_jpeg_sha256": hashlib.sha256(body).hexdigest(),
                          "truth": row["training_label"], "physical_egg_id": row.get("physical_egg_id"),
                          "source_dataset": row["source_dataset"], "duplicate_group": row["duplicate_group"],
                          "raw_prediction": max(scores, key=scores.get),
                          **{key: result[key] for key in ["sourcePrediction", "recaptureRequested", "recaptureReasons",
                               "sourceClassDecisionScores", "modelReleaseId", "modelSha256", "cameraHeadSha256"]}}
                assert record["recaptureRequested"] == (record["sourcePrediction"] is None)
                records.append(record)
                output.write(json.dumps(record, allow_nan=False) + "\n")
                output.flush()
                if (index + 1) % 25 == 0 or index + 1 == len(test):
                    print(json.dumps({"evaluated": index + 1, "total": len(test)}), flush=True)
    finally:
        service.close()
    groups, eggs = {}, {}
    for record in records:
        group = ("camera:" if record["physical_egg_id"] else "source:") + record["truth"]
        groups.setdefault(group, []).append(record)
        if record["physical_egg_id"]:
            eggs.setdefault(record["physical_egg_id"], []).append(record)
    assert len(eggs) == 10 and sum(bool(r["physical_egg_id"]) for r in records) == 540
    assert all(sha(ROOT / name) == digest for name, digest in protected.items())
    metrics = {"scope": "LOCKED_HISTORICAL_REGRESSION_NOT_NEW_INDEPENDENT_TEST",
               "completed_at": datetime.now(timezone.utc).isoformat(), "class_order": CLASSES,
               "overall": summarize(records), "groups": {name: summarize(values) for name, values in groups.items()},
               "physical_eggs": {name: summarize(values) for name, values in eggs.items()},
               "test_images_opened": len(records), "model_or_policy_changed": False,
               "physical_reject_validation_passed": False}
    write(OUT / "metrics.json", metrics)
    names = ("evaluation-plan.json", "outcomes.jsonl", "metrics.json")
    write(OUT / "evaluation-lock.json", {"artifacts": {name: sha(OUT / name) for name in names}})
    print(json.dumps(metrics["overall"]), flush=True)


if __name__ == "__main__":
    main()

