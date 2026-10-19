"""Build the scientific defense packet from measured, sealed project evidence."""
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import re
import shutil
import sys
from xml.sax.saxutils import escape
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "ml")]
from build_unfertilized_training_report import (read, sha, check_lock, np, plt, PdfReader, colors,
    A4, ParagraphStyle, SimpleDocTemplate, Paragraph, Table, TableStyle, Image, Spacer, PageBreak, pdfmetrics, TTFont)
from balut_ml.scientific_metrics import classification_metrics, cluster_intervals

AUDIT = ROOT / "output/scientific-audit-20261019"
OUT = ROOT / "output/model-results/EggGrade-IoT-Scientific-Defense-20261019"
PDF = ROOT / "output/pdf/EggGrade-IoT-Scientific-Defense-20261019.pdf"
EPOCH = ROOT / "ml/runs/nested-feature-epochs-20261019"
NAMES = ["Day 16", "Day 18", "Reject*"]
INK = "#203b50"


def pretty(text):
    text = text.replace("Day16", "Day 16").replace("Day18", "Day 18")
    return re.sub(r"\b(maximum|patience|rate|decay|batch|smoothing|dropout|fold|epoch|seed|only|uses|provides|gives|divide|within|for|all|All|new|Register|least|than|incubation|slots|receive|counts|count|under|mean|std|revision|reproduced|inactive|trained|has|not|over|size|images|views|weight|historical|remaining|is|our|Our)(?=\d)", r"\1 ", text)


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def pct(value):
    return "not measured" if value is None else f"{value * 100:.2f}%"


def matrix(ax, counts, title, columns):
    counts = np.array(counts)
    ax.imshow(counts, cmap="Blues", vmin=0)
    ax.set(xticks=range(len(columns)), xticklabels=columns, yticks=range(3), yticklabels=NAMES,
           xlabel="Predicted", ylabel="Reference label", title=title)
    for (i, j), count in np.ndenumerate(counts):
        ax.text(j, i, str(count), ha="center", va="center", fontsize=12,
                color="white" if count > counts.max() * .5 else INK)


def figures(metrics, repeat, experiments):
    fig = plt.figure(figsize=(14, 9), layout="constrained")
    grid = fig.add_gridspec(2, 2, height_ratios=[1.15, 1])
    matrix(fig.add_subplot(grid[0, 0]), metrics["raw_confusion_matrix"], "Before recapture gates (649 images)", NAMES)
    matrix(fig.add_subplot(grid[0, 1]), metrics["selective_confusion_matrix"], "After gates; recaptures remain visible", NAMES + ["Recapture"])
    ax = fig.add_subplot(grid[1, 0]); ax.axis("off")
    cells = [[name, str(row["support"]), pct(row["precision"]), pct(row["recall"]), pct(row["f1"])] for name, row in zip(NAMES, metrics["per_class"])]
    cells += [["Macro", "649", pct(metrics["macro_precision"]), pct(metrics["macro_recall"]), pct(metrics["macro_f1"])],
              ["Weighted F1", "649", "", "", pct(metrics["weighted_f1"])]]
    table = ax.table(cellText=cells, colLabels=["Class", "Support", "Precision", "Recall", "F1"], loc="upper center", cellLoc="center")
    table.auto_set_font_size(False); table.set_fontsize(11); table.scale(1, 1.8)
    ax.text(0, .25, "95% cluster-bootstrap raw accuracy interval: 72.40–94.61%\n66 recorded clusters: 10 eggs + 56 public source families.\nHistorical, previously inspected data; not field accuracy.", transform=ax.transAxes, fontsize=11, va="top")
    ax = fig.add_subplot(grid[1, 1]); ax.axis("off")
    lines = [f"Raw accuracy: 550 / 649 = {pct(metrics['raw_accuracy'])}",
             f"Balanced accuracy: {pct(metrics['balanced_accuracy'])}",
             f"Accepted accuracy: 423 / 444 = {pct(metrics['accepted_accuracy'])}",
             f"Coverage: 444 / 649 = {pct(metrics['coverage'])}",
             f"Recapture: 205 / 649 = {pct(metrics['recapture_rate'])}",
             f"Correct accepted / all: 423 / 649 = {pct(metrics['correct_over_all'])}",
             "*Reject = public Unfertilized source label.", "96% independent target: NOT ESTABLISHED"]
    ax.text(.04, 1, "\n".join(lines), va="top", fontsize=13, linespacing=1.8)
    fig.suptitle("EggGrade IoT • Active model results\nunfertilized-trial-20261019 | ONNX 479211e3e587 | data efec2f696feb", fontsize=18)
    fig.savefig(OUT / "active-model-results.png", dpi=180); plt.close(fig)

    logs = [json.loads(line) for line in (EPOCH / "hidden-64/fold-1-inner/history.jsonl").read_text().splitlines()]
    selected = read(EPOCH / "metrics.json")["selected"]
    fig = plt.figure(figsize=(16, 11), layout="constrained"); grid = fig.add_gridspec(3, 5, height_ratios=[1, 1, 1.65])
    keys = [("loss", "Cross-entropy loss"), ("accuracy", "Raw accuracy"), ("precision", "Macro precision"), ("recall", "Macro recall"), ("f1", "Macro F1")]
    for r, phase in enumerate(("train", "validation")):
        for col, (key, label) in enumerate(keys):
            ax = fig.add_subplot(grid[r, col]); ax.plot([x["epoch"] for x in logs], [x[phase][key] for x in logs], color="#2367a1", linewidth=1.5)
            ax.axvline(42, color="#ba6929", linestyle="--", linewidth=1)
            ax.set(title=f"{phase}/{label}", xlabel="Epoch"); ax.grid(alpha=.18)
            if key != "loss": ax.set_ylim(0, 1.04)
    matrix(fig.add_subplot(grid[2, :2]), selected["raw"]["confusion_matrix"], "Five outer folds: 3,070 development images", NAMES)
    ax = fig.add_subplot(grid[2, 2:]); ax.axis("off")
    ax.text(.02, .98, "ACTUAL EPOCH LOGS — EXPERIMENTAL, NOT DEPLOYED\n\n"
            "Frozen DINOv2 + EfficientNet-B0 interior features → 64-unit MLP.\n"
            "Curves: fold 1 inner training/validation only. Best epoch 42; stopped at 50.\n"
            "Max 60 epochs, patience 8. Dashed line: selected inner checkpoint.\n"
            "Outer-fold refit epoch counts: 42, 1, 18, 3, 12.\n\n"
            f"Outer-fold raw accuracy: {pct(selected['raw']['accuracy'])}; macro F1: {pct(selected['raw']['f1'])}.\n"
            "Physical Day 16 recall: 88.33%; Day 18 recall: 92.78%.\n"
            "This candidate did not improve the age target and was not activated.\n"
            "The active logistic model has no epoch learning curves.\n"
            "Reject* means public Unfertilized annotations; not verified field Reject eggs.", va="top", fontsize=12, linespacing=1.5)
    fig.suptitle("EggGrade IoT • Measured learning curves and confusion matrix\nnested-feature-epochs-20261019 / hidden-64 | dataset efec2f696feb", fontsize=19)
    fig.savefig(OUT / "results.png", dpi=180); plt.close(fig)

    examples = read(AUDIT / "misclassified-validation-examples.json")
    fig, axes = plt.subplots(1, 4, figsize=(14, 5), layout="constrained")
    for ax, example in zip(axes, examples):
        scores = example["result"]["sourceClassDecisionScores"]
        predicted = max(scores, key=scores.get)
        ax.imshow(plt.imread(example["image_path"])); ax.axis("off")
        ax.set_title(f"{example['source_label']} → {predicted}\n{example['source_sha256'][:12]} | validation", fontsize=11)
    fig.suptitle("Observed ambiguity: all four pass quality limits; all four request recapture", fontsize=16)
    fig.savefig(OUT / "validation-error-examples.png", dpi=160); plt.close(fig)


