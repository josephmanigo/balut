"""Seal verified local ONNX models into a versioned, standalone serving release."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/edge_api"))
from balut_api.model_service import preprocess, sha256_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "deployment/releases/source-labels-20260912")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Use a fresh release directory; sealed releases are immutable")
    import onnxruntime as ort
    from PIL import Image, ImageOps
    release = {"schema_version": 1, "scope": "SOURCE_LABEL_SHADOW_ONLY", "release_id": args.output.name, "models": []}
    selections = [
        ("age16-18", "accuracy-v2/source-age16-18", "thesis-egg-candling", "audit-v1", "Single-egg candling crop; source day labels, species unverified"),
        ("pat-status", "accuracy-v2/pat-balut", "pat-balut", "audit-v2", "Single-egg crop; original Fertilized/Reject/Unfertilized labels"),
        ("duck-status", "duck-candling-v1", "duck-egg-candling", "audit-v2", "Full published candling framing; original baseline preserved"),
    ]
    args.output.mkdir(parents=True)
    licenses = args.output / "licenses"
    licenses.mkdir()
    shutil.copy2(Path.home() / ".cache/torch/hub/facebookresearch_dinov2_7764ea0f912e53c92e82eb78a2a1631e92725fc8/LICENSE", licenses / "DINOv2-LICENSE")
    shutil.copy2(ROOT / ".venv-ml/Lib/site-packages/torchvision-0.26.0+cu128.dist-info/LICENSE", licenses / "torchvision-LICENSE")
    for model_id, run_name, source, audit, description in selections:
        run = ROOT / "ml/runs" / run_name
        parity = json.loads((run / "onnx-parity.json").read_text())
        if not parity["passed"] or sha256_file(run / "best.onnx") != parity["onnx_sha256"]:
            raise ValueError("Model is not the verified export")
        output = args.output / model_id
        output.mkdir()
        for name in ["best.onnx", "config.json", "metrics.json", "model-card.md", "onnx-parity.json"]:
            shutil.copy2(run / name, output / name)
        source_root = ROOT / "data/public" / source
        for license_file in (source_root / "export").glob("README*"):
            shutil.copy2(license_file, output / license_file.name)
        audit_path = source_root / audit
        manifest = audit_path / "manifest.jsonl"
        audit_data = json.loads((audit_path / "audit.json").read_text())
        if sha256_file(manifest) != audit_data["manifest_sha256"]:
            raise ValueError("Source manifest changed")
        row = next(r for r in map(json.loads, manifest.read_text().splitlines()) if r["partition"] == "validation")
        if sha256_file(Path(row["image_path"])) != row["source_sha256"]:
            raise ValueError("Known-answer source image changed")
        fixture = output / "known-answer.jpg"
        with Image.open(row["image_path"]) as image:
            ImageOps.exif_transpose(image).convert("RGB").save(fixture, "JPEG", quality=95)
        config = json.loads((output / "config.json").read_text())
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        session = ort.InferenceSession(str(output / "best.onnx"), sess_options=options, providers=["CPUExecutionProvider"])
        scores = session.run(None, {"images": preprocess(fixture.read_bytes(), config)})[0][0].tolist()
        artifact = lambda path: {"path": path.relative_to(args.output).as_posix(), "sha256": sha256_file(path)}
        release["models"].append({"id": model_id, "model": artifact(output / "best.onnx"), "config": artifact(output / "config.json"),
                                  "known_answer": artifact(fixture), "expected_scores": scores, "input_description": description,
                                  "known_answer_provenance": {"source_url": config["provenance"]["url"], "source_sha256": row["source_sha256"],
                                                               "adaptation": "EXIF orientation applied and RGB JPEG quality 95", "partition": "validation"}})
    path = args.output / "registry.json"
    path.write_text(json.dumps(release, indent=2)+"\n", encoding="utf-8")
    (args.output / "registry.sha256").write_text(sha256_file(path)+"\n", encoding="utf-8")
    print(json.dumps({"registry": str(path.resolve()), "sha256": sha256_file(path), "models": len(release["models"]), "scope": release["scope"]}, indent=2))


if __name__ == "__main__":
    main()
