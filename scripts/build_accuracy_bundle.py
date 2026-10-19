"""Package the fixed validation-selected experiment with its complete comparison."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "ml" / "runs" / "accuracy-v2"
SOURCES = {
    "duck-candling": ("Duck candling status", "duck-candling-v1", "duck-egg-candling", "audit-v2"),
    "source-age16-18": ("Source-labelled Day 16 / Day 18", "source-age16-18-v1", "thesis-egg-candling", "audit-v1"),
    "pat-balut": ("Pat Fertilized / Reject / Unfertilized", "pat-balut-v1", "pat-balut", "audit-v2"),
}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    completion = read_json(RUN / "completion.json")
    lock_sha = sha(RUN / "selection-lock.json")
    assert completion["completed"] and lock_sha == completion["selection_lock_sha256"]
    entries = []
    for task, (title, baseline_name, source, audit_version) in SOURCES.items():
        directory = RUN / task
        metrics, config, parity = [read_json(directory / name) for name in ["metrics.json", "config.json", "onnx-parity.json"]]
        assert metrics["selection_lock_sha256"] == lock_sha
        assert metrics["checkpoint_sha256"] == sha(directory / "best.pt")
        assert parity["passed"] and parity["onnx_sha256"] == sha(directory / "best.onnx")
        candidates = [json.loads(line) for line in (directory / "candidates.jsonl").read_text(encoding="utf-8").splitlines()]
        assert len(candidates) == 42
        entries.append((task, title, baseline_name, source, audit_version, metrics, config, parity))

    lines = ["# Accuracy comparison — 2026-09-12", "",
             "The second experiment improved source-labelled Day 16/18 accuracy from 62.9% to 82.9%, and Pat status accuracy from 94.1% to 96.5%. The new duck-status candidate regressed from 95.4% to 93.1%; the original checkpoint is preserved. These are historical image/crop test results, not prospective physical-egg or device accuracy.", "",
             "| Task | Original test correct | Candidate test correct | Original → candidate accuracy | Candidate balanced accuracy | Candidate macro F1 |",
             "|---|---:|---:|---:|---:|---:|"]
    for task, title, baseline_name, source, audit_version, metrics, config, parity in entries:
        original, test = metrics["baseline_test"], metrics["test"]
        n = test["image_count"]
        lines.append(f"| {title} | {round(original['accuracy']*n)}/{n} | {test['correct']}/{n} | {original['accuracy']:.1%} → {test['accuracy']:.1%} | {test['balanced_accuracy']:.1%} | {test['macro_f1']:.3f} |")
    lines += ["", "## How the comparison was selected", "",
              "All three original audited manifests and their train/validation/test partitions were frozen. No labels were changed and no extra test images were removed. Each task compared 42 candidates: three pretrained frozen backbones (DINOv2 ViT-S/14, ConvNeXt-Tiny, EfficientNet-B0), eight L2 logistic-regression settings, and six one-versus-rest RBF SVM settings. The fixed representation averages original and horizontally flipped views, then L2-normalizes the embedding. Only the classifier is fitted to the source training labels.", "",
              "Selection uses validation macro F1, then balanced accuracy, then accuracy; exact ties keep the first candidate. All three task selections were recorded together before any candidate test features were extracted. The `promoted` field in that selection record means the candidate beat the baseline validation key; it is not a release approval or a claim that test performance improved. No further candidate was chosen after seeing these test results.", "",
              f"The experiment completed locally on the RTX 3080 in {completion['elapsed_seconds']:.1f} seconds, excluding ONNX export/verification. [Experiment plan](../ml/runs/accuracy-v2/experiment-plan.json), [selection record](../ml/runs/accuracy-v2/selection-lock.json). Selection record SHA-256: `{lock_sha}`.", "",
              "The test was already examined in the original experiment, so this is a retrospective comparison on the same historical holdout. It is not a newly blinded acceptance test. The 35-image age set is especially small: one prediction changes its accuracy by 2.86 percentage points. Physical egg identities and batch separation remain unavailable; image-family deduplication cannot establish independent eggs.", ""]

    for task, title, baseline_name, source, audit_version, metrics, config, parity in entries:
        test = metrics["test"]
        original = metrics["baseline_test"]
        card = [f"# {title} — accuracy-v2", "", "Status: exploratory source-label candidate; operational use not authorized.", "",
                f"Backbone: `{config['backbone']}`; head: `{json.dumps(config['hyperparameters'])}`. Frozen pretrained features, resize 224×224, ImageNet normalization, original/flip feature averaging, L2 normalization.", "",
                f"Source: [{config['provenance']['name']}]({config['provenance']['url']}); {config['provenance']['license']}. Species: {config['provenance']['species']}.", "",
                config["provenance"]["label_limitations"], "",
                f"Validation accuracy {metrics['validation']['accuracy']:.2%}; validation macro F1 {metrics['validation']['macro_f1']:.4f}. Historical test: {test['correct']}/{test['image_count']} correct ({test['accuracy']:.2%}), balanced accuracy {test['balanced_accuracy']:.2%}, macro F1 {test['macro_f1']:.4f}.", "",
                "| Source label | Test images | Original recall | Candidate recall | Candidate precision |", "|---|---:|---:|---:|---:|"]
        for label in config["class_order"]:
            record = test["per_class"][label]
            card.append(f"| {label} | {int(record['support'])} | {original['per_class'][label]['recall']:.1%} | {record['recall']:.1%} | {record['precision']:.1%} |")
        card += ["", "Confusion matrices: rows are truth and columns prediction, in the class order above.", "",
                 "Original:", "```json", json.dumps(original["confusion_matrix"]), "```", "",
                 "Candidate:", "```json", json.dumps(test["confusion_matrix"]), "```", "",
                 f"CPU Torch and ONNX each reproduce {parity['test_images_compared']}/{parity['test_images_compared']} frozen GPU class predictions. Maximum Torch/ONNX decision-score difference: {parity['maximum_absolute_torch_onnx_score_error']:.8g}. The ONNX input resolution is fixed at 224×224; variable batch sizes were exercised. Export tracing warnings about image geometry are consistent with this fixed input contract.", "",
                 "Scores are uncalibrated decision values, not probabilities. Public labels do not establish actual incubation age, biological viability, or food safety. Unknown egg/batch identity, no prospective device evaluation, and no ESP32 int8 validation remain material limits. These larger backbones are desktop research candidates, not verified microcontroller deployment models.", "",
                 f"Checkpoint SHA-256: `{metrics['checkpoint_sha256']}`", "", f"ONNX SHA-256: `{parity['onnx_sha256']}`", "",
                 f"Manifest SHA-256: `{config['manifest_sha256']}`", "", f"Selection record SHA-256: `{lock_sha}`", ""]
        (RUN / task / "model-card.md").write_text("\n".join(card), encoding="utf-8")
        lines += [f"## {title}", "", f"`{config['backbone']}` + `{config['hyperparameters']['kind']}`. [Model card](../ml/runs/accuracy-v2/{task}/model-card.md) · [PyTorch](../ml/runs/accuracy-v2/{task}/best.pt) · [ONNX](../ml/runs/accuracy-v2/{task}/best.onnx) · [all validation candidates](../ml/runs/accuracy-v2/{task}/candidates.jsonl).", ""]
    lines += ["The age candidate correctly classifies 12/15 Day 16 examples and 17/20 Day 18 examples. It still makes six errors in 35 images. Pat Reject recall improved only modestly, from 121/137 (88.3%) to 123/137 (89.8%); fourteen Reject-labelled crops are still missed. Duck abnormal recall remains 10/14 (71.4%), and the new candidate adds two fertile/infertile errors. Overall accuracy must not hide these weaknesses.", "",
              "## Use the candidate files", "", "From the EggGrade IoT workspace:", "", "```powershell",
              '.\\scripts\\Predict-Candling.ps1 -ImagePath "C:\\path\\to\\egg-crop.jpg" -Model age16-18 -Version accuracy-v2',
              '.\\scripts\\Predict-Candling.ps1 -ImagePath "C:\\path\\to\\egg-crop.jpg" -Model pat-status -Version accuracy-v2', "```", "",
              "Use a single-egg crop for age and Pat status, matching their training images. `-Version baseline` (also the unchanged default) runs the original models. `-Model duck-status -Version accuracy-v2` explicitly selects the new duck candidate, whose historical test result is lower. Every command continues to return `REVIEW_RECAPTURE` for operational grading.", "",
              "The new ZIP includes all three candidates plus the original duck-status baseline, PyTorch/ONNX files, class orders, scores, all candidate validation results, licenses, and inference code. Run its `predict.py` with an ONNX file using only NumPy, Pillow, and ONNX Runtime; Torch and network access are unnecessary for this inference route.", "",
              "For further progress on real duck-age accuracy, collect identified eggs from the actual candler with verified species, incubation/capture times, reviewer evidence, and whole-batch holdouts. [Collection guide](REAL_CANDLING_DATA_COLLECTION.md) · [Blank capture log](../data/templates/real-candling-capture-log.csv). No additional real-device accuracy can be claimed until those data exist and are evaluated.", ""]
    (ROOT / "docs" / "ACCURACY_RESULTS_2026-09-12.md").write_text("\n".join(lines), encoding="utf-8")

    cache = Path.home() / ".cache" / "torch" / "hub"
    pretrained = []
    for name, url in [
        ("dinov2_vits14_pretrain.pth", "https://dl.fbaipublicfiles.com/dinov2/dinov2_vits14/dinov2_vits14_pretrain.pth"),
        ("convnext_tiny-983f1562.pth", "https://download.pytorch.org/models/convnext_tiny-983f1562.pth"),
        ("efficientnet_b0_rwightman-7f5810bc.pth", "https://download.pytorch.org/models/efficientnet_b0_rwightman-7f5810bc.pth")]:
        path = cache / "checkpoints" / name
        pretrained.append({"file": name, "url": url, "sha256": sha(path), "bytes": path.stat().st_size})
    (RUN / "pretrained-sources.json").write_text(json.dumps(pretrained, indent=2)+"\n", encoding="utf-8")
    artifact = ROOT / "artifacts" / "balut-accuracy-v2-20260912.zip"
    if artifact.exists():
        raise FileExistsError("Preserve existing bundle")
    files = {}
    def add(path, destination):
        files[destination] = path
    for task, title, baseline_name, source, audit_version, metrics, config, parity in entries:
        for name in ["best.pt", "best.onnx", "config.json", "metrics.json", "onnx-parity.json", "model-card.md", "candidates.jsonl", "test-predictions.jsonl"]:
            add(RUN / task / name, f"models/{task}/{name}")
        for path in (ROOT / "data" / "public" / source / "export").glob("README*"):
            add(path, f"sources/{source}/{path.name}")
        for name in ["audit.json", "manifest.jsonl"]:
            add(ROOT / "data" / "public" / source / audit_version / name, f"sources/{source}/{name}")
    baseline = ROOT / "ml" / "runs" / "duck-candling-v1"
    for name in ["best.pt", "best.onnx", "config.json", "metrics.json", "onnx-parity.json", "model-card.md"]:
        add(baseline / name, f"models/duck-candling-baseline/{name}")
    for name in ["experiment-plan.json", "selection-lock.json", "completion.json", "pretrained-sources.json"]:
        add(RUN / name, f"experiment/{name}")
    for name in ["feature_models.py", "benchmark_public.py", "predict_public.py", "predict_onnx.py", "train_public.py", "export_features.py"]:
        add(ROOT / "ml" / "balut_ml" / name, f"ml/balut_ml/{name}")
    add(ROOT / "ml" / "balut_ml" / "predict_onnx.py", "predict.py")
    add(ROOT / "ml" / "requirements-public-training.lock.txt", "requirements-training.lock.txt")
    for name in ["ACCURACY_RESULTS_2026-09-12.md", "accuracy-methods-2026-09-12.md", "REAL_CANDLING_DATA_COLLECTION.md"]:
        add(ROOT / "docs" / name, f"docs/{name}")
    add(ROOT / "data" / "templates" / "real-candling-capture-log.csv", "data/templates/real-candling-capture-log.csv")
    dino = cache / "facebookresearch_dinov2_7764ea0f912e53c92e82eb78a2a1631e92725fc8"
    for path in dino.rglob("*.py"):
        if "__pycache__" not in path.parts:
            add(path, "ml/vendor/dinov2/" + path.relative_to(dino).as_posix())
    for name in ["LICENSE", "LICENSE_CELL_DINO_CODE", "LICENSE_CELL_DINO_MODELS", "LICENSE_XRAY_DINO_MODEL", "README.md", "MODEL_CARD.md"]:
        add(dino / name, f"ml/vendor/dinov2/{name}")
    add(ROOT / ".venv-ml" / "Lib" / "site-packages" / "torchvision-0.26.0+cu128.dist-info" / "LICENSE", "licenses/torchvision-LICENSE")
    readme = """# EggGrade IoT accuracy-v2 research models