def questions(metrics, audit):
    span = list(audit["capture_time_span_hours_by_egg"].values())
    return [
      ("How did you train the model?",
       "We combined our numbered camera eggs with public source-labelled images. We kept each known egg together, extracted frozen transformer and CNN features, and trained a three-class logistic head. The current reproduced historical raw accuracy is 84.75%; new-egg accuracy is not established.",
       "The 3,719-image manifest contains 1,620 physical views of 30 eggs and 2,099 public images. Your 1,590 requested photos are included: 90 three-view photos plus 1,500 rotation photos; 30 earlier views are also retained. R1/R2/R3 are excluded. Train/validation/test contain 2,256/814/649 images. Only 2,256 training rows fit the active head. Three candidate per-egg weights (20, 50, 100) were compared on validation; weight 20 was retained. Class weights balance total effective class weight, and each egg's weight is shared across its views. Logistic regression uses C=100, L-BFGS, maximum 3,000 iterations and seed 42. Pretrained encoders are frozen; original/flipped features are averaged. Validation chooses margins/cosine gates; historical test is used only as a disclosed historical evaluation here.",
       "ml/balut_ml/train_unfertilized.py; retained-unfertilized-serving-20261019/experiment-plan.json, selection-lock.json; classifier-fit-script-verification.json; dataset-audit/audit.json.",
       "Farm ages were user-reported; incubation logs and independent label verification were not supplied. Public labels are annotations. We need new documented eggs and batch identities before claiming independent accuracy."),
      ("Why this train/validation/test split?",
       "The split follows egg and source-family groups, so a different view of the same known egg cannot appear in testing. It is not an assumed 80/10/10 split. Training fits parameters, validation selects settings, and the historical test measures previously held-out groups.",
       "Train: 2,256/3,719=60.66%; validation: 814/3,719=21.89%; historical test: 649/3,719=17.45%. The class counts are Day16 315/286/285, Day18 327/290/290, and Reject-source 1,614/238/74. Each partition has 10 known physical eggs, five per age; each egg has 54 saved views. Your 1,590 newer photos contribute 530 images per partition. Public family counts per class are 45/16/15 for Day16, 57/20/20 for Day18 and 173/69/21 for Reject. No farm batches are known. The newer experiments combine train+validation into 3,070 development images from 20 age eggs and use five grouped folds, holding two eggs per age out per fold. These are development estimates used for comparison, not a new final test.",
       "split-counts.csv; dataset-audit/audit.json; grouped-camera-20261019/folds.json; data/local/retained-camera-epochs-reject-20261019/manifest.jsonl.",
       "The historical test has already been inspected during earlier model development. Its reuse cannot confirm a new candidate independently. Unknown public physical identities and missing batches also prevent farm/batch-generalization claims."),
      ("Where are precision, recall, F1 and other metrics?",
       "They are visible in the active-model PNG, the tables in this report, and the downloadable CSV. The raw matrix includes all 649 images. A second matrix shows the 205 recaptures separately.",
       "Raw accuracy=84.75%, balanced accuracy=88.55%, macro F1=88.50%, weighted F1=84.72%. Day16 precision/recall/F1=79.81/87.37/83.42%; Day18=86.31/78.28/82.10%; public Reject=100/100/100%, from only 74 images in 21 public families. Accepted accuracy=95.27% at 68.41% coverage. Correct accepted over all inputs=65.18%. The raw 95% cluster-bootstrap interval is 72.40–94.61%, based on 5,000 resamples of 10 egg and 56 public-family clusters. It is conditional on these recorded groups and historical sampling, not a field guarantee.",
       "active-model-results.png; classification-metrics.csv; baseline-metrics.json; baseline-reproduction-20261019-v3/outcomes.jsonl and reproduction.json.",
       "No qualifying independent field results are available. Public Reject performance does not validate Reject detection on this camera."),
      ("How did you compute the metrics?",
       "We count actual predictions against reference labels. For each class, true positives are correct predictions of that class, false positives are other classes predicted as it, and false negatives are its missed examples. Recapture is a separate decision, not the Reject class.",
       "For Day16: TP=249, FP=63, FN=36, TN=301. Precision=249/(249+63)=79.81%; recall=249/(249+36)=87.37%; F1=498/(498+63+36)=83.42%. Day18: TP=227, FP=36, FN=63, TN=323. Reject: TP=74, FP=0, FN=0, TN=575. Accuracy=(249+227+74)/649=84.75%. Balanced accuracy=(249/285+227/290+74/74)/3=88.55%. Macro F1=(0.8341708543+0.8209764919+1)/3=88.50%. Weighted F1=(285×0.8341708543+290×0.8209764919+74×1)/649=84.72%. Accepted accuracy=423/444=95.27%; coverage=444/649=68.41%; recapture=205/649=31.59%; correct-over-all=423/649=65.18%. For a zero denominator, class precision/recall/F1 are set to zero and missing class support is flagged; accepted accuracy is undefined when accepted count is zero.",
       "ml/balut_ml/scientific_metrics.py; ml/tests/test_scientific_metrics.py; baseline-metrics.json. Calculations use full-precision counts; percentages are rounded only for display.",
       "These are image-level historical metrics. Future first-attempt three-view field metrics use a separately declared scan unit; image counts must not be presented as independent eggs."),
      ("Were repeated scans exactly consistent?",
       "Identical saved-input inference was exactly repeatable in the tested environment. Fresh physical scan consistency has not been measured under the strict protocol. ZERO-GAP REQUIREMENT NOT MET.",
       "Part A used nine three-file bundles, ten fresh inferences each, and a model reload between repeats 5 and 6: 90 bundle predictions and 270 view inferences. Six bundles represent identified physical age eggs; three represent public Reject families with unknown physical identities. Every bundle had class agreement 100%, decision agreement 100%, maximum pairwise full-score-vector difference 0.0 and zero failed attempts. We compared nine values per bundle: three classes for each of three views, including nonwinning scores. This establishes determinism for identical bytes only. Part B has zero qualifying new physical repeat attempts in this audit; maximum physical score gap is not measured.",
       "identical-input-repeatability/summary.json, case-*/attempts.jsonl, full-precision-scores.npy and evidence-lock.json; scripts/check_saved_repeatability.py; scripts/collect_scientific_field_scan.py.",
       "New independently identified eggs from every class are unavailable, including physical Unfertilized eggs. Future testing uses ten scans per selected egg within 600 seconds, saves all valid raw frames and failed attempts, and treats any nonzero full-precision score difference as failure. Same class with different scores still fails."),
      ("Why confuse Day16 and Day18? What differs?",
       "The current model confused 36 Day16 images as Day18 and 63 Day18 images as Day16. Both ages can look similar under candling. The age labels and camera conditions also have limitations, so we cannot assign one proven cause.",
       f"Inspected validation examples 16-10 view45 and 18-10 view46 both show a large dark interior and bright lower illumination. Their raw winning margins are 0.53046 and 0.03798; both trigger ambiguity recapture. Edge variance is 146.53/177.77 and clipped fraction is 27.75/21.09%, within configured limits. The two public errors also pass quality checks; one has visible shell writing, a possible source cue. No intervention proves that glare, writing or shell differences caused these specific mistakes. Recorded sessions for the same egg span {min(span):.2f}–{max(span):.2f} hours, while exact incubation hours are unverified. Biologically, embryos continue growing and developing between these ages; candling sees transmitted-light appearance rather than a direct clock. Trela et al. (2025) document developmental timing differences between Pekin and Mulard ducks. Metzer Farms' primary candling chart illustrates progressive filling of the egg. Neither establishes a universal Day16/Day18 brightness cutoff for our eggs.",
       "validation-error-examples.png; misclassified-validation-examples.json; https://doi.org/10.1016/j.psj.2025.105132 ; https://www.metzerfarms.com/candling-pictures.html .",
       "Shell thickness, orientation, lighting and developmental variation are plausible contributors, not isolated causal findings here. Confirm age from incubation records and compare controlled images across independent eggs/batches. An image alone does not prove exact age or food safety."),
      ("Which epoch did you stop at, and why?",
       "The active model is a frozen-feature logistic classifier, so it has solver iterations rather than epochs. A new CPU reproduction converged in 38 iterations. The separately labelled experimental MLP has real epoch logs, but it was not deployed.",
       "Active L-BFGS limit=3,000 iterations; the reproduced fit took 38 and exactly matched the stored float32 coefficient/intercept arrays. The original fit did not save its iteration count, so 38 is explicitly a reproduction measurement. Experimental hidden-64 MLP: maximum60, patience8, AdamW learning rate0.001, weight decay0.01, batch256, label smoothing0.03, dropout0.2. Inner stopping ranks weaker physical-age recall, mean age recall, public macro F1, then lower loss. Selected epochs by outer fold=42/1/18/3/12; completed inner epochs=50/9/26/11/20. Each outer refit trains exactly the selected epoch count using its four training folds. The outer held fold never chooses stopping. Fold1's best checkpoint is42; the final inner epoch50 follows eight epochs without improvement. This MLP had only88.33/92.78% physical-age recalls and remained inactive.",
       "classifier-fit-script-verification.json; nested-feature-epochs-20261019/experiment-plan.json, hidden-64/fold-*/summary.json and history.jsonl; results.png.",
       "There are no active-model epoch curves to show. GPU image-fine-tuning runs were interrupted by two automatic PC restarts and are not complete cross-validation evidence. The restart cause remains unconfirmed; further GPU runs were avoided."),
      ("Was there data leakage?",
       "No cross-partition leakage was detected by the checks we could run. That is not proof that every kind of leakage is absent. Missing public egg identities, missing batches and prior test inspection remain explicit limitations.",
       "All3,719 files match their recorded hashes; zero cross-partition file-hash, decoded-pixel, recorded source-family, original-source-image or known-egg overlaps. Thirty known eggs stay in one partition across all sessions. The near-duplicate check found zero cross-partition candidates requiring both64-bit dHash distance≤3 and32×32 RGB mean absolute difference≤6/255. Grouped development folds show zero recorded group crossings. Split assignment precedes learned augmentation; deterministic original/flip inference stays within each image. New MLP centering/scaling and photometry standardization fit only training folds. Public identities are unknown for2,099 images; batch IDs are missing for all3,719. Reject comes entirely from one public source family of datasets while camera data contains only age eggs: source/class confounding remains possible. The historical test has been reused and cannot be called a fresh confirmation holdout.",
       "dataset-audit/audit.json; near-duplicate-candidates.json; scripts/audit_scientific_dataset.py; train_nested_feature_epochs.py; search_camera_photometry.py.",
       "No confirmed overlap required deleting data. Perceptual checks can miss visually changed duplicates; unknown same-egg identities across public files or ages cannot be ruled out. Future studies require verified persistent egg IDs and batches before splitting, and one untouched final evaluation cycle."),
      ("Which CNN architecture did you use?",
       "It is a hybrid: EfficientNet-B0 is the CNN, DINOv2 ViT-S/14 is the transformer, and a logistic head predicts the three source-label classes. Calling the entire system a CNN would be incomplete.",
       "EfficientNet-B0 provides1,280 features with ImageNet1K_V1 pretrained weights; DINOv2 ViT-S/14 provides384 features (repository revision7764ea0f912e53c92e82eb78a2a1631e92725fc8). Features from original and horizontally flipped images are averaged per encoder and L2-normalized. Concatenation divided by sqrt(2) gives1,664 features, followed by three linear decision scores. Encoders remain frozen in the active model. JPEG preprocessing: EXIF transpose, RGB,224×224 bilinear resize, divide255, ImageNet mean[.485,.456,.406]/std[.229,.224,.225], float32 NCHW. CPU ONNX uses4 intra-op/1 inter-op threads. Scores are not calibrated probabilities. App Reject maps to internal UNFERTILIZED; recapture remains separate. Three-view consensus requires at least two distinct accepted view hashes and agreement among accepted labels.",
       "ml/balut_ml/feature_models.py; deployment/releases/unfertilized-trial-20261019/egg-grade/config.json; model_service.py (view_consensus and combine_views); runtime-status.json, final-runtime-verification.json and model-identity.json.",
       "A new representation candidate has not completed full runtime export verification or deployment. The current app/model hashes are reported separately from all experimental checkpoints."),
      ("What is the field-testing accuracy?",
       "FIELD ACCURACY NOT YET ESTABLISHED. Our84.75% result is a historical image test. Earlier checks of the same collection eggs do not satisfy the new independent field protocol.",
       "This audit collected zero new physical field eggs and zero qualifying fresh repeat scans. A planned study has90 new eggs,30 per class, from at least three batches per class. Its first three-view attempt per egg is the primary unit. Three preregistered eggs per class receive ten attempts within600 seconds, for171 planned attempts total; repeated attempts are not171 independent eggs. Primary raw scan classification is argmax of the mean of the three unrounded decision-score vectors; app consensus/recapture is reported separately. First-attempt capture failures remain unsuccessful in the90-egg denominator. Report per-class P/R/F1, raw accuracy, accepted accuracy, coverage, recaptures and failures, with batch-cluster uncertainty and unique-egg counts. Required target: raw and every class recall≥96%, coverage≥68.41%, correct-over-all≥65.18%, with no baseline regression on paired evidence.",
       "field-protocol.txt; field-registration.csv; field-conditions.json; scripts/collect_scientific_field_scan.py and its tests. The blank workbook is a planned collection sheet, not completed observations.",
       "The user has no new verified Day16/Day18 eggs and no physical Unfertilized eggs. Both USB adapters enumerate, but the cloud connector was offline at runtime inspection. The collector reuses the existing stop/capture/resume three-view functions; it is tested with mocks only. Physical execution and a new independent accuracy claim remain pending.")]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    baseline = read(AUDIT / "dataset-audit/baseline-metrics.json"); metrics = baseline["metrics"]
    baseline_records = [json.loads(line) for line in (ROOT / "ml/runs/baseline-reproduction-20261019-v3/outcomes.jsonl").read_text().splitlines()]
    classes = ["DAY_16", "DAY_18", "UNFERTILIZED"]
    baseline["uncertainty"] = cluster_intervals(baseline_records, classes)
    write(OUT / "baseline-metrics.json", baseline)
    audit = read(AUDIT / "dataset-audit/audit.json"); repeat = read(AUDIT / "identical-input-repeatability/summary.json")
    assert classification_metrics(metrics["raw_confusion_matrix"], metrics["selective_confusion_matrix"]) == metrics
    assert sum(audit["source_class_counts"].get(f"{source}:{c}", 0) for source in ("physical-multiangle-20261019", "physical-50views-20261019") for c in ("DAY_16", "DAY_18")) == 1590
    check_lock(ROOT / "ml/runs/baseline-reproduction-20261019-v3", "evaluation-lock.json")
    runs = [("Grouped linear", "grouped-camera-20261019", 18, "The current linear boundary may underfit age appearances."),
            ("RBF full frame", "grouped-kernel-20261019", 6, "A nonlinear head may separate overlapping frozen features."),
            ("Interior representation", "representation-search-20261019", 72, "Removing enclosure background may improve age separation."),
            ("Nested stacking", "nested-camera-stack-20261019", 3, "Complementary frozen heads may reduce individual errors."),
            ("Age hierarchy", "camera-hierarchy-20261019", 108, "Separating age inference from Reject inference may help."),
            ("CPU MLP epochs", "nested-feature-epochs-20261019", 2, "A regularized epoch-trained head may improve separation."),
            ("Interior photometry", "camera-photometry-20261019", 27, "Interior color and dark-area features may add useful information.")]
    experiments = []
    dev_rows = [json.loads(line) for line in (ROOT / "data/local/retained-camera-epochs-reject-20261019/manifest.jsonl").read_text().splitlines() if json.loads(line)["partition"] != "test"]
    for name, run, count, hypothesis in runs:
        folder = ROOT / "ml/runs" / run; check_lock(folder, "selection-lock.json")
        result = read(folder / "metrics.json")["selected"]
        oof_path = folder / ("hidden-64/oof.npz" if run == "nested-feature-epochs-20261019" else "selected-oof.npz")
        with np.load(oof_path, allow_pickle=False) as bank:
            scores = bank["scores"]; truth = bank["truth"]
        assert len(scores) == len(dev_rows)
        np.testing.assert_array_equal(truth, [classes.index(row["source_label"]) for row in dev_rows])
        predicted = scores.argmax(1)
        assert np.mean(predicted == truth) == result["raw"]["accuracy"]
        records = [{"truth": classes[int(y)], "raw_prediction": classes[int(z)], "sourcePrediction": classes[int(z)],
                    "physical_egg_id": row.get("physical_egg_id"), "duplicate_group": row["duplicate_group"]}
                   for row, y, z in zip(dev_rows, truth, predicted, strict=True)]
        uncertainty = cluster_intervals(records, classes)
        uncertainty["intervals"] = {key: value for key, value in uncertainty["intervals"].items()
                                    if key in ("raw_accuracy", "balanced_accuracy", "macro_f1", "weighted_f1")}
        uncertainty["limitations"] += " Development model selection makes these descriptive intervals optimistic; not independent confirmation. Gates were not evaluated by this raw-score interval calculation."
        experiments.append({"name": name, "run": run, "configurations": count, "hypothesis": hypothesis,
                            "scope": "GROUPED_DEVELOPMENT_NOT_INDEPENDENT_TEST", "raw_accuracy": result["raw"]["accuracy"],
                            "macro_f1": result["raw"]["f1"], "camera_age_recall": result["camera_age_recall"],
                            "selected_configuration": result.get("spec", {k: result[k] for k in ("hidden", "meta_C") if k in result}),
                            "selection_lock_sha256": sha(folder / "selection-lock.json"), "uncertainty": uncertainty, "promoted": False})
    assert sum(e["configurations"] for e in experiments) == 236
    write(OUT / "experiment-ledger.json", experiments)
    for source, dest in [(AUDIT / "runtime-status.json", "runtime-status.json"),
                         (AUDIT / "classifier-fit-script-verification.json", "classifier-fit-reproduction.json"),
                         (AUDIT / "dataset-audit/audit.json", "leakage-audit.json"),
                         (AUDIT / "identical-input-repeatability/summary.json", "repeatability-results.json"),
                         (AUDIT / "misclassified-validation-examples.json", "misclassified-validation-examples.json"),
                         (AUDIT / "protocol.json", "audit-protocol.json")]: shutil.copyfile(source, OUT / dest)
    with (OUT / "classification-metrics.csv").open("w", newline="", encoding="utf-8") as stream:
        ci_fields = [key + suffix for key in ("precision", "recall", "f1") for suffix in ("_ci95_lower", "_ci95_upper")]
        writer = csv.DictWriter(stream, fieldnames=["class", *metrics["per_class"][0].keys(), *ci_fields]); writer.writeheader()
        for name, row, ci in zip(NAMES, metrics["per_class"], baseline["uncertainty"]["per_class_intervals"]):
            writer.writerow({"class": name, **row, **{key + "_ci95_" + bound: ci[key][bound] for key in ("precision", "recall", "f1") for bound in ("lower", "upper")}})
    with (OUT / "split-counts.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(audit["splits"][0])); writer.writeheader(); writer.writerows(audit["splits"])
    registration_fields = ["slot", "reference_class", "repeats", "egg_id", "batch_id", "unseen_egg", "independent_reference", "assessor", "incubation_start_utc", "reference_method", "reference_file", "notes"]
    slots = [{**dict.fromkeys(registration_fields, ""), "slot": f"{prefix}-{i:02d}", "reference_class": label, "repeats": 10 if i in (1, 11, 21) else 1}
             for prefix, label in (("D16", "DAY_16"), ("D18", "DAY_18"), ("UF", "UNFERTILIZED")) for i in range(1, 31)]
    random.Random(42).shuffle(slots)
    with (OUT / "field-registration.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=registration_fields); writer.writeheader(); writer.writerows(slots)
    write(OUT / "field-conditions.json", {"registry_sha256": read(AUDIT / "runtime-status.json")["catalog"]["registrySha256"],
          **dict.fromkeys(("lighting", "position", "ambient_conditions", "operator", "camera_settings_policy"), "FILL BEFORE CAPTURE")})
    identity = {"release": read(AUDIT / "runtime-status.json")["catalog"],
                "data_manifest_sha256": "efec2f696feb38f5204f5a9f8b3550ec88fc5793ea4cdad40c19aa703aa999ba",
                "active_original_manifest_sha256": "01478d1619524c383539bf0d7bd3b730be5c5d82aa9f01a51db19e1018300885",
                "class_display_mapping": {"DAY_16": "Day 16", "DAY_18": "Day 18", "UNFERTILIZED": "Reject"},
                "epoch_experiment": str(EPOCH.relative_to(ROOT)), "field_evaluation_performed": False}
    write(OUT / "model-identity.json", identity)
    figures(metrics, repeat, experiments)
    qa = [[pretty(value) for value in row] for row in questions(metrics, audit)]
    ci = baseline["uncertainty"]["per_class_intervals"]
    qa[2][2] += f" Class recall 95% cluster intervals: Day 16 {pct(ci[0]['recall']['lower'])}–{pct(ci[0]['recall']['upper'])}; Day 18 {pct(ci[1]['recall']['lower'])}–{pct(ci[1]['recall']['upper'])}. Full precision/recall/F1 intervals are in the CSV."
    qa[3][2] += " In one-vs-rest terms, TN means other reference classes predicted as other classes. General formulas: precision=TP/(TP+FP); recall=TP/(TP+FN); F1=2TP/(2TP+FP+FN); raw accuracy=correct/evaluated; balanced accuracy=mean class recall; macro F1=mean class F1; weighted F1=sum(support×F1)/total support."
    (OUT / "defense-answers.txt").write_text("EggGrade IoT - technical defense answers\n2026-10-19\n\n" + "\n\n".join(
        f"Q{i}. {q}\nA. Spoken answer\n{a}\nB. Technical detail\n{b}\nC. Evidence (paths relative to project or packet)\n{c}\nD. Missing evidence / next work\n{d}"
        for i, (q, a, b, c, d) in enumerate(qa, 1)), encoding="utf-8")
    write(OUT / "defense-answers.json", qa)

    pdfmetrics.registerFont(TTFont("AuditArial", "C:/Windows/Fonts/arial.ttf"))
    body = ParagraphStyle("Body", fontName="AuditArial", fontSize=9.2, leading=12.2, textColor=colors.HexColor(INK), spaceAfter=7)
    title = ParagraphStyle("Title", parent=body, fontSize=21, leading=25, spaceAfter=14)
    heading = ParagraphStyle("Heading", parent=body, fontSize=12.5, leading=16, spaceBefore=9, spaceAfter=8)
    small = ParagraphStyle("Small", parent=body, fontSize=7.8, leading=10)
    story = []
    def p(text, style=body): story.append(Paragraph(escape(pretty(text)).replace("\n", "<br/>"), style))
    def table(rows, widths):
        data = [[Paragraph(escape(str(v)), small) for v in row] for row in rows]
        value = Table(data, colWidths=widths, repeatRows=1)
        value.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5edf3")),
                                  ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 6),
                                  ("BOTTOMPADDING", (0, 0), (-1, -1), 6), ("LINEBELOW", (0, 0), (-1, 0), .6, colors.HexColor(INK)),
                                  ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f7f9")])]))
        story.append(value); story.append(Spacer(1, 10))
    p("EggGrade IoT", title); p("Scientific audit and technical defense | 19 October 2026", heading)
    p("96% independent accuracy: NOT ESTABLISHED.\nZERO-GAP REQUIREMENT NOT MET.\nFIELD ACCURACY NOT YET ESTABLISHED.", heading)
    p("The active release was reproduced without changing its weights, gates, or capture workflow. The user's 1,590 requested photos are included. They represent 30 eggs. No candidate satisfied the full accuracy and operational comparison requirements, so the working app release was preserved.")
    table([["Measured result", "Value", "Scope"], ["Active raw accuracy", "550 / 649 = 84.75%", "Previously inspected historical images"],
           ["95% interval", "72.40–94.61%", "66 recorded egg/source-family clusters"], ["Accepted accuracy / coverage", "95.27% / 68.41%", "423 correct out of 444 accepted"],
           ["Correct accepted / all", "423 / 649 = 65.18%", "All 205 recaptures retained"], ["Best overall development candidate", "96.87% overall; ages 95.19% / 94.63%", "Interior RBF; used for selection, not independent"],
           ["Identical-file repeats", "9 cases × 10 repeats; score gap 0.0", "Fresh inference on unchanged saved bytes only"]], [160, 155, 196])
    p("What improved", heading)
    p("The evidence now includes a reproduced baseline, an exact classifier-fit reproduction, complete metric computations, grouped confidence intervals, a leakage audit, full-score repeatability logs, actual epoch plots, and a tested field-collection script. Across 236 bounded development configurations, useful changes were evaluated without activating an unsupported model.")
    p("Immediate limitation", heading)
    p("Available photos can support further development and historical comparison. They cannot supply unseen physical eggs, independent incubation records, physical Reject examples or a fresh final holdout. GPU fine-tuning was interrupted by automatic PC restarts; the cause is unknown. Subsequent completed work used CPU inference or cached-feature training.")
    p("Active release: unfertilized-trial-20261019. Runtime checked 2026-10-19 04:09:36 UTC. Web/mobile display Reject for the internal public-source UNFERTILIZED class. These labels do not establish food safety or sellability.", small)
    story.append(PageBreak())
    p("Current model: measured results", title)
    story.append(Image(str(OUT / "active-model-results.png"), width=511, height=329))
    table([["Metric", "Observed", "95% cluster-bootstrap interval"]] + [[key.replace("_", " "), pct(metrics[key]),
           f"{pct(bounds['lower'])}–{pct(bounds['upper'])}"] for key, bounds in baseline["uncertainty"]["intervals"].items()], [230, 100, 181])
    p("Rows are reference labels; columns are predictions. Reject* is the source Unfertilized class. Recapture is an abstention. The bootstrap resamples whole recorded eggs/families (seed42, 5,000 draws); unknown public egg/batch relationships and prior test reuse remain limitations.", small)
    story.append(PageBreak())
    p("Development comparisons", title)
    table([["Experiment", "Configs", "Raw overall", "Raw 95% interval", "Day16 recall", "Day18 recall"]] + [[e["name"], e["configurations"], pct(e["raw_accuracy"]), f"{pct(e['uncertainty']['intervals']['raw_accuracy']['lower'])}–{pct(e['uncertainty']['intervals']['raw_accuracy']['upper'])}", *map(pct, e["camera_age_recall"])] for e in experiments], [127, 42, 76, 110, 78, 78])
    p("Candidate intervals resample whole recorded development eggs/source families. They describe the selected development predictions; they do not correct for model-selection bias or establish independent performance.", small)
    p("Same development population: 3,070 images, 20 physical age eggs, five grouped folds. Overall scores include 1,852 public Reject images; age recalls above use 540 physical views per age. Model selection uses these development results. It is therefore incorrect to present the 96%+ overall figures as independent field accuracy.")
    p("The retained linear configuration (fused, C100, per-egg weight20) has grouped physical-age recalls88.33% /95.00%. The interior RBF candidate improves these to95.19% /94.63%, trading away some Day18 recall. The hierarchy gives95.74% /95.00% on physical ages but only96.03% overall and lower public-age performance. None reaches96% for both physical ages.")
    p("A previous full-frame RBF candidate was also evaluated on the historical649 images: raw572/649=88.14%, but only315/649=48.54% coverage, with334 recaptures. Its100% accepted accuracy did not justify promotion. Comparing it against the active84.75% raw and68.41% coverage demonstrates why accepted accuracy alone is insufficient.")
    p("Each experiment's hypothesis, selected configuration and selection-lock hash appear in experiment-ledger.json. Raw configurations, seeds, folds and outcomes remain in the corresponding ml/runs folders. The latest photometry experiment completed with95.00% /94.81% age recalls and was not deployed.")
    p("Split and source counts", heading)
    table([["Partition", "Images (% total)", "Day16 / Day18 / Reject", "Physical eggs"], ["Training", "2,256 (60.66%)", "315 / 327 / 1,614", "10"], ["Validation", "814 (21.89%)", "286 / 290 / 238", "10"], ["Historical test", "649 (17.45%)", "285 / 290 / 74", "10"]], [110, 140, 181, 80])
    p("Full per-class partition percentages, physical egg counts and public-family counts are in split-counts.csv. All batch identities are missing. The 1,590 photos contribute530 images per partition; the30 earlier views add10 per partition. Known physical identities remain grouped across capture sessions.", small)
    story.append(PageBreak())
    p("Actual epoch curves", title)
    story.append(Image(str(OUT / "results.png"), width=511, height=351.3))
    p("These curves belong only to the inactive64-unit MLP experiment. They show measured fold1 inner training/validation values, not the current app's learning history. The confusion matrix covers the five outer development folds. No YOLO box losses or mAP metrics apply to this image classifier.")
    table([["Outer fold", "Selected inner epoch", "Completed inner epochs", "Outer refit epochs"]] + [[i, best, completed, best] for i, best, completed in zip(range(1, 6), [42, 1, 18, 3, 12], [50, 9, 26, 11, 20])], [100, 140, 140, 131])
    p("Both frozen encoders remain unchanged. The MLP fits its input mean/scale only inside the training fold. Inner validation chooses the stopping epoch; the outer held fold is evaluated after refitting. The active logistic fit separately reproduced38 L-BFGS iterations and exactly matched stored float32 parameters.")
    for start in range(0, 10, 2):
        story.append(PageBreak())
        p(f"Defense answers {start+1}–{start+2}", title)
        for i in range(start, start + 2):
            q, a, b, c, d = qa[i]
            p(f"Q{i+1}. {q}", heading)
            for label, text in (("A. Say", a), ("B. Detail", b), ("C. Evidence", c), ("D. Missing / next", d)):
                p(label + ": " + text, small if label.startswith("C") else body)
    story.append(PageBreak()); p("Inspected validation errors", title)
    story.append(Image(str(OUT / "validation-error-examples.png"), width=511, height=182.5))
    p("Observed: similar broad dark regions and bright lower illumination in both physical ages; enclosure lighting differs; one public example has shell writing. All four examples pass the configured quality gates yet are ambiguous under the age classifier. These are observations, not proof of a causal mechanism.")
    p("Testable hypotheses: control stray light, stabilize exposure and framing, and compare markings-free images on independently labelled eggs. The existing crop/photometry experiments test parts of this idea but still fail the per-age target. Do not relabel a difficult egg to match the prediction.")
    p("Biological references", heading)
    p("Trela M. et al. (2025). Developmental stages of the Pekin duck (Anas platyrhynchos f. domestica) and the Mulard duck in artificial incubation. Poultry Science104(8):105132. https://doi.org/10.1016/j.psj.2025.105132 . This primary study documents breed-dependent development; its measurements are not a calibration of this device or this egg cohort.")
    p("Metzer Farms. Candling Duck Eggs, day-by-day original photographs. https://www.metzerfarms.com/candling-pictures.html . This is a hatchery observation source, not a model-validation experiment. It supports careful lighting and progressive development, not exact-age or food-safety inference.")
    p("Hashes and runtime identity", heading)
    for key, value in [("Registry", identity["release"]["registrySha256"]), ("ONNX", identity["release"]["models"][0]["modelSha256"]), ("Camera head", identity["release"]["models"][0]["cameraHeadSha256"]), ("Audit dataset", identity["data_manifest_sha256"])]: p(key + ": " + value, small)
    p("Full thresholds, input/aggregation contracts and source hashes are preserved in the release and packet evidence. The app retains its current three-view pause/capture/resume workflow. Timed motor steps are not encoder-verified angular measurements.", small)
    story.append(PageBreak()); p("Field protocol and reproducibility", title)
    p("Prepared for future collection; no fabricated field observations", heading)
    p("Register90 genuinely new eggs (30/class) from at least3 batches/class before viewing predictions. Freeze persistent IDs, independent references, assessor, batch and age records. Day16 is elapsed384–<408 hours; Day18 is432–<456 hours for this planned protocol. Reject means independently confirmed Unfertilized under a declared reference method, not a vendor's general rejection label. Assign repeated slots01/11/21 of each class to different batches.")
    p("Use the supplied randomized registration order (seed42). First attempt per egg is primary. Three selected eggs/class receive10 full three-view scans each within600 seconds. Keep the egg seated, hands clear, candling light on, documented ambient light and camera settings. Preserve current rotation between views and pause during capture. Record actual exposure status on each attempt; do not tune settings after seeing outcomes. Any protocol deviation remains recorded. Compare all nine unrounded view scores, final class and accept/recapture; any nonzero difference fails strict repeatability.")
    p("Fill the CSV/workbook and field-conditions.json. Run validation-only before opening hardware. During collection close any other process holding these USB ports. The collector uses existing capture/preprocessing/inference functions, saves all CRC-valid sensor frames including warmup/discarded reads, inputs, timestamps, motor steps, exposure response and full results. Invalid transport bytes are rejected by the existing CRC reader and logged as errors rather than accepted inputs. It does not alter the deployed release.")
    p("Runnable command from project root:", heading)
    p(".venv-serving/Scripts/python.exe scripts/collect_scientific_field_scan.py --registration <completed.csv> --conditions <completed.json> --slot <registered-slot> --output <new-study-folder> --validate-only", small)
    p("Remove --validate-only only when the registered egg is physically in place. One folder per preregistered egg prevents replacement of failed attempts. Registration, references, model and workflow hashes lock on the first capture. Report all90 first attempts, including missing/capture-failed attempts. For uncertainty resample whole batches, retaining whole eggs, and disclose the small number of batches. At30 eggs/class, one error gives96.67% and two93.33%; confidence intervals remain wide even if the point target passes.")
    p("Reproduce measured evidence", heading)
    p("1. Run scripts/reproduce_retained_classifier_fit.py with .venv-ml and --output <new.json>.\n2. Run scripts/reproduce_scientific_baseline.py with .venv-serving and --output <new-folder>.\n3. Review audit/repeatability scripts and saved protocols; their fixed output paths protect completed evidence. Use a new dated output location for a new run.\n4. Run the focused tests listed in reproducibility.txt.\n5. Build this report with scripts/build_scientific_defense.py using the bundled document Python.\n6. Do not rerun the GPU image-fine-tuner until the automatic-restart problem is diagnosed.")
    p("The packet contains summaries, original measured curves, collection templates and source references. Raw camera datasets, credentials and model weights are intentionally not duplicated into the shareable ZIP. The project retains the complete local evidence.", small)
    def footer(canvas, doc):
        canvas.setFont("AuditArial", 8); canvas.setFillColor(colors.HexColor("#667887"))
        canvas.drawString(42, 24, "EggGrade IoT | Scientific audit | 2026-10-19")
        canvas.drawRightString(A4[0] - 42, 24, f"Page {doc.page}")
    SimpleDocTemplate(str(PDF), pagesize=A4, leftMargin=42, rightMargin=42, topMargin=40, bottomMargin=42).build(story, onFirstPage=footer, onLaterPages=footer)
    extracted = "\n".join(page.extract_text() for page in PdfReader(PDF).pages)
    for required in ("84.75%", "95.27%", "ZERO-GAP REQUIREMENT NOT MET", "FIELD ACCURACY NOT YET ESTABLISHED", "Q10."):
        assert required in extracted
    write(OUT / "report-verification.json", {"pages": len(PdfReader(PDF).pages), "required_text_present": True, "pdf_sha256": sha(PDF), "visual_review": "PENDING"})
    for source, target in [(ROOT / "docs/scientific-field-protocol.txt", "field-protocol.txt"),
                           (ROOT / "docs/scientific-reproducibility.txt", "reproducibility.txt"),
                           (ROOT / "deployment/releases/unfertilized-trial-20261019/egg-grade/gate-policy.json", "active-gate-policy.json"),
                           (ROOT / "deployment/releases/unfertilized-trial-20261019/egg-grade/config.json", "active-model-config.json")]:
        shutil.copyfile(source, OUT / target)
    print(json.dumps({"pdf": str(PDF), "pages": len(PdfReader(PDF).pages), "output": str(OUT)}))


if __name__ == "__main__":
    main()
