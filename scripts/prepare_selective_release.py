"""Seal the fixed selective model and known-answer classification/recapture fixtures."""
from pathlib import Path
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / "apps/edge_api"))
from balut_api.model_service import ModelService, preprocess, decode_jpeg, sha256_file
from balut_api.selective_gate import decide


def main():
    import numpy as np
    import onnxruntime as ort
    from PIL import Image, ImageOps
    run = ROOT / "ml/runs/selective-v2"
    release = ROOT / "deployment/releases/automatic-recapture-20260912"
    parity = json.loads((run / "onnx-parity.json").read_text())
    assert parity["passed"] and sha256_file(run / "best.onnx") == parity["onnx_sha256"]
    release.mkdir(parents=True,exist_ok=False)
    model_dir = release / "egg-grade"
    model_dir.mkdir()
    for name in ["best.onnx","config.json","metrics.json","onnx-parity.json","onnx-gpu-parity.json","gate-policy.json","training-references.npz","experiment-plan.json","selection-lock.json"]:
        shutil.copy2(run / name,model_dir / name)
    config = json.loads((run / "config.json").read_text())
    policy = json.loads((run / "gate-policy.json").read_text())
    bank = np.load(run / "training-references.npz")
    development = np.load(run / "selected-development.npz")
    manifest = ROOT / "ml/runs/three-class-v1/manifest.jsonl"
    assert sha256_file(manifest) == config["manifest_sha256"]
    rows = [json.loads(line) for line in manifest.read_text().splitlines()]
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    session = ort.InferenceSession(str(model_dir / "best.onnx"),sess_options=options,providers=["CPUExecutionProvider"])
    sample_root = ROOT / "data/recapture-test-samples"
    sample_root.mkdir(parents=True,exist_ok=False)
    artifact = lambda path:{"path":path.relative_to(release).as_posix(),"sha256":sha256_file(path)}
    examples = []

    def inference(path):
        scores,vector = session.run(None,{"images":preprocess(path.read_bytes(),config)})
        result = decide(scores[0],vector[0],decode_jpeg(path.read_bytes()),policy,bank["features"],bank["labels"])
        return scores[0],result

    def add(path,result,scores,provenance):
        shutil.copy2(path,sample_root / path.name)
        examples.append({"file":artifact(path),"expected_prediction":result["sourcePrediction"],"expected_analysis_outcome":result["analysisOutcome"],
                         "expected_recapture_reasons":result["recaptureReasons"],"expected_scores":scores.tolist(),**provenance})

    for class_id,label in enumerate(config["class_order"]):
        fixture = model_dir / (label.lower()+".jpg")
        for index,truth,scores in zip(development["indexes"],development["truth"],development["scores"]):
            if int(truth)!=class_id or int(scores.argmax())!=class_id:
                continue
            row = rows[int(index)]
            assert row["partition"] == "validation" and sha256_file(Path(row["image_path"])) == row["source_sha256"]
            with Image.open(row["image_path"]) as image:
                ImageOps.exif_transpose(image).convert("RGB").save(fixture,"JPEG",quality=95)
            actual,result = inference(fixture)
            if result["sourcePrediction"] == label:
                add(fixture,result,actual,{"source_label":row["original_source_label"],"source_dataset":row["source_dataset"],"source_sha256":row["source_sha256"],"partition":"validation","adaptation":"EXIF orientation, RGB JPEG quality 95"})
                break
        else:
            raise ValueError("No accepted validation fixture for "+label)
    dark = model_dir / "too-dark.jpg"
    Image.new("RGB",(224,224),"black").save(dark,"JPEG")
    actual,result = inference(dark)
    assert result["sourcePrediction"] is None and "LOW_CONTRAST" in result["recaptureReasons"]
    add(dark,result,actual,{"source_dataset":"synthetic software fixture","partition":"not a training or accuracy image","adaptation":"solid black JPEG to test automatic recapture"})
    unclear = model_dir / "unclear-egg.jpg"
    for index in development["indexes"]:
        row = rows[int(index)]
        if row["source_dataset"] != "age": continue
        with Image.open(row["image_path"]) as image:
            ImageOps.exif_transpose(image).convert("RGB").save(unclear,"JPEG",quality=95)
        actual,result = inference(unclear)
        if result["sourcePrediction"] is None and "AMBIGUOUS_APPEARANCE" in result["recaptureReasons"]:
            add(unclear,result,actual,{"source_label":row["original_source_label"],"source_dataset":row["source_dataset"],"source_sha256":row["source_sha256"],"partition":"validation","adaptation":"EXIF orientation, RGB JPEG quality 95"})
            break
    else: raise ValueError("No validation ambiguity fixture")
    registry = {"schema_version":1,"scope":"SOURCE_LABEL_SHADOW_ONLY","release_id":release.name,"default_analysis_model":"egg-grade",
                "models":[{"id":"egg-grade","model":artifact(model_dir / "best.onnx"),"config":artifact(model_dir / "config.json"),
                           "gate_policy":artifact(model_dir / "gate-policy.json"),"training_references":artifact(model_dir / "training-references.npz"),
                           "known_answer":examples[0]["file"],"expected_scores":examples[0]["expected_scores"],"expected_prediction":"DAY_16",
                           "input_description":"One cropped candling JPEG; automatic appearance prediction or unclassified recapture request"}],"software_test_examples":examples}
    (release / "registry.json").write_text(json.dumps(registry,indent=2)+"\n")
    (release / "registry.sha256").write_text(sha256_file(release / "registry.json")+"\n")
    shutil.copytree(ROOT / "deployment/releases/automatic-three-class-20260912/licenses",release / "licenses")
    shutil.copy2(ROOT / "deployment/releases/source-labels-20260912/licenses/DINOv2-LICENSE",release / "licenses/DINOv2-LICENSE")
    (sample_root / "manifest.json").write_text(json.dumps({"scope":"Known-answer software checks only; no independent accuracy evidence","examples":examples},indent=2)+"\n")
    service = ModelService()
    service.load(release / "registry.json",sha256_file(release / "registry.json"))
    for example in examples:
        result = service.predict("egg-grade",(release / example["file"]["path"]).read_bytes())
        assert result["sourcePrediction"] == example["expected_prediction"] and result["recaptureReasons"] == example["expected_recapture_reasons"] and result["reviewRequired"] is False
    service.close()
    print(json.dumps({"registry":str(release / "registry.json"),"sha256":sha256_file(release / "registry.json"),"verified_examples":len(examples)},indent=2))


if __name__ == "__main__":
    main()
