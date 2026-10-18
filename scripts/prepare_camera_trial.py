"""Seal the learned three-class camera head for an explicitly experimental live trial."""
import hashlib
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/edge_api"))
from balut_api.model_service import ModelService, decode_jpeg, preprocess, sha256_file, view_consensus
from balut_api.selective_gate import CLASSES, decide


def main(multiangle=False):
    import numpy as np
    import onnx
    import onnxruntime as ort
    from onnx import numpy_helper
    from PIL import Image
    base = ROOT / "deployment/releases/automatic-recapture-20260912"
    run = ROOT / "ml/runs" / ("retained-multiangle-20261019" if multiangle else "retained-camera-20261018")
    release = ROOT / "deployment/releases" / ("camera-multiangle-trial-20261019" if multiangle else "camera-trial-20261018")
    if release.exists():
        raise FileExistsError("Preserve the prepared camera trial release")
    read = lambda path: json.loads(path.read_text())
    lock, adapted = read(run / "selection-lock.json"), read(run / "config.json")
    if multiangle and (not lock.get("admission_passed") or not read(run / "metrics.json").get("admission_passed")):
        raise ValueError("Multiangle candidate did not meet the predeclared comparison requirements")
    for name, digest in lock["artifacts"].items():
        if sha256_file(run / name) != digest:
            raise ValueError("Locked adaptation artifact changed")
    encoder = Path(adapted["encoder_onnx"])
    if sha256_file(encoder) != adapted["encoder_onnx_sha256"]:
        raise ValueError("Retained encoder changed")
    with np.load(run / "head.npz", allow_pickle=False) as bank:
        coefficient, intercept = bank["coefficient"], bank["intercept"]
    if coefficient.shape != (3, 1664) or intercept.shape != (3,) or not np.isfinite(coefficient).all() or not np.isfinite(intercept).all():
        raise ValueError("Invalid learned camera head")
    model = onnx.load(encoder)
    replacements = {"head.linear.weight": coefficient, "head.linear.bias": intercept}
    changed = set()
    for tensor in model.graph.initializer:
        if tensor.name in replacements:
            if list(tensor.dims) != list(replacements[tensor.name].shape):
                raise ValueError("Retained head dimensions changed")
            changed.add(tensor.name)
            tensor.CopyFrom(numpy_helper.from_array(replacements[tensor.name].astype(np.float32), tensor.name))
    if changed != set(replacements):
        raise ValueError("Expected retained linear classifier was not found")
    onnx.checker.check_model(model)
    model_dir = release / "egg-grade"
    model_dir.mkdir(parents=True)
    onnx.save(model, model_dir / "best.onnx")
    for name in ("gate-policy.json", "training-references.npz", "metrics.json", "selection-lock.json"):
        shutil.copy2(run / name, model_dir / name)
    config = read(base / "egg-grade/config.json")
    config.update(experimental=True, display_name="Camera model · experimental", manifest_sha256=adapted["dataset_sha256"],
                  selection_lock_sha256=sha256_file(run / "selection-lock.json"),
                  gate_policy_sha256=sha256_file(model_dir / "gate-policy.json"),
                  references_sha256=sha256_file(model_dir / "training-references.npz"))
    config["limitations"] += adapted["limitations"] + ["Live testing requested by the operator; 99 percent accuracy is not established."]
    (model_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    options = ort.SessionOptions()
    options.intra_op_num_threads, options.inter_op_num_threads = 4, 1
    old_session = ort.InferenceSession(str(encoder), sess_options=options, providers=["CPUExecutionProvider"])
    session = ort.InferenceSession(str(model_dir / "best.onnx"), sess_options=options, providers=["CPUExecutionProvider"])
    policy = read(model_dir / "gate-policy.json")
    with np.load(model_dir / "training-references.npz", allow_pickle=False) as bank:
        references, labels = bank["features"], bank["labels"]
    dataset = [json.loads(line) for line in Path(adapted["dataset_manifest"]).read_text().splitlines()]
    development = [r for r in dataset if (r.get("physical_egg_id") or "").startswith("physical-camera-20261018:") and r["partition"] in {"train", "validation"}]
    expected = read(run / "camera-validation-outcomes.json")
    expected_views = expected["views_after"] if multiangle else expected
    outcomes = {row["image_path"]: row for row in expected_views}
    grouped = {}
    maximum_error = 0.0
    for row in development:
        body = Path(row["image_path"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == row["source_sha256"]
        tensor = preprocess(body, config)
        _, old_features = old_session.run(None, {"images": tensor})
        scores, features = session.run(None, {"images": tensor})
        wanted = old_features @ coefficient.T + intercept
        np.testing.assert_allclose(features, old_features, atol=1e-7, rtol=1e-7)
        np.testing.assert_allclose(scores, wanted, atol=1e-4, rtol=1e-4)
        maximum_error = max(maximum_error, float(np.abs(scores - wanted).max()))
        if row["partition"] == "validation":
            prior = outcomes[row["image_path"]]
            with decode_jpeg(body) as image:
                actual = decide(scores[0], features[0], image, policy, references, labels)
            assert actual["sourcePrediction"] == prior["sourcePrediction"]
            assert actual["recaptureReasons"] == prior["recaptureReasons"]
            if multiangle and row["source_dataset"] == "physical-multiangle-20261019":
                grouped.setdefault(row["physical_egg_id"], []).append((row["source_sha256"], actual))
    if multiangle:
        expected_eggs = {row["egg_id"]: row for row in expected["after"]}
        assert set(grouped) == set(expected_eggs) and len(grouped) == 10
        for egg, views in grouped.items():
            prediction, reasons, _ = view_consensus([result for _, result in views], [digest for digest, _ in views])
            assert prediction == expected_eggs[egg]["sourcePrediction"]
            assert reasons == expected_eggs[egg]["recaptureReasons"]
    examples = []
    artifact = lambda p: {"path": p.relative_to(release).as_posix(), "sha256": sha256_file(p)}

    def inspect(body):
        scores, features = session.run(None, {"images": preprocess(body, config)})
        with decode_jpeg(body) as image:
            result = decide(scores[0], features[0], image, policy, references, labels)
        return scores[0], result

    for label in CLASSES:
        for row in dataset:
            if row["partition"] != "validation" or row["source_label"] != label or row.get("physical_egg_id"):
                continue
            body = Path(row["image_path"]).read_bytes()
            assert hashlib.sha256(body).hexdigest() == row["source_sha256"]
            from PIL import ImageOps
            with Image.open(Path(row["image_path"])) as image:
                target = model_dir / f"{label.lower()}.jpg"
                ImageOps.exif_transpose(image).convert("RGB").save(target, "JPEG", quality=95)
            scores, result = inspect(target.read_bytes())
            if result["sourcePrediction"] == label:
                examples.append({"file": artifact(target), "expected_scores": scores.tolist(),
                                 "expected_prediction": label, "expected_analysis_outcome": "CLASSIFIED",
                                 "expected_recapture_reasons": [], "partition": "historical validation software fixture"})
                break
        else:
            raise ValueError("No accepted validation fixture for " + label)
    dark = model_dir / "too-dark.jpg"
    Image.new("RGB", (224, 224), "black").save(dark, "JPEG")
    scores, result = inspect(dark.read_bytes())
    assert result["sourcePrediction"] is None and "LOW_CONTRAST" in result["recaptureReasons"]
    examples.append({"file": artifact(dark), "expected_scores": scores.tolist(), "expected_prediction": None,
                     "expected_analysis_outcome": "RECAPTURE_REQUIRED", "expected_recapture_reasons": result["recaptureReasons"],
                     "partition": "synthetic software fixture"})
    registry = {"schema_version": 1, "scope": "SOURCE_LABEL_SHADOW_ONLY", "release_id": release.name,
                "default_analysis_model": "egg-grade", "models": [{"id": "egg-grade", "model": artifact(model_dir / "best.onnx"),
                "config": artifact(model_dir / "config.json"), "gate_policy": artifact(model_dir / "gate-policy.json"),
                "training_references": artifact(model_dir / "training-references.npz"), "known_answer": examples[0]["file"],
                "expected_scores": examples[0]["expected_scores"], "expected_prediction": "DAY_16",
                "input_description": "Three paused live camera views; experimental camera model" if multiangle else "Single live camera frame; experimental three-class camera model"}], "software_test_examples": examples}
    (release / "registry.json").write_text(json.dumps(registry, indent=2) + "\n")
    (release / "registry.sha256").write_text(sha256_file(release / "registry.json") + "\n")
    shutil.copytree(base / "licenses", release / "licenses")
    service = ModelService()
    service.load(release / "registry.json", sha256_file(release / "registry.json"))
    assert service.describe()["experimental"] is True
    service.close()
    report = {"passed": True, "release": release.name, "registry_sha256": sha256_file(release / "registry.json"),
              "onnx_sha256": sha256_file(model_dir / "best.onnx"), "development_images_compared": len(development),
              "maximum_score_error": maximum_error, "software_fixtures": len(examples), "test_images_opened": 0}
    if multiangle:
        report["validation_groups_compared"] = len(grouped)
    (release / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--multiangle", action="store_true")
    main(parser.parse_args().multiangle)
