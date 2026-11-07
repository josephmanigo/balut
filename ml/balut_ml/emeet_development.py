"""Verify operator-labeled EMEET development eggs and cache exact serving features."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "apps/edge_api"))
from scripts.capture_emeet_egg import finish, sha, verify_candidate, write
from balut_api.model_service import ModelService, active_registry, decode_jpeg, preprocess, view_consensus
from balut_api.selective_gate import decide


def validate_rows(rows, allow_test=False):
    groups, identities = {}, {}
    for row in rows:
        if row["partition"] not in ({"train", "validation", "test"} if allow_test else {"train", "validation"}):
            raise ValueError("Test images must stay outside development")
        group = row.get("physical_egg_id") or row["duplicate_group"]
        if groups.setdefault(group, row["partition"]) != row["partition"]:
            raise ValueError("An egg or image family crosses partitions")
        for field in ("source_sha256", "pixel_sha256"):
            identity = (row["partition"], row["source_label"])
            if identities.setdefault((field, row[field]), identity) != identity:
                raise ValueError("An image crosses labels or partitions")


def development_rows(dataset, require_complete=False, include_test=False):
    dataset = dataset.resolve()
    if include_test:
        verify_candidate(dataset)
    plan_path = dataset / "collection-plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    expected = {key for key, value in plan["eggs"].items() if include_test or value["partition"] != "test"}
    found, rows = set(), []
    for egg_id in sorted(expected):
        for path in sorted((dataset / "captures" / egg_id).glob("*/record.json")):
            record = json.loads(path.read_text(encoding="utf-8-sig"))
            if record["status"] != "complete":
                continue
            if egg_id in found:
                raise ValueError("Multiple completed captures for one physical egg")
            record = finish(dataset, path.parent)
            if record["egg_id"] != egg_id or record.get("model_used_for_label") is not False:
                raise ValueError("Invalid operator label provenance")
            if len(record["views"]) != plan["eggs"][egg_id].get("sampled_frames", plan["sampled_frames"]):
                raise ValueError("Wrong number of retained views")
            found.add(egg_id)
            for view in record["views"]:
                rows.append({"egg_id": egg_id, "physical_egg_id": record["physical_egg_id"],
                             "source_dataset": dataset.name, "source_label": record["source_label"],
                             "partition": record["partition"], "view_index": view["view_index"],
                             "source_sha256": view["sha256"], "pixel_sha256": view["pixel_sha256"],
                             "image_path": str(path.parent / view["image"]), "record_sha256": sha(path),
                             "plan_sha256": sha(plan_path)})
    if require_complete and found != expected:
        raise ValueError("Missing development eggs: " + ", ".join(sorted(expected - found)))
    validate_rows(rows, allow_test=include_test)
    return rows


def extract(dataset, output):
    rows = development_rows(dataset)
    if not rows:
        raise ValueError("No completed development eggs")
    output.mkdir(parents=True, exist_ok=True)
    registry = active_registry(ROOT)
    contract = sha(registry) + ":" + sha(ROOT / "apps/edge_api/balut_api/model_service.py")
    cache_path = output / "features.npz"
    cache = {}
    if cache_path.exists():
        with np.load(cache_path, allow_pickle=False) as saved:
            if str(saved["contract"]) != contract:
                raise ValueError("Encoder or preprocessing changed; use a new cache directory")
            cache = {digest: (feature, scores) for digest, feature, scores in
                     zip(saved["source_sha256"], saved["features"], saved["scores"], strict=True)}
    models = ModelService()
    models.load(registry, sha(registry))
    model = models.models[models.analysis_model_id]
    camera = model.get("camera") or model
    outcomes, features, scores = [], [], []
    try:
        for row in rows:
            body = Path(row["image_path"]).read_bytes()
            if row["source_sha256"] not in cache:
                raw, embedding = model["session"].run(None, {model["input_name"]: preprocess(body, model["config"])})
                effective = embedding @ camera["coefficient"].T + camera["intercept"] if "coefficient" in camera else raw
                cache[row["source_sha256"]] = (embedding[0], effective[0])
            feature, score = cache[row["source_sha256"]]
            with decode_jpeg(body) as image:
                decision = decide(score, feature, image, camera["policy"], camera["references"], camera["reference_labels"])
            features.append(feature)
            scores.append(score)
            outcomes.append(decision)
        values = np.asarray(features, dtype=np.float32)
        if values.shape != (len(rows), camera["references"].shape[1]) or not np.isfinite(values).all():
            raise ValueError("Invalid encoder features")
        np.testing.assert_allclose(np.linalg.norm(values, axis=1), 1, atol=1e-4)
        temporary = cache_path.with_suffix(".tmp")
        with temporary.open("wb") as stream:
            np.savez_compressed(stream, features=values, scores=np.asarray(scores),
                                source_sha256=np.array([r["source_sha256"] for r in rows]), contract=contract)
        temporary.replace(cache_path)
        write(output / "rows.json", rows)
        eggs = []
        for egg_id in sorted({r["egg_id"] for r in rows}):
            indexes = [i for i, row in enumerate(rows) if row["egg_id"] == egg_id]
            attempts = []
            for offset in (0, 3, 6):
                selected = indexes[offset:offset + 3]
                prediction, reasons, accepted = view_consensus([outcomes[i] for i in selected],
                                                              [rows[i]["source_sha256"] for i in selected])
                attempts.append({"prediction": prediction, "reasons": reasons, "accepted_views": accepted})
            eggs.append({"egg_id": egg_id, "label": rows[indexes[0]]["source_label"],
                         "partition": rows[indexes[0]]["partition"], "attempts": attempts})
        write(output / "baseline.json", {"release": models.release_id, "eggs": eggs,
              "role": "Labeled development replay, not an independent field test",
              "test_images_opened": 0, "field_accuracy_established": False})
        return {"eggs": len(eggs), "frames": len(rows), "baseline": str(output / "baseline.json")}
    finally:
        models.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(extract(args.dataset, args.output)))