Source-labelled age: 62.9% -> 82.9% (29/35); Pat status: 94.1% -> 96.5% (445/461).
The duck candidate regressed: 95.4% -> 93.1% (81/87). Its original 83/87 baseline is included separately.
All results are historical source-image/crop tests, not independently verified physical duck-egg or device accuracy.

## Run without Torch

Install Python 3.12, then `python -m pip install -r requirements-inference.txt`.

`python predict.py models/source-age16-18/best.onnx path/to/egg-crop.jpg`

Other model directories: `pat-balut`, `duck-candling` (candidate), `duck-candling-baseline` (original).
Age and Pat inputs must be single-egg crops. Outputs are uncalibrated decision scores, not biological confidence.
Read each model-card.md, config.json, and metrics.json. Operational output remains REVIEW_RECAPTURE.

## Records and limits

`experiment/` records the fixed candidate grid, validation selection, and original pretrained hashes.
`sources/` preserves dataset attribution, CC BY 4.0 notices, audits, and original manifest records. Manifest image paths reference the original workspace; image pixels are not bundled. Reproduction requires the same downloaded archives and extraction/crop audit outputs.
`docs/` contains the full before/after report and real-data collection guidance. Its workspace-relative links may require the original workspace; bundle model files are under `models/`.
All three new models include float32 ONNX and Torch weights. ONNX expects NCHW RGB 224x224 with config mean/std; the flip feature ensemble is already inside each candidate graph. Do not apply it a second time.
Torch inference source and pinned Apache-2.0 DINOv2 source are included under `ml/`. Set PYTHONPATH to `ml` and use `python -m balut_ml.predict_public models/source-age16-18/best.pt image.jpg` after installing torch and torchvision.
No field acceptance, physical egg/batch identity, age-source species verification, or ESP32 int8 deployment is established. Fourteen Pat Reject-labelled test crops are still missed; public Reject is not a food-safety label.
"""
    with zipfile.ZipFile(artifact, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        bundle.writestr("README.md", readme)
        bundle.writestr("requirements-inference.txt", "numpy==2.5.2\nPillow==12.3.0\nonnxruntime==1.30.0\n")
        bundle.writestr("ml/balut_ml/__init__.py", "")
        inventory = {}
        for destination, path in files.items():
            inventory[destination] = {"sha256": sha(path), "bytes": path.stat().st_size}
            bundle.write(path, destination)
        bundle.writestr("file-hashes.json", json.dumps(inventory, indent=2)+"\n")
    with zipfile.ZipFile(artifact) as bundle:
        assert bundle.testzip() is None
    result = {"bundle": str(artifact), "sha256": sha(artifact), "bytes": artifact.stat().st_size,
              "report": str(ROOT / "docs" / "ACCURACY_RESULTS_2026-09-12.md")}
    (RUN / "bundle.json").write_text(json.dumps(result, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
