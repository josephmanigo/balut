"""Build the panel report from sealed training, held-out, and deployment evidence."""
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile

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
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak

RUN = ROOT / "ml/runs/retained-unfertilized-serving-20261019"
TEST = ROOT / "ml/runs/unfertilized-heldout-20261019-v1"
DATA = ROOT / "data/local/retained-camera-unfertilized-20261019"
OUT = ROOT / "output/model-results/EggGrade-IoT-Unfertilized-Results-20261019"
PDF = ROOT / "output/pdf/EggGrade-IoT-Unfertilized-Training-Results-20261019.pdf"
LABELS = ["DAY_16", "DAY_18", "UNFERTILIZED"]
NAMES = ["Day 16", "Day 18", "Unfertilized"]
INK, TEAL, MUTED = "#152a24", "#267867", "#52645b"


def read(path):
    return json.loads(path.read_text())


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_lock(folder, filename):
    lock = read(folder / filename)
    assert all(sha(folder / name) == digest for name, digest in lock["artifacts"].items())
    return lock


def pct(value):
    return "N/A" if value is None else f"{100 * value:.2f}%"


def summary(raw, selective):
    raw, selective = np.asarray(raw), np.asarray(selective)
    count, accepted = int(raw.sum()), int(selective[:, :3].sum())
    correct = int(sum(selective[i, i] for i in range(3)))
    assert raw.shape == (3, 3) and selective.shape == (3, 4)
    np.testing.assert_array_equal(raw.sum(1), selective.sum(1))
    return {"images": count, "raw_accuracy": float(np.trace(raw) / count),
            "accepted_accuracy": correct / accepted if accepted else None,
            "coverage": accepted / count, "correct_over_all": correct / count,
            "correct": correct, "wrong": accepted - correct, "recapture": count - accepted}


def classification(raw):
    raw = np.asarray(raw)
    report = []
    for i in range(3):
        tp, support, predicted = int(raw[i, i]), int(raw[i].sum()), int(raw[:, i].sum())
        precision, recall = tp / predicted if predicted else 0, tp / support
        report.append({"class": LABELS[i], "precision": precision, "recall": recall,
                       "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0,
                       "support": support})
    return report


def plot_matrices(name, raw, selective):
    matrices = [np.asarray(raw), np.asarray(selective)]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.7), constrained_layout=True)
    maximum = max(int(matrix.max()) for matrix in matrices)
    for axis, title, matrix in zip(axes, ["Raw predictions", "After recapture gates"], matrices, strict=True):
        axis.imshow(matrix, cmap="BuGn", vmin=0, vmax=maximum)
        columns = NAMES + (["Recapture"] if matrix.shape[1] == 4 else [])
        axis.set_xticks(range(len(columns)), columns, rotation=22, ha="right", fontsize=11)
        axis.set_yticks(range(3), NAMES, fontsize=11)
        axis.set_xlabel("Predicted label", fontsize=12)
        axis.set_ylabel("Recorded label", fontsize=12)
        axis.set_title(title, fontsize=14, color=INK, weight="bold", pad=15)
        for i in range(3):
            for j in range(matrix.shape[1]):
                axis.text(j, i, str(matrix[i, j]), ha="center", va="center", fontsize=18,
                          color="white" if matrix[i, j] > maximum * .52 else INK, weight="bold")
        axis.spines[["top", "right", "bottom", "left"]].set_visible(False)
    fig.savefig(OUT / f"{name}-confusion-matrices.png", dpi=260, facecolor="white")
    plt.close(fig)
    for suffix, matrix in zip(["raw", "selective"], matrices, strict=True):
        with (OUT / f"{name}-{suffix}-confusion-matrix.csv").open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Recorded / predicted", *NAMES, *(["Recapture"] if matrix.shape[1] == 4 else [])])
            writer.writerows([[label, *map(int, values)] for label, values in zip(NAMES, matrix, strict=True)])


