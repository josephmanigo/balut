"""Seal the unified classifier and three validation examples for one-click analysis."""
from pathlib import Path
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/edge_api"))
from balut_api.model_service import ModelService, preprocess, sha256_file


def main():
    import numpy as np
    import onnxruntime as ort
    from PIL import Image, ImageOps
    run = ROOT / "ml/runs/three-class-v1"
    output = ROOT / "deployment/releases/automatic-three-class-20260912"
    output.mkdir(parents=True, exist_ok=False)
    parity = json.loads((run / "onnx-parity.json").read_text())
    if not parity["passed"] or sha256_file(run / "best.onnx") != parity["onnx_sha256"]:
        raise ValueError("Export parity is missing or stale")
    model_dir = output / "egg-grade"
    model_dir.mkdir()
    for name in ["best.onnx", "config.json", "metrics.json", "model-card.md", "onnx-parity.json", "experiment-plan.json", "selection-lock.json"]:
        shutil.copy2(run / name, model_dir / name)
    config = json.loads((run / "config.json").read_text())
    manifest = run / "manifest.jsonl"
    if sha256_file(manifest) != config["manifest_sha256"]:
        raise ValueError("Training manifest changed")
    rows = [json.loads(line) for line in manifest.read_text().splitlines()]
    frozen = np.load(run / "selected-validation.npz")
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    session = ort.InferenceSession(str(model_dir / "best.onnx"), sess_options=options, providers=["CPUExecutionProvider"])
    artifact = lambda path: {"path": path.relative_to(output).as_posix(), "sha256": sha256_file(path)}
    examples = []
    sample_root = ROOT / "data/automatic-test-samples"
    sample_root.mkdir(parents=True, exist_ok=False)
    for class_id, label in enumerate(config["class_order"]):
        # These are explicitly known-answer fixtures, not extra accuracy tests.
        for index, truth, scores in zip(frozen["indexes"], frozen["truth"], frozen["scores"]):
            if int(truth) != class_id or int(scores.argmax()) != class_id:
                continue
            row = rows[int(index)]
            if row["partition"] != "validation" or sha256_file(Path(row["image_path"])) != row["source_sha256"]:
                raise ValueError("Validation fixture identity changed")
            fixture = model_dir / (label.lower() + ".jpg")
            with Image.open(row["image_path"]) as image:
                ImageOps.exif_transpose(image).convert("RGB").save(fixture, "JPEG", quality=95)
            actual = session.run(None, {"images": preprocess(fixture.read_bytes(), config)})[0][0]
            if int(actual.argmax()) == class_id:
                break
        else:
            raise ValueError("No stable JPEG fixture for " + label)
        shutil.copy2(fixture, sample_root / fixture.name)
        examples.append({"file": artifact(fixture), "expected_prediction": label, "expected_scores": actual.tolist(),
                         "source_label": row["original_source_label"], "source_dataset": row["source_dataset"],
                         "source_sha256": row["source_sha256"], "partition": "validation", "adaptation": "EXIF orientation applied, RGB JPEG quality 95"})
    registry = {"schema_version": 1, "scope": "SOURCE_LABEL_SHADOW_ONLY", "release_id": output.name,
                "default_analysis_model": "egg-grade", "models": [{"id": "egg-grade", "model": artifact(model_dir / "best.onnx"),
                "config": artifact(model_dir / "config.json"), "known_answer": examples[0]["file"],
                "expected_scores": examples[0]["expected_scores"], "input_description": "One cropped candling image; automatic Day 16 / Day 18 / Reject source-label prediction"}],
                "software_test_examples": examples}
    (output / "registry.json").write_text(json.dumps(registry, indent=2)+"\n")
    (output / "registry.sha256").write_text(sha256_file(output / "registry.json")+"\n")
    license_dir = output / "licenses"
    license_dir.mkdir()
    shutil.copy2(ROOT / "deployment/releases/source-labels-20260912/licenses/torchvision-LICENSE", license_dir / "torchvision-LICENSE")
    for source in ["thesis-egg-candling", "pat-balut"]:
        target = license_dir / source
        target.mkdir()
        for file in (ROOT / "data/public" / source / "export").glob("README*"):
            shutil.copy2(file, target / file.name)
    (sample_root / "manifest.json").write_text(json.dumps({"scope": "Known-answer software tests, not independent accuracy evidence", "examples": examples}, indent=2)+"\n")
    service = ModelService()
    service.load(output / "registry.json", sha256_file(output / "registry.json"))
    for example in examples:
        predicted = service.predict(service.analysis_model_id, (output / example["file"]["path"]).read_bytes())
        if predicted["sourcePrediction"] != example["expected_prediction"]:
            raise ValueError("Serving fixture mismatch")
    service.close()
    print(json.dumps({"registry": str(output / "registry.json"), "sha256": sha256_file(output / "registry.json"), "verified_examples": len(examples), "models": 1}))


if __name__ == "__main__":
    main()
