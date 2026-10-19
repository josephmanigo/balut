"""Build the plain-language defense guide from a public aggregate evidence snapshot.

Use --refresh-evidence only after regenerating the local scientific packet.
No photos, identities, credentials, predictions, or model weights are published.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tmp/pdfdeps"))
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / "tmp/pdfs/matplotlib"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

PUBLIC = ROOT / "docs/reports/20261019"
PACKET = ROOT / "output/model-results/EggGrade-IoT-Scientific-Defense-20261019"
SNAPSHOT = PUBLIC / "model-evidence.json"
PDF = ROOT / "output/pdf/EggGrade-IoT-Defense-Guide.pdf"
NAMES = ["Day 16", "Day 18", "Reject*"]
INK, BLUE, PALE = "#19364a", "#126c94", "#eef5f8"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pct(value):
    return f"{value * 100:.2f}%"


def refresh():
    baseline = read(PACKET / "baseline-metrics.json")
    runtime = read(PACKET / "final-runtime-verification.json")
    assert runtime["live_matches_local"] is True
    epoch = ROOT / "ml/runs/nested-feature-epochs-20261019"
    sources = {
        "baseline": PACKET / "baseline-metrics.json",
        "historical_candidate": ROOT / "ml/runs/grouped-camera-historical-20261019/metrics.json",
        "experiment_ledger": PACKET / "experiment-ledger.json",
        "epoch_metrics": epoch / "metrics.json",
        "epoch_history": epoch / "hidden-64/fold-1-inner/history.jsonl",
        "epoch_summary": epoch / "hidden-64/fold-1-inner/summary.json",
        "repeatability": PACKET / "repeatability-results.json",
        "leakage": PACKET / "leakage-audit.json",
    }
    experiments = [{key: row[key] for key in ("name", "run", "configurations", "raw_accuracy", "camera_age_recall", "promoted")}
                   for row in read(sources["experiment_ledger"])]
    history = [{"epoch": row["epoch"], **{phase: {key: row[phase][key] for key in ("loss", "accuracy", "precision", "recall", "f1")}
               for phase in ("train", "validation")}} for row in
               (json.loads(line) for line in sources["epoch_history"].read_text().splitlines())]
    summary = read(sources["epoch_summary"])
    evidence = {
        "scope": "HISTORICAL_IMAGE_EVALUATION_AND_SELECTED_DEVELOPMENT_RESULTS_NOT_FIELD_ACCURACY",
        "date": "2026-10-19", "runtime_verified_at": runtime["live_status"]["verified_at"],
        "active_catalog": runtime["live_catalog"],
        "manifest_sha256": read(PACKET / "model-identity.json")["data_manifest_sha256"],
        "baseline": baseline["metrics"], "uncertainty": baseline["uncertainty"],
        "historical_candidate": read(sources["historical_candidate"])["overall"],
        "experiments": experiments,
        "epoch": {"run": "nested-feature-epochs-20261019", "hidden_units": 64, "history": history,
                  "selected_epoch": summary["selected_epoch"], "epochs_completed": summary["epochs_completed"],
                  "outer_metrics": read(sources["epoch_metrics"])["selected"]["raw"]},
        "source_hashes": {name: {"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path)} for name, path in sources.items()},
        "decision": "KEEP_CURRENT_MODEL", "reason": "No candidate passes the complete accuracy, per-age and coverage requirements.",
        "physical_field_accuracy": None, "fresh_physical_score_gap": None,
        "saved_input_repeatability": {"bundles": 9, "repeats_per_bundle": 10, "views_per_bundle": 3, "maximum_score_gap": 0.0},
    }
    PUBLIC.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def verify(e):
    """Reject inconsistent counts or accidental mixing of experimental/live results."""
    m, c = e["baseline"], e["historical_candidate"]
    raw, gated = np.array(m["raw_confusion_matrix"]), np.array(m["selective_confusion_matrix"])
    assert raw.sum() == gated.sum() == m["evaluated"] == 649
    assert raw.trace() == m["raw_correct"] == 550
    assert gated[:, :3].trace() == m["correct_accepted"] == 423
    assert gated[:, :3].sum() == m["accepted"] == 444
    assert gated[:, 3].sum() == m["recaptures"] == 205
    np.testing.assert_allclose(
        [m[key] for key in ("raw_accuracy", "balanced_accuracy", "macro_f1", "weighted_f1", "accepted_accuracy", "coverage", "recapture_rate", "correct_over_all")],
        [550 / 649, np.mean([row["recall"] for row in m["per_class"]]), np.mean([row["f1"] for row in m["per_class"]]),
         sum(row["support"] * row["f1"] for row in m["per_class"]) / 649, 423 / 444, 444 / 649, 205 / 649, 423 / 649],
        rtol=0, atol=1e-15)
    for i, row in enumerate(m["per_class"]):
        tp, fp, fn = raw[i, i], raw[:, i].sum() - raw[i, i], raw[i].sum() - raw[i, i]
        assert row["TP"] == tp and row["FP"] == fp and row["FN"] == fn
        np.testing.assert_allclose([row["precision"], row["recall"], row["f1"]],
                                   [tp / (tp + fp), tp / (tp + fn), 2 * tp / (2 * tp + fp + fn)], rtol=0, atol=1e-15)
    assert c["raw_accuracy"] > m["raw_accuracy"] and c["correct_over_all"] < m["correct_over_all"]
    assert sum(row["configurations"] for row in e["experiments"]) == 236
    assert all(not row["promoted"] for row in e["experiments"])
    assert e["decision"] == "KEEP_CURRENT_MODEL"
    assert e["active_catalog"]["releaseId"] == "unfertilized-trial-20261019"
    assert e["physical_field_accuracy"] is None and e["fresh_physical_score_gap"] is None
    assert e["epoch"]["selected_epoch"] == 42 and e["epoch"]["epochs_completed"] == 50
    assert [row["epoch"] for row in e["epoch"]["history"]] == list(range(1, 51))


def draw_matrix(ax, data, title, columns):
    data = np.array(data)
    ax.imshow(data, cmap="Blues", vmin=0)
    ax.set(xticks=range(len(columns)), xticklabels=columns, yticks=range(3), yticklabels=NAMES,
           xlabel="Predicted class", ylabel="Reference class", title=title)
    for (row, col), value in np.ndenumerate(data):
        ax.text(col, row, str(value), ha="center", va="center", fontsize=18,
                color="white" if value > data.max() / 2 else INK)


def figures(e):
    plt.rcParams.update({"font.size": 12, "axes.titleweight": "bold"})
    for key, title, columns in (("raw_confusion_matrix", "Before recapture gates", NAMES),
                               ("selective_confusion_matrix", "After gates: recaptures included", NAMES + ["Recapture"])):
        fig, ax = plt.subplots(figsize=(8, 3.7), layout="constrained")
        draw_matrix(ax, e["baseline"][key], title, columns)
        fig.savefig(PUBLIC / (key + ".png"), dpi=200); plt.close(fig)
    history = e["epoch"]["history"]
    fig, axes = plt.subplots(2, 5, figsize=(16, 7), layout="constrained")
    for r, phase in enumerate(("train", "validation")):
        for col, (key, name) in enumerate((("loss", "Loss"), ("accuracy", "Accuracy"), ("precision", "Precision"), ("recall", "Recall"), ("f1", "F1"))):
            ax = axes[r, col]
            ax.plot([x["epoch"] for x in history], [x[phase][key] for x in history], color=BLUE)
            ax.axvline(42, color="#b26a21", linestyle="--")
            ax.set(title=f"{phase}/{name}", xlabel="Epoch"); ax.grid(alpha=.2)
            if key != "loss": ax.set_ylim(0, 1.04)
    fig.suptitle("Measured epoch experiment: NOT the web model\n64-unit MLP, fold 1 inner split; dashed line = selected epoch 42", fontsize=18)
    fig.savefig(PUBLIC / "epoch-curves.png", dpi=180); plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 3.7), layout="constrained")
    draw_matrix(ax, e["epoch"]["outer_metrics"]["confusion_matrix"], "MLP: five outer development folds, 3,070 images", NAMES)
    fig.savefig(PUBLIC / "epoch-confusion-matrix.png", dpi=200); plt.close(fig)


def build(e):
    m, c = e["baseline"], e["historical_candidate"]
    body = ParagraphStyle("Body", fontName="Helvetica", fontSize=12.5, leading=18, spaceAfter=10, textColor=colors.HexColor(INK))
    title = ParagraphStyle("Title", parent=body, fontName="Helvetica-Bold", fontSize=25, leading=29, spaceAfter=18)
    heading = ParagraphStyle("Heading", parent=body, fontName="Helvetica-Bold", fontSize=14, leading=19, spaceBefore=9, spaceAfter=8)
    small = ParagraphStyle("Small", parent=body, fontSize=10, leading=14, spaceAfter=7)
    cell = ParagraphStyle("Cell", parent=body, fontSize=10.5, leading=14, spaceAfter=0)
    story = []

    def p(text, style=body):
        story.append(Paragraph(escape(text).replace("\n", "<br/>"), style))

    def start(tag, text):
        if story: story.append(PageBreak())
        p(tag.upper(), small); p(text, title)

    def table(rows, widths):
        data = [[Paragraph(escape(str(value)).replace("\n", "<br/>"), cell) for value in row] for row in rows]
        t = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dceaf1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(PALE)]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 9),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 9), ("LINEBELOW", (0, 0), (-1, 0), .6, colors.HexColor(BLUE))]))
        story.extend([t, Spacer(1, 12)])

    def say(text):
        p("SAY THIS", heading); p(text)

    def limit(text):
        p("LIMIT / NEXT EVIDENCE", heading); p(text)

    def evidence(text):
        p("EVIDENCE: " + text, small)

    start("Read this first | 19 October 2026", "EggGrade IoT\nDefense guide")
    p("Decision: keep the current web model.", heading)
    p("A newer model must improve useful results. A higher headline percentage alone is not enough.")
    table([["Same 649 historical images", "Current app", "Tested candidate"],
           ["Correct before recapture", "550 / 649\n84.75%", "572 / 649\n88.14%"],
           ["Correct accepted / all inputs", "423 / 649\n65.18%", "315 / 649\n48.54%"],
           ["Coverage: accepted / all", "444 / 649\n68.41%", "315 / 649\n48.54%"],
           ["Asked for another scan", "205", "334"]], [245, 127, 127])
    p("Why keep it? The tested candidate returns 108 fewer correct accepted results. Other candidates still miss the Day 16 / Day 18 requirements.")
    say("We compared models using the same inputs. We kept the current model because the candidate increased recaptures and reduced useful correct results.")
    p("Read the SAY THIS answer first on each question page. Use the numbers below it if the panel asks for detail.", small)
    p("Tested candidate: grouped-camera-trial-20261019, full-frame RBF classifier. Later development experiments are compared on page 14.", small)
    p("Current release: unfertilized-trial-20261019. Historical results are not field accuracy. No independent 96% or 99% claim is established.", small)

    start("Q1 | Training", "How did you train it?")
    say("We used pretrained image feature extractors. We trained a classifier using labeled egg images, kept each egg in one split, and used validation data to choose settings.")
    table([["Step", "What we did"],
           ["1. Prepare data", "3,719 images. Your 1,590 new views are included. R1, R2 and R3 are excluded."],
           ["2. Group eggs", "All views of one known egg stay together. We split before training or augmentation."],
           ["3. Prepare images", "RGB, 224 x 224 pixels, ImageNet normalization. Average original and flipped image features."],
           ["4. Train the head", "Freeze DINOv2 and EfficientNet-B0. Fit logistic regression on 2,256 training images."],
           ["5. Select and evaluate", "Use validation for weights and recapture thresholds. Report the 649-image historical evaluation separately."]], [120, 379])
    p("Training settings: C = 100, seed = 42, per-egg weight = 20. Each egg shares its weight across its views. Class weights balance total effective class weight.", small)
    limit("Age labels are user-reported farm ages. Public labels are source annotations. Independent biological verification remains incomplete.")
    evidence("train_unfertilized.py; classifier-fit-script-verification.json; manifest and split audit in the technical packet.")

    start("Q2 | Data split", "Why this split?")
    say("The split protects against seeing the same egg in training and testing. It follows egg identities and source groups, so it is not a fixed 80/20 split.")
    table([["Partition", "Images", "D16 / D18 / Reject", "Known eggs"],
           ["Train", "2,256 (60.66%)", "315 / 327 / 1,614", "10"],
           ["Validation", "814 (21.89%)", "286 / 290 / 238", "10"],
           ["Historical test", "649 (17.45%)", "285 / 290 / 74", "10"]], [110, 125, 175, 89])
    p("Train learns classifier weights. Validation chooses settings. Historical test reports performance on previously excluded images.")
    p("1,590 new photos = 90 three-view photos + 1,500 rotation photos. They represent 30 eggs, not 1,590 independent eggs.")
    p("Each split has 530 new photos plus 10 earlier photos. Each split contains five Day 16 and five Day 18 eggs.")
    p("There are 2,099 public images: 173 age images and 1,926 Unfertilized images. App name: Reject.")
    limit("The historical test was inspected during earlier development. It cannot act as a fresh independent confirmation. Public egg identities and batch records are incomplete.")
    evidence("split-counts.csv; leakage-audit.json; manifest SHA-256 in model-evidence.json.")

    start("Q3 | Metrics", "Where are the scores?")
    say("Here are precision, recall and F1 for every class. We also show recaptures, because accepted accuracy alone hides how often the app gives no grade.")
    table([["Class", "Images", "Precision", "Recall", "F1"]] +
          [[name, row["support"], pct(row["precision"]), pct(row["recall"]), pct(row["f1"])] for name, row in zip(NAMES, m["per_class"])], [104, 70, 110, 105, 110])
    table([["Metric", "Result", "Meaning"],
           ["Raw accuracy", pct(m["raw_accuracy"]), "Correct before recapture gates"],
           ["Balanced accuracy", pct(m["balanced_accuracy"]), "Average recall across three classes"],
           ["Macro / weighted F1", "88.50% / 84.72%", "Equal class weight / image-count weight"],
           ["Accepted accuracy", "95.27%", "423 correct out of 444 accepted"],
           ["Coverage / recapture", "68.41% / 31.59%", "444 accepted / 205 recaptures"],
           ["Correct accepted / all", "65.18%", "423 correct accepted out of 649"]], [155, 126, 218])
    p("Raw accuracy 95% interval: 72.40% to 94.61%. This resamples 66 recorded clusters: 10 eggs and 56 public image families. 5,000 draws; seed 42.", small)
    limit("Reject's 100% here means 74 public labeled images were correct. It does not establish 100% performance on real Reject eggs.")
    evidence("model-evidence.json; full per-class intervals in classification-metrics.csv. Active model only on this page.")

    start("Q3 continued | Confusion matrices", "Read rows, then columns")
    p("Rows = reference labels. Columns = predictions. Diagonal cells are correct. Other cells are mistakes or recaptures.")
    for name in ("raw_confusion_matrix.png", "selective_confusion_matrix.png"):
        story.append(Image(str(PUBLIC / name), width=499, height=231))
    p("Example: 63 Day 18 images were predicted Day 16 before gates. After gates, 18 Day 18 images still received Day 16.")
    p("Reject* = public Unfertilized source label. Recapture = no grade issued. They are different outcomes.", small)
    evidence("649 historical images; unfertilized-trial-20261019. Counts recomputed from saved predictions.")

    start("Q4 | Computation", "How did you calculate it?")
    say("We count correct and incorrect predictions in the confusion matrix, then apply the standard formulas. Recaptures stay visible in separate metrics.")
    p("For Day 16: TP = 249, FP = 63, FN = 36, TN = 301.", heading)
    p("TP: correct Day 16. FP: other class called Day 16. FN: Day 16 called another class. TN: other class called another class.", small)
    table([["Metric", "Formula", "Actual result"],
           ["Precision", "TP / (TP + FP)", "249 / 312 = 79.81%"],
           ["Recall", "TP / (TP + FN)", "249 / 285 = 87.37%"],
           ["F1", "2TP / (2TP + FP + FN)", "498 / 597 = 83.42%"],
           ["Raw accuracy", "Correct / all inputs", "550 / 649 = 84.75%"],
           ["Balanced accuracy", "Mean of three recalls", "88.55%"],
           ["Macro F1", "Mean of three class F1 scores", "88.50%"],
           ["Weighted F1", "Sum(class count x F1) / all", "84.72%"],
           ["Accepted accuracy", "Correct accepted / accepted", "423 / 444 = 95.27%"],
           ["Coverage", "Accepted / all inputs", "444 / 649 = 68.41%"],
           ["Correct accepted / all", "Correct accepted / all inputs", "423 / 649 = 65.18%"]], [125, 207, 167])
    p("Zero denominators: class precision, recall or F1 becomes 0; missing support is flagged. Accepted accuracy is undefined if no inputs are accepted.", small)
    evidence("scientific_metrics.py; test_scientific_metrics.py; model-evidence.json. Counts and formulas checked during PDF generation.")

    start("Q5 | Repeatability", "Does the same egg give\nthe same result?")
    say("Identical saved inputs gave exactly the same scores in our test. Fresh camera scans are a different test. Strict physical zero-gap is not established.")
    table([["Test", "Measured result"],
           ["A. Same saved inputs", "9 three-image bundles, 10 repeats each. 270 fresh view inferences. Model reloaded halfway."],
           ["A. Agreement", "Same class and accept/recapture decision in every tested bundle."],
           ["A. Maximum score difference", "0.0 across the complete score vectors."],
           ["B. Fresh physical scans", "No qualifying study. Score difference not measured."]], [189, 310])
    p("Saved inputs cover six known age eggs and three public Unfertilized image families. Public family identity is not physical egg identity.")
    p("Strict rule: any nonzero full-precision score difference fails. Rounding, reusing predictions or hiding failed scans cannot count as consistency.")
    limit("ZERO-GAP REQUIREMENT NOT MET. We still need repeated live scans of independently identified eggs from every class.")
    evidence("check_saved_repeatability.py; repeatability-results.json; full score logs in the local technical packet.")

    start("Q6 | Day 16 versus Day 18", "Why are the ages confused?")
    say("The two ages can look similar under candling. Our model sees appearance, not an incubation clock. Lighting, shell variation and uncertain labels can also affect the result.")
    table([["Observed before gates", "Count"], ["Day 16 predicted Day 18", "36 / 285"],
           ["Day 18 predicted Day 16", "63 / 290"], ["Total age errors", "99 / 575 age images"]], [365, 134])
    p("Observed in validation: both ages can show a large dark interior and bright lower illumination. Inspected examples pass the quality checks but remain ambiguous.")
    p("Biological difference: development continues over the two days. Developmental timing also differs by duck breed. No single brightness cutoff establishes exact age.")
    p("Possible causes: light and exposure changes, different shell properties, overlapping appearances, and missing exact incubation records. These are hypotheses, not proven causes of each error.")
    limit("We need new age-confirmed eggs, documented incubation times and controlled capture conditions to separate these effects.")
    evidence("Validation error review and raw matrix; Trela et al., Poultry Science (2025), DOI 10.1016/j.psj.2025.105132; Metzer Farms candling chart.")
    p("https://doi.org/10.1016/j.psj.2025.105132\nhttps://www.metzerfarms.com/candling-pictures.html", small)

    start("Q7 | Training duration", "Which epoch did you stop at?")
    say("The current app uses a logistic classifier, not epoch-based neural training. A separate MLP experiment selected epoch 42 and stopped at 50 in its first inner fold. It was not deployed.")
    table([["Model", "Actual training record"],
           ["Current app", "Frozen encoders + logistic head. Reproduced fit converged in 38 L-BFGS iterations. Maximum 3,000."],
           ["Experimental 64-unit MLP", "Maximum 60 epochs. Patience 8. First inner fold selected epoch 42; training ended at 50."],
           ["Why stop?", "Eight epochs gave no improvement under the predefined validation ranking."],
           ["Other selected epochs", "Five outer refits used 42, 1, 18, 3 and 12 epochs. There is no single best epoch for every fold."]], [160, 339])
    p("Best checkpoint = selected weights. Final epoch = when training stopped. They need not be the same.")
    p("Selection ranks weaker-age recall, mean age recall, public-source F1, then lower loss. Outer evaluation data does not choose the stopping point.", small)
    limit("The graph appendix shows the inactive MLP only. Never describe its curves as the web model's training history. Original active solver iterations were not logged; 38 is the verified reproduction.")
    evidence("hidden-64/fold-1-inner/history.jsonl and summary.json; train_nested_feature_epochs.py; classifier-fit-script-verification.json.")

    start("Q8 | Leakage", "Did test data leak into training?")
    say("Our checks found no recorded cross-split file, pixel, known-egg or source-family overlaps. That is not proof of zero leakage. Missing public identities and prior test reuse remain limitations.")
    table([["Check", "Result"],
           ["Recorded file hashes", "All 3,719 files match."],
           ["Cross-split exact files / pixels", "0 overlaps found."],
           ["Known eggs / recorded families", "0 cross-split overlaps found."],
           ["Near-duplicate image check", "0 candidates under the declared thresholds."],
           ["Development fold groups", "0 recorded group crossings."],
           ["Learned normalization", "Fitted within training folds only."]], [240, 259])
    p("Near-duplicate rule: 64-bit dHash distance at most 3 AND 32 x 32 RGB mean difference at most 6/255.", small)
    limit("Public physical egg identities are unknown. Batch IDs are missing. Reject images come from public sources; camera images cover age classes. The model may learn source cues. The historical test is already inspected.")
    evidence("audit_scientific_dataset.py; leakage-audit.json; group folds and source hashes retained in the technical packet.")

    start("Q9 | Architecture", "Which CNN did you use?")
    say("It is a hybrid model. EfficientNet-B0 is the CNN. DINOv2 ViT-S/14 is a transformer. Their frozen features are combined, then a trained logistic head predicts three classes.")
    table([["Component", "Role", "Trained here?"],
           ["EfficientNet-B0", "CNN; 1,280 features; ImageNet pretrained", "No - frozen"],
           ["DINOv2 ViT-S/14", "Vision transformer; 384 features", "No - frozen"],
           ["Feature fusion", "Normalize and combine 1,664 features", "No learned fusion"],
           ["Logistic head", "Scores Day 16, Day 18, Unfertilized", "Yes"],
           ["Quality / confidence gates", "Request recapture when requirements fail", "Selected on validation"]], [160, 235, 104])
    p("The app displays Unfertilized as Reject. This is a source-label mapping, not proof of spoilage, food safety or sellability.")
    p("Live workflow: three views. The holder pauses for capture, moves between views, then resumes rotation. Accepted views must agree; at least two accepted views must have distinct hashes.")
    p("App model SHA-256 begins 479211e3e587. Full registry, model and camera-head hashes are in model-evidence.json.", small)
    limit("A newer experimental architecture is not automatically the model loaded by the web app. Compare the runtime release and hashes.")
    evidence("Active model config; model_service.py, including view_consensus and combine_views; authenticated runtime verification.")

    start("Q10 | Field test", "What is the field accuracy?")
    say("FIELD ACCURACY NOT YET ESTABLISHED. The reported accuracy comes from saved historical images. We have prepared a separate test using new physical eggs and independent reference labels.")
    table([["Planned study", "Requirement"],
           ["New eggs", "90 total: 30 Day 16, 30 Day 18, 30 confirmed Unfertilized."],
           ["Independence", "At least three batches per class. Document egg IDs, incubation records, assessor and reference method."],
           ["Primary result", "First three-view attempt for each of the 90 eggs. Include failed and recapture attempts."],
           ["Repeat study", "Three eggs per class, ten scans each within ten minutes. 171 total planned attempts, still only 90 eggs."],
           ["Success criteria", "Raw accuracy and each class recall at least 96%. Coverage at least 68.41%; correct accepted / all at least 65.18%. No paired baseline regression."]], [145, 354])
    p("At 30 eggs per class, one error gives 96.67%; two give 93.33%. Confidence intervals still matter. Resample whole batches and keep repeated scans attached to their egg.", small)
    limit("No new independently referenced eggs are available. Fresh physical score gap is unmeasured. A prepared form is not a completed field test.")
    evidence("scientific-field-protocol.txt; blank collection workbook; collect_scientific_field_scan.py and its validation tests.")

    start("Graph appendix | Experimental model only", "Actual training graphs")
    story.append(Image(str(PUBLIC / "epoch-curves.png"), width=499, height=218.3))
    p("Top row: training. Bottom row: validation. Loss should fall; higher accuracy, precision, recall and F1 are better. Gaps between training and validation can indicate limited generalization.")
    story.append(Image(str(PUBLIC / "epoch-confusion-matrix.png"), width=499, height=231))
    p("Curves: first inner fold, epochs 1-50. Precision, recall and F1 use macro averaging. Matrix: five outer development folds. These are different evaluation populations within the same MLP experiment.", small)
    p("Outer raw accuracy 95.28%. Physical-age recall: Day 16 88.33%, Day 18 92.78%. This candidate was not deployed.", small)
    evidence("Actual logged values in model-evidence.json; full-size PNGs beside this PDF. No invented YOLO loss or mAP graphs.")

    start("Decision evidence | Candidates are not field results", "What improved, what did not")
    table([["Selected development experiment", "Raw overall", "D16 recall", "D18 recall"]] +
          [[row["name"], pct(row["raw_accuracy"]), *map(pct, row["camera_age_recall"])] for row in e["experiments"]], [230, 89, 90, 90])
    p("236 configurations. Same 3,070 development images, 20 physical age eggs, five grouped folds. Age recalls use 540 physical views per age. Overall accuracy also includes 1,852 public Reject images.")
    p("Best selected overall result: 96.87%. Its physical-age recalls are 95.19% and 94.63%, both below 96%. Selection uses these development results, so they are not independent confirmation.")
    p("Same-fold linear control: Day 16 88.33%, Day 18 95.00%. The selected interior candidate improves Day 16 but slightly reduces Day 18. No complete promotion case is established.")
    say("We measured improvements, but we did not replace the web model without meeting the full criteria. The next valid confirmation needs new independently labeled eggs.")
    p("Public evidence: model-evidence.json and PNGs beside this guide. Full local evidence: scientific packet, raw logs and scripts. Photos, accounts, credentials and private histories are not included here.", small)

    def footer(canvas, doc):
        canvas.setStrokeColor(colors.HexColor("#c9dae5")); canvas.line(48, 38, A4[0] - 48, 38)
        canvas.setFont("Helvetica", 8); canvas.setFillColor(colors.HexColor(INK))
        canvas.drawString(48, 25, "EggGrade IoT | Evidence-based defense | 19 Oct 2026")
        canvas.drawRightString(A4[0] - 48, 25, f"{doc.page} / 14")
    PDF.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(PDF), pagesize=A4, leftMargin=48, rightMargin=48, topMargin=42, bottomMargin=50,
                      title="EggGrade IoT - Easy Technical Defense", author="EggGrade IoT").build(story, onFirstPage=footer, onLaterPages=footer)
    reader = PdfReader(PDF); text = "\n".join(page.extract_text() for page in reader.pages)
    assert len(reader.pages) == 14, f"Unexpected pagination: {len(reader.pages)}"
    for required in ("Q1", "Q10", "84.75%", "95.27%", "1,590", "ZERO-GAP REQUIREMENT NOT MET", "FIELD ACCURACY NOT YET ESTABLISHED"):
        assert required in text
    assert "C:/Users" not in text and "C:\\Users" not in text
    shutil.copyfile(PDF, PUBLIC / PDF.name)
    print(json.dumps({"pdf": str(PDF), "pages": len(reader.pages), "sha256": sha(PDF), "metrics_self_check": "passed", "visual_review": "required"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh-evidence", action="store_true")
    args = parser.parse_args()
    if args.refresh_evidence: refresh()
    data = read(SNAPSHOT); verify(data); figures(data); build(data)