def main():
    train_lock = check_lock(RUN, "selection-lock.json")
    check_lock(TEST, "evaluation-lock.json")
    audit, training, heldout = read(DATA / "audit.json"), read(RUN / "metrics.json"), read(TEST / "metrics.json")
    live = read(ROOT / "output/unfertilized-20261019/egggrade-live-deployment.json")
    assert sha(DATA / "manifest.jsonl") == audit["manifest_sha256"]
    assert audit["total_rows"] == 3719 and training["test_images_opened"] == 0
    assert heldout["test_images_opened"] == 649 and not heldout["model_or_policy_changed"]
    assert live["readiness"]["serviceReady"] and live["bundle_matches_verified_local_build"]
    assert train_lock["physical_unfertilized_validation_passed"] is False
    val = training["validation"]
    raw_test, selective_test = [heldout["overall"][key] for key in ("raw_confusion_matrix", "selective_confusion_matrix")]
    val_summary = summary(val["raw_confusion_matrix"], val["selective_confusion_matrix"])
    test_summary = summary(raw_test, selective_test)
    assert val_summary["images"] == 814 and test_summary["images"] == 649
    OUT.mkdir(parents=True, exist_ok=True)
    PDF.parent.mkdir(parents=True, exist_ok=True)
    for name, raw, selective in [("validation", val["raw_confusion_matrix"], val["selective_confusion_matrix"]),
                                  ("held-out", raw_test, selective_test)]:
        plot_matrices(name, raw, selective)
    reports = {"validation": classification(val["raw_confusion_matrix"]), "held_out": classification(raw_test)}
    with (OUT / "classification-report.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["partition", "class", "precision", "recall", "f1", "support"])
        for part, values in reports.items():
            for row in values:
                writer.writerow([part, *row.values()])
    (OUT / "classification-report.json").write_text(json.dumps(reports, indent=2) + "\n")
    candidates = read(RUN / "candidates.json")
    with (OUT / "candidate-comparison.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["camera_weight_per_egg", "validation_raw_accuracy", "validation_coverage", "validation_correct_over_all"])
        for candidate in candidates:
            metrics = summary(candidate["raw_confusion_matrix"], candidate["selective_confusion_matrix"])
            writer.writerow([candidate["camera_weight_per_egg"], metrics["raw_accuracy"], metrics["coverage"], metrics["correct_over_all"]])
    for name, font in [("Body", "segoeui.ttf"), ("Bold", "segoeuib.ttf"), ("Display", "georgia.ttf")]:
        pdfmetrics.registerFont(TTFont(name, str(Path("C:/Windows/Fonts") / font)))
    styles = {"title": ParagraphStyle("title", fontName="Display", fontSize=27, leading=32, textColor=colors.HexColor(INK), spaceAfter=15),
              "heading": ParagraphStyle("heading", fontName="Bold", fontSize=15, leading=19, textColor=colors.HexColor(INK), spaceBefore=10, spaceAfter=9),
              "body": ParagraphStyle("body", fontName="Body", fontSize=10, leading=14, textColor=colors.HexColor(INK), spaceAfter=10),
              "small": ParagraphStyle("small", fontName="Body", fontSize=8, leading=11, textColor=colors.HexColor(MUTED), spaceAfter=8),
              "cell": ParagraphStyle("cell", fontName="Body", fontSize=8.5, leading=11.5, textColor=colors.HexColor(INK))}
    story = []
    def p(text, style="body"):
        return Paragraph(str(text), styles[style])
    def add(text, style="body"):
        story.append(p(text, style))
    def table(rows, widths):
        grid = Table([[p(cell, "cell") for cell in row] for row in rows], colWidths=widths, repeatRows=1, hAlign="LEFT")
        grid.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e5eee8")),
                  ("LINEBELOW", (0, 0), (-1, 0), .7, colors.HexColor(TEAL)),
                  ("LINEBELOW", (0, 1), (-1, -1), .3, colors.HexColor("#d7ded8")),
                  ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                  ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        story.append(grid)
        story.append(Spacer(1, 11))
    def title(text, subtitle):
        add(text, "title")
        add(subtitle)
    def figure(name):
        story.append(Image(str(OUT / name), width=510, height=200))
        story.append(Spacer(1, 10))
    now = datetime.now(timezone(timedelta(hours=8))).strftime("19 October 2026, %H:%M UTC+8")

    title("Model training<br/>and evaluation results", "EggGrade IoT / Day 16, Day 18 and Unfertilized / Technical defense report / 19 October 2026")
    add("<b>Retraining is complete and the new release is deployed.</b> The retained image encoder is reused with a newly fitted classifier for three explicit classes. R1, R2 and R3 are excluded from this model's dataset.")
    add("Locked held-out image result", "heading")
    table([["Metric", "Result", "What it measures"],
           ["Raw accuracy", pct(test_summary["raw_accuracy"]), "Correct before uncertainty gates / 649 images"],
           ["Accepted accuracy", pct(test_summary["accepted_accuracy"]), "Correct / classified images only"],
           ["Coverage", pct(test_summary["coverage"]), "Classified / all 649 images"],
           ["Correct over all inputs", pct(test_summary["correct_over_all"]), "Correct classified / all 649 images"],
           ["Correct / wrong / recapture", f"{test_summary['correct']} / {test_summary['wrong']} / {test_summary['recapture']}", "Recapture is not a correct classification"]], [125,100,285])
    add("How to present this result", "heading")
    add("The classifier was trained on 2,256 images, selected and calibrated on 814 validation images, then evaluated once on 649 reserved test images with its parameters and gates locked. These figures measure agreement with recorded labels on this dataset.")
    add("<b>Scope:</b> the test contains repeated views of ten age eggs plus public source images. It is not a 649-egg trial, a live-camera Unfertilized test, or proof of embryo absence. A 99% field-accuracy claim is not supported.")
    add("The former Reject model and this Unfertilized model solve different label tasks. Retraining alone does not establish that the new task is more accurate than the old one.", "small")
    story.append(PageBreak())

    title("Dataset and labels", "3,719 images / grouped partitions / original evidence preserved")
    table([["Partition", *NAMES, "Total"],
           *[[part.title(), *[audit["partition_counts"][part][label] for label in LABELS], sum(audit["partition_counts"][part].values())] for part in ("train", "validation", "test")]], [126,96,96,96,96])
    table([["Data included", "Images", "Meaning"],
           ["Age camera views", 1620, "30 original + 90 multiangle + 1,500 sweep views of the same 30 age eggs"],
           ["Retained public age examples", 173, "Source Day 16 / Day 18 labels; not new physical eggs"],
           ["Public Unfertilized crops", 1926, "Literal Unfertilized annotations in retained Pat v8 data"],
           ["Excluded vendor Reject views", 150, "All R1/R2/R3 photos excluded from the new task"],
           ["Other excluded Reject rows", 1888, "No old Reject label was renamed Unfertilized"]], [160,64,286])
    add("Partition integrity", "heading")
    add("All views of a known physical egg stay in one partition. Public image families remain grouped. Byte hashes and pixel hashes were checked for cross-partition duplicates. The age camera collection has ten training, ten validation and ten test eggs, with 540 views in each partition.")
    add("Label authority", "heading")
    add("Day 16 / Day 18 camera ages are operator-reported incubation ages. Public Unfertilized labels come from source bounding-box annotations, not an independent embryo examination. Physical egg and farm-batch identities are unavailable for the public source. Reject eggs can have other conditions and are not automatically Unfertilized.")
    add("Original photos, previous training runs and historical app results remain preserved with their original meanings. Only membership in the new dataset and model changed.", "small")
    story.append(PageBreak())

    title("Training method", "Frozen visual features + weighted three-class logistic classifier")
    table([["Setting", "Implemented value"], ["Retained encoder", "DINOv2 ViT-S/14 + EfficientNet-B0; frozen, reused visual features [1,2]"],
           ["Serving input", "RGB JPEG; resized to 224 x 224 with retained normalization"],
           ["Classifier", "Three-class logistic head; C=100; seed=42; maximum 3,000 optimizer iterations"],
           ["Weighting", "Equal effective class weight; each camera egg's weight shared across its views"],
           ["Candidates", "Camera weight per egg: 20, 50, 100; selected: 20"],
           ["Selection", "Mean validation correct-over-all across five source/camera class groups; mean group raw recall tie-break"],
           ["Serving calibration", "Validation embeddings recomputed with actual ONNX CPU encoder; PNG crops converted to JPEG quality95"],
           ["Test protocol", "No test fitting or threshold selection; one locked evaluation after selection"]], [130,380])
    add("Validation candidate comparison", "heading")
    table([["Egg weight", "Selection score", "Raw accuracy", "Coverage"],
           *[[candidate["camera_weight_per_egg"], pct(sum(group["correct_classified"] / group["images"] for group in candidate["validation_groups"].values()) / 5),
              *[pct(summary(candidate["raw_confusion_matrix"], candidate["selective_confusion_matrix"])[key]) for key in ("raw_accuracy", "coverage")]] for candidate in candidates]], [100,136,137,137])
    add("Selection score gives each of the five validation groups equal weight. It differs from accuracy or coverage calculated over all images, which are dominated by repeated camera views.", "small")
    add("Recapture and live capture", "heading")
    add("The final decision retains image-quality, decision-margin and nearest-training-feature checks. Live scans require three distinct paused views and consistent accepted labels. The holder pauses for capture, spins between views and resumes afterward; the candling light stays on.")
    add("This run retrains the classifier head, not all neural-network weights. Maximum optimizer iterations are not epochs. No epoch loss or accuracy curves were produced, so none are invented for this report.", "small")
    story.append(PageBreak())

    title("Development validation", "814 images used for candidate selection and recapture-gate calibration")
    figure("validation-confusion-matrices.png")
    table([["Recorded class", "Images", "Raw correct", "Accepted correct", "Recapture"],
           *[[name, sum(val["raw_confusion_matrix"][i]), val["raw_confusion_matrix"][i][i], val["selective_confusion_matrix"][i][i], val["selective_confusion_matrix"][i][3]] for i, name in enumerate(NAMES)]], [142,75,95,104,94])
    table([["Metric", "Development value"], ["Raw accuracy", pct(val_summary["raw_accuracy"])],
           ["Accepted accuracy", f"{pct(val_summary['accepted_accuracy'])} ({val_summary['correct']} accepted; 0 wrong)"],
           ["Coverage and correct over all", pct(val_summary["coverage"])],
           ["Recaptures", f"{val_summary['recapture']} / 814"]], [255,255])
    add("Interpretation", "heading")
    add("The 661 accepted validation predictions agree with their recorded labels. That accepted accuracy is measured on the same development data used to set the gates. It is not an independent 100% accuracy claim. The age camera views are correlated observations of ten validation eggs.")
    story.append(PageBreak())

    title("Locked test matrices", "649 reserved images / unchanged model and gates / individual-image decisions")
    figure("held-out-confusion-matrices.png")
    table([["Recorded class", "Precision", "Recall", "F1", "Support"],
           *[[NAMES[i], pct(row["precision"]), pct(row["recall"]), pct(row["f1"]), row["support"]] for i, row in enumerate(reports["held_out"])]], [142,92,92,92,92])
    macro_f1 = sum(row["f1"] for row in reports["held_out"]) / 3
    add(f"Raw macro F1: <b>{macro_f1:.4f}</b>. Precision, recall and F1 above use raw predictions before gates. Matrices count images, including correlated repeated views.")
    table([["Final decision", "Count", "Rate over all 649"], ["Correctly classified", test_summary["correct"], pct(test_summary["correct_over_all"])],
           ["Wrong against recorded labels", test_summary["wrong"], pct(test_summary["wrong"] / 649)],
           ["Recapture requested", test_summary["recapture"], pct(test_summary["recapture"] / 649)]], [260,90,160])
    add("Every reserved image was evaluated once through the deployed release's ONNX CPU camera head and gates. Native camera JPEGs were unchanged. Public PNG crops used JPEG quality95, matching validation preprocessing. No model or policy changed after the test.", "small")
    story.append(PageBreak())

    title("What the test establishes", "Source and camera groups remain separate; image counts are not egg counts")
    table([["Test group", "Images", "Raw correct", "Correct / wrong / recapture"],
           *[[name.replace("camera:", "Camera ").replace("source:", "Public ").replace("DAY_", "Day ").replace("UNFERTILIZED", "Unfertilized"),
              row["images"], sum(row["raw_confusion_matrix"][i][i] for i in range(3)), f"{row['correct_classified']} / {row['wrong_classified']} / {row['recapture']}"] for name, row in heldout["groups"].items()]], [175,60,95,180])
    add("Physical age eggs", "heading")
    table([["Reserved egg", "Views", "Raw correct", "Correct / wrong / recapture"],
           *[[name.split(":")[-1], row["images"], sum(row["raw_confusion_matrix"][i][i] for i in range(3)), f"{row['correct_classified']} / {row['wrong_classified']} / {row['recapture']}"] for name, row in sorted(heldout["physical_eggs"].items())]], [160,65,105,180])
    add("The 540 camera test images represent only ten age eggs. Some reserved age eggs were already used in earlier live checks of the previous Reject release; their images did not enter this model's fitting or selection. This test is therefore not a fresh prospective farm trial.", "small")
    add("No confirmed Unfertilized egg is available for a live check in this box. Public-source performance cannot establish biological embryo absence or general accuracy on future eggs. Wider testing needs new eggs, independent incubation/embryo records, multiple farm batches and a predeclared scan protocol.", "small")
    story.append(PageBreak())

    title("Deployment and evidence", "Same server model for web and Android / evidence recorded 19 October 2026")
    table([["Component", "Verified status"], ["Live service", '<link href="https://egggradeiot.vercel.app" color="#267867">https://egggradeiot.vercel.app</link>; serviceReady=true'],
           ["Active release", "unfertilized-trial-20261019; Day 16 / Day 18 / Unfertilized"],
           ["Camera connection", "Connected, enabled, waiting/Ready, no reported error at release verification"],
           ["Web build", "47 tests; type checks and production build passed; published JS equals checked local build"],
           ["Android", "0.4.2+6 preview APK; analysis and 19 tests passed; built for the live service"],
           ["API and ML checks", "224 backend tests and 5 new dataset/training tests passed; sealed package reconstructs and passes known-answer checks"],
           ["Operational status", "Experimental appearance classification; automaticGradingReady=false; no physical sorting or food-safety authorization"]], [130,380])
    add("Reproducibility", "heading")
    for label, value in [("Dataset", audit["manifest_sha256"]), ("Classifier head", sha(RUN / "head.npz")),
                         ("ONNX model", "479211e3e587b0bce7d9bb1be1a318c48bdc62f632374f75d980ab1dbceda31e")]:
        add(f"<b>{label} SHA-256</b><br/>{value[:32]}<br/>{value[32:]}", "small")
    add("The ZIP includes matrix PNGs/CSVs, per-class metrics, sealed training/evaluation plans, test outcomes and deployment receipt. Original dataset photos, credentials, accounts and runtime databases are excluded. The training lock remains unchanged; the subsequent held-out result is stored separately.", "small")
    add("References", "heading")
    add('[1] Oquab et al. DINOv2: Learning Robust Visual Features without Supervision. <link href="https://arxiv.org/abs/2304.07193" color="#267867">arxiv.org/abs/2304.07193</link><br/>[2] Tan and Le. EfficientNet: Rethinking Model Scaling for Convolutional Neural Networks. <link href="https://arxiv.org/abs/1905.11946" color="#267867">arxiv.org/abs/1905.11946</link><br/>[3] Pat, Balut Eggs Project v8, explicit Unfertilized COCO annotations. Retained export attribution: CC BY 4.0. <link href="https://universe.roboflow.com/pat-bteu2/balut-eggs-project-unfertilized-fertilized-and-reject-tgibj/dataset/8" color="#267867">Roboflow source dataset</link>. The live page was unavailable to the web reader; labels and attribution were verified against the retained export.', "small")
    add("Generated " + now + ". Preview APK is debug-signed and has not been physically installed or accepted in this release check.", "small")
    def page(canvas, doc):
        canvas.saveState()
        canvas.setFont("Bold", 11); canvas.setFillColor(colors.HexColor(INK))
        canvas.drawString(42, A4[1] - 32, "EggGrade IoT")
        canvas.setStrokeColor(colors.HexColor("#cfdbd2")); canvas.line(42, A4[1] - 42, A4[0] - 42, A4[1] - 42)
        canvas.setFont("Body", 7.5); canvas.setFillColor(colors.HexColor(MUTED))
        canvas.drawString(42, 25, "Technical defense / recorded-label evaluation / experimental appearance model")
        canvas.drawRightString(A4[0] - 42, 25, str(doc.page)); canvas.restoreState()
    document = SimpleDocTemplate(str(PDF), pagesize=A4, leftMargin=42, rightMargin=42, topMargin=64, bottomMargin=47,
                                 title="EggGrade IoT - Unfertilized Model Training and Evaluation", author="EggGrade IoT")
    document.build(story, onFirstPage=page, onLaterPages=page)
    reader = PdfReader(PDF)
    assert len(reader.pages) == 7, f"Unexpected page overflow: {len(reader.pages)}"
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert all(term in text for term in ["3,719", "649", "Unfertilized", "99%", "0.4.2+6"])
    shutil.copyfile(PDF, OUT / PDF.name)
    for name in ["metrics.json", "selection-lock.json", "experiment-plan.json", "config.json", "candidates.json", "gate-policy.json"]:
        shutil.copyfile(RUN / name, OUT / ("training-" + name))
    for name in ["metrics.json", "evaluation-plan.json", "evaluation-lock.json", "outcomes.jsonl"]:
        shutil.copyfile(TEST / name, OUT / ("held-out-" + name))
    shutil.copyfile(DATA / "audit.json", OUT / "dataset-audit-at-preparation.json")
    shutil.copyfile(ROOT / "output/unfertilized-20261019/egggrade-live-deployment.json", OUT / "live-deployment.json")
    shutil.copyfile(ROOT / "output/unfertilized-20261019/model-and-camera-verification.json", OUT / "model-and-camera-verification.json")
    shutil.copyfile(ROOT / "ml/balut_ml/train_unfertilized.py", OUT / "training-source.py")
    shutil.copyfile(ROOT / "scripts/evaluate_unfertilized_holdout.py", OUT / "evaluation-source.py")
    (OUT / "README.txt").write_text("EggGrade IoT - Day 16 / Day 18 / Unfertilized\n\n"
        "Current release: unfertilized-trial-20261019. Previous Reject report describes a different task.\n"
        "Training metrics and dataset audit are frozen preparation/selection records. They correctly record zero test inference at that time.\n"
        "The later held-out evaluation opened all 649 reserved images once without changing model or gates.\n"
        "Views are correlated. No confirmed physical Unfertilized camera test has been performed. No 99% field claim.\n"
        "No epoch curves exist: only the classifier head was fitted over retained frozen visual features.\n"
        "No raw photographs, credentials, accounts, runtime database or standalone model is included.\n")
    files = {path.relative_to(OUT).as_posix(): sha(path) for path in OUT.rglob("*") if path.is_file() and path.name != "bundle-manifest.json"}
    (OUT / "bundle-manifest.json").write_text(json.dumps(files, indent=2) + "\n")
    archive = OUT.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in OUT.rglob("*"):
            if path.is_file():
                bundle.write(path, path.relative_to(OUT).as_posix())
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        assert all(hashlib.sha256(bundle.read(name)).hexdigest() == digest for name, digest in files.items())
    check_lock(RUN, "selection-lock.json"); check_lock(TEST, "evaluation-lock.json")
    print(json.dumps({"pdf": str(PDF), "pages": 7, "pdf_sha256": sha(PDF), "zip": str(archive), "test": test_summary}))


if __name__ == "__main__":
    main()
