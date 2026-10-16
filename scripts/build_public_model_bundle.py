"""Build a local, source-attributed handoff from completed training artifacts."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUNS = [
    ("duck-candling-v1", "Duck candling status", "duck-egg-candling", "audit-v2"),
    ("source-age16-18-v1", "Source-labelled Day 16 vs Day 18", "thesis-egg-candling", "audit-v1"),
    ("pat-balut-v1", "Pat source-labelled Fertilized / Reject / Unfertilized", "pat-balut", "audit-v2"),
]


def main():
    entries = []
    for run_name, title, source, audit_name in RUNS:
        run = ROOT / "ml" / "runs" / run_name
        metrics = json.loads((run / "metrics.json").read_text(encoding="utf-8"))
        config = json.loads((run / "config.json").read_text(encoding="utf-8"))
        audit = json.loads((ROOT / "data" / "public" / source / audit_name / "audit.json").read_text(encoding="utf-8"))
        parity = json.loads((run / "onnx-parity.json").read_text(encoding="utf-8"))
        assert metrics["checkpoint_sha256"] == hashlib.sha256((run / "best.pt").read_bytes()).hexdigest()
        assert parity["passed"] and parity["onnx_sha256"] == hashlib.sha256((run / "best.onnx").read_bytes()).hexdigest()
        entries.append((run_name, title, source, audit_name, metrics, config, audit, parity))
    lines = ["# Balut public-dataset training results — 2026-09-12", "",
             "Three MobileNetV3-Small classifiers were trained locally on the RTX 3080. These are exploratory source-label models; no operational model release was created.", "",
             "The Day 16/18 experiment is too weak for reliable age decisions, and its source does not document duck species. The duck-status model also misses abnormal examples despite high overall accuracy. Preserve the review workflow.", "",
             "| Model | Train / validation / test | Test accuracy | Balanced accuracy | Macro F1 | Selected epoch |",
             "|---|---:|---:|---:|---:|---:|"]
    for name, title, source, audit_name, metrics, config, audit, parity in entries:
        counts = [sum(audit["partition_counts"][p].values()) for p in ("train", "validation", "test")]
        test = metrics["test"]
        lines.append(f"| {title} | {' / '.join(map(str, counts))} | {test['accuracy']:.1%} | {test['balanced_accuracy']:.1%} | {test['macro_f1']:.3f} | {metrics['best_epoch']} |")
    lines += ["", "Counts are images or annotated egg crops, not independent physical eggs. Selection used validation loss; test predictions were computed only after checkpoint selection. No test result was used to select a later checkpoint.", ""]
    for name, title, source, audit_name, metrics, config, audit, parity in entries:
        run = ROOT / "ml" / "runs" / name
        test = metrics["test"]
        card = [f"# {title}", "", "Status: **TRAINED EXPLORATORY ONLY — operational use not authorized**", "",
                f"Source: [{config['provenance']['name']}]({config['provenance']['url']}). License: {config['provenance']['license']}.", "",
                f"Species documentation: {config['provenance']['species']}.", "",
                config["provenance"]["label_limitations"], "",
                f"Architecture: MobileNetV3-Small initialized from Torchvision ImageNet-1K weights; RGB 224×224; ImageNet mean/std; original source labels; seed {config['seed']}.", "",
                f"Completed {metrics['epochs_completed']} epochs in {metrics['elapsed_seconds']:.1f} seconds. Selected epoch {metrics['best_epoch']} by validation loss.", "",
                f"Test accuracy: {test['accuracy']:.2%}; balanced accuracy: {test['balanced_accuracy']:.2%}; macro F1: {test['macro_f1']:.4f}. Majority-class test baseline: {metrics['majority_class_test_baseline']:.2%}.", "",
                "| Original source label | Test examples | Precision | Recall | F1 |", "|---|---:|---:|---:|---:|"]
        for label in config["class_order"]:
            result = test["per_class"][label]
            card.append(f"| `{label}` | {int(result['support'])} | {result['precision']:.1%} | {result['recall']:.1%} | {result['f1-score']:.3f} |")
        card += ["", "Confusion matrix rows are true labels; columns are predicted labels, in the class order above:", "", "```json", json.dumps(test["confusion_matrix"]), "```", "",
                 f"Split method: {audit['split_method']}", "", f"Image groups: {audit['image_group_count']}. Independent physical egg count: unknown.", "",
                 "Exclusions: " + json.dumps(audit["exclusion_counts"]) + ".", "",
                 f"Float32 ONNX parity: {parity['argmax_agreement_count']}/{parity['test_images_compared']} matching class predictions; maximum absolute logit error {parity['maximum_absolute_logit_error']:.8g}.", "",
                 "Limits: no verified incubation timestamps, physical egg/batch isolation, prospective device test, confidence calibration, or ESP32 int8 validation. Scores are source-specific and do not establish food safety, viability, or actual chronological age. No comparison of image hashes can prove that all repeated physical eggs were isolated.", "",
                 f"Checkpoint SHA-256: `{metrics['checkpoint_sha256']}`", "", f"Manifest SHA-256: `{config['manifest_sha256']}`", ""]
        (run / "model-card.md").write_text("\n".join(card), encoding="utf-8")
        lines += [f"## {title}", "", f"[Model card](../ml/runs/{name}/model-card.md) · [PyTorch weights](../ml/runs/{name}/best.pt) · [ONNX weights](../ml/runs/{name}/best.onnx) · [Metrics](../ml/runs/{name}/metrics.json)", "",
                  f"Source: [{config['provenance']['name']}]({config['provenance']['url']}). Retained {audit['retained_images']} images/crops. Exclusions: `{json.dumps(audit['exclusion_counts'])}`.", "",
                  f"[Dataset audit](../data/public/{source}/{audit_name}/audit.json) · [Inspected sample sheet](../data/public/{source}/{audit_name}/contact-sheet.jpg)", ""]
    lines += ["## Run a prediction locally", "", "Use a single-egg candling image. For the age and Pat models, crop the egg first, matching training. The duck-status model used the full published image framing.", "",
              "```powershell", '.\\scripts\\Predict-Candling.ps1 -ImagePath "C:\\path\\to\\egg.jpg" -Model duck-status',
              '.\\scripts\\Predict-Candling.ps1 -ImagePath "C:\\path\\to\\egg-crop.jpg" -Model age16-18',
              '.\\scripts\\Predict-Candling.ps1 -ImagePath "C:\\path\\to\\egg-crop.jpg" -Model pat-status', "```", "",
              "These commands return original source labels and uncalibrated probabilities. The operational outcome remains REVIEW_RECAPTURE. No production API, simulator, firmware release, or physical grading authority was changed.", "",
              "The original archives and their README/license files remain under data/public. Training source, exact manifests, epoch histories, test predictions, checkpoints, and ONNX parity results are retained for audit. The two first experiments used conservative dHash/filename grouping. Pat uses filename grouping plus dHash and RGB similarity because grayscale hashes alone falsely match different egg silhouettes.", ""]
    report = ROOT / "docs" / "TRAINING_RESULTS_2026-09-12.md"
    report.write_text("\n".join(lines), encoding="utf-8")
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    archive = artifacts / "balut-public-models-20260912.zip"
    readme = "# Balut exploratory trained models\n\nThree source-label MobileNetV3-Small models. Read each model-card.md and metrics.json before use. None is an operational or food-safety release. Day 16/18 performance is weak and source species is unknown.\n\nInstall Python 3.12 and run `pip install torch torchvision pillow`. Then run:\n\n`python predict.py models/duck-candling-v1/best.pt path/to/egg.jpg`\n\nOther directories: source-age16-18-v1 (cropped egg, source day labels) and pat-balut-v1 (cropped egg, source Fertilized/Reject/Unfertilized labels).\n\nONNX models require RGB NCHW float32, resized to 224x224, values scaled to 0..1 and normalized with mean [0.485,0.456,0.406], std [0.229,0.224,0.225]. Outputs are logits, in config.json class_order.\n\nOriginal training-data licenses/attribution are in sources/. Precise training environment is recorded in the lock file. Full local source datasets and manifests remain in the Balut workspace.\n"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("README.md", readme)
        bundle.write(ROOT / "ml" / "balut_ml" / "predict_public.py", "predict.py")
        bundle.write(ROOT / "ml" / "requirements-public-training.lock.txt", "requirements-training.lock.txt")
        for name, title, source, audit_name, metrics, config, audit, parity in entries:
            run = ROOT / "ml" / "runs" / name
            for filename in ("best.pt", "best.onnx", "config.json", "metrics.json", "onnx-parity.json", "model-card.md", "history.jsonl", "training-command.json"):
                bundle.write(run / filename, f"models/{name}/{filename}")
            for path in (ROOT / "data" / "public" / source / "export").glob("README*"):
                bundle.write(path, f"sources/{source}/{path.name}")
            bundle.write(ROOT / "data" / "public" / source / audit_name / "audit.json", f"sources/{source}/audit.json")
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
    print(json.dumps({"report": str(report), "bundle": str(archive), "bundle_bytes": archive.stat().st_size,
                      "bundle_sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}, indent=2))


if __name__ == "__main__":
    main()
