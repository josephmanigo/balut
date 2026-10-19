"""Export the sealed retraining results as matrices, CSVs, a PDF, and a ZIP."""
from collections import Counter
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
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
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
from pypdf import PdfReader

RUN = ROOT / "ml/runs/retained-camera-50views-rejects-20261019"
OUT = ROOT / "output/model-results/EggGrade-IoT-Training-Results-20261019"
PDF = ROOT / "output/pdf/EggGrade-IoT-Training-Results-20261019.pdf"
LABELS = ["DAY_16", "DAY_18", "REJECT"]
NAMES = ["Day 16", "Day 18", "Vendor Reject"]
INK, TEAL, AMBER = "#15221d", "#267867", "#a66c20"


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def read(path):
    return json.loads(path.read_text())


def matrix(scans, selective=False):
    result = np.zeros((3, 4 if selective else 3), dtype=int)
    for scan in scans:
        prediction = scan["sourcePrediction"] if selective else scan["raw_prediction"]
        result[LABELS.index(scan["truth"]), LABELS.index(prediction) if prediction else 3] += 1
    assert result.sum() == 176 and result.sum(axis=1).tolist() == [80, 80, 16]
    return result


def export_matrix(name, values, selective=False):
    with (OUT / f"{name}.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["True / predicted", *NAMES, *(["Recapture"] if selective else [])])
        writer.writerows([[label, *map(int, row)] for label, row in zip(NAMES, values, strict=True)])


def plot_pair(path, matrices, selective=False, historical=False):
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.7), constrained_layout=True)
    plot_names = ["Day 16", "Day 18", "Reject"] if historical else NAMES
    columns = plot_names + (["Recapture"] if selective else [])
    maximum = max(int(values.max()) for values in matrices)
    for axis, title, values in zip(axes, ["Current app model", "Retrained candidate - inactive"], matrices, strict=True):
        axis.imshow(values, cmap="BuGn", vmin=0, vmax=maximum)
        axis.set_xticks(range(len(columns)), columns, rotation=20, ha="right", fontsize=10)
        axis.set_yticks(range(3), plot_names, fontsize=10)
        axis.set_xlabel("Predicted label", fontsize=11, labelpad=9)
        axis.set_ylabel("Recorded label", fontsize=11, labelpad=9)
        axis.set_title(title, fontsize=13, color=INK, pad=14, weight="bold")
        for i in range(3):
            for j in range(len(columns)):
                axis.text(j, i, str(values[i, j]), ha="center", va="center", fontsize=17, weight="bold",
                          color="white" if values[i, j] > maximum*.52 else INK)
        axis.spines[["top", "right", "bottom", "left"]].set_visible(False)
    fig.savefig(path, dpi=230, facecolor="white")
    plt.close(fig)


def raw_report(values):
    result = {}
    for i, label in enumerate(LABELS):
        tp = int(values[i, i])
        support, predicted = int(values[i].sum()), int(values[:, i].sum())
        precision, recall = tp/predicted if predicted else 0, tp/support if support else 0
        result[label] = {"precision": precision, "recall": recall,
                         "f1": 2*precision*recall/(precision+recall) if precision+recall else 0, "support": support}
    result["accuracy"] = float(np.trace(values)/values.sum())
    result["macro_f1"] = float(np.mean([result[label]["f1"] for label in LABELS]))
    return result


def main():
    lock = read(RUN / "selection-lock.json")
    for name, digest in lock["artifacts"].items():
        assert sha(RUN / name) == digest, name
    metrics, outcomes = read(RUN / "metrics.json"), read(RUN / "validation-outcomes.json")
    assert metrics["test_images_opened"] == 0 and not lock["admission_passed"]
    dataset = ROOT / "data/local/retained-camera-rejects-20261019"
    audit = read(dataset / "audit.json")
    assert sha(dataset / "manifest.jsonl") == audit["manifest_sha256"]
    rows = list(map(json.loads, (dataset / "manifest.jsonl").read_text().splitlines()))
    partitions = Counter(row["partition"] for row in rows)
    assert partitions == {"train": 2111, "validation": 958, "test": 762}
    OUT.mkdir(parents=True, exist_ok=True)
    PDF.parent.mkdir(parents=True, exist_ok=True)
    raw = [matrix(outcomes[key]["sweep"]) for key in ("before_scans", "after_scans")]
    selective = [matrix(outcomes[key]["sweep"], True) for key in ("before_scans", "after_scans")]
    for suffix, values, accepted in (("current-raw", raw[0], False), ("retrained-raw", raw[1], False),
                                      ("current-selective", selective[0], True), ("retrained-selective", selective[1], True)):
        export_matrix(f"confusion-matrix-{suffix}", values, accepted)
    plot_pair(OUT / "confusion-matrix-raw.png", raw)
    plot_pair(OUT / "confusion-matrix-selective.png", selective, True)
    baseline, chosen = metrics["before"], metrics["selected_candidate"]
    after = chosen["validation"]
    historical = [np.array(value["historical"]["raw"]["confusion_matrix"]) for value in (baseline, after)]
    assert all(values.sum() == 368 for values in historical)
    plot_pair(OUT / "confusion-matrix-historical.png", historical, historical=True)
    reports = {"current": raw_report(raw[0]), "retrained": raw_report(raw[1])}
    (OUT / "classification-report.json").write_text(json.dumps(reports, indent=2)+"\n")
    with (OUT / "classification-report.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["model", "class", "precision", "recall", "f1", "support"])
        for model, report in reports.items():
            for label in LABELS:
                writer.writerow([model, label, *report[label].values()])
    candidates = read(RUN / "candidates.json")
    comparison = [("Current app", baseline["sweep"], True)] + [(f"Weight {r['camera_weight_per_egg']}", r["validation"]["sweep"], r["admission_passed"]) for r in candidates]
    with (OUT / "candidate-comparison.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["candidate", "correct", "wrong", "recapture", "raw_correct", "accepted_accuracy", "coverage", "correct_over_all", "admission_passed"])
        for name, r, passed in comparison:
            writer.writerow([name, r["correct_classified"], r["wrong_classified"], 176-r["classified"], r["raw_correct"],
                             r["accepted_accuracy"], r["coverage"], r["correct_of_all_inputs"], passed])
    plt.rcParams.update({"font.size": 11})
    fig, axis = plt.subplots(figsize=(10, 4.3), constrained_layout=True)
    x = np.arange(len(comparison))
    axis.bar(x-.18, [r["correct_of_all_inputs"]*100 for _, r, _ in comparison], .36, color=TEAL, label="Correct over all scan groups")
    axis.bar(x+.18, [r["coverage"]*100 for _, r, _ in comparison], .36, color="#d4b17a", label="Coverage")
    axis.set_xticks(x, [name for name, _, _ in comparison])
    axis.set_ylim(0, 112)
    axis.set_ylabel("Percent of 176 correlated scan groups")
    axis.spines[["top", "right"]].set_visible(False)
    axis.legend(loc="upper right", frameon=False)
    fig.savefig(OUT / "candidate-comparison.png", dpi=230, facecolor="white")
    plt.close(fig)
    for name, filename in (("Body", "segoeui.ttf"), ("Bold", "segoeuib.ttf"), ("Display", "georgia.ttf")):
        pdfmetrics.registerFont(TTFont(name, str(Path("C:/Windows/Fonts") / filename)))
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TitleEG", fontName="Display", fontSize=28, leading=33, textColor=colors.HexColor(INK), spaceAfter=17))
    styles.add(ParagraphStyle(name="HeadingEG", fontName="Bold", fontSize=16, leading=20, textColor=colors.HexColor(INK), spaceBefore=10, spaceAfter=10))
    styles.add(ParagraphStyle(name="BodyEG", fontName="Body", fontSize=10, leading=14, textColor=colors.HexColor(INK), spaceAfter=10))
    styles.add(ParagraphStyle(name="SmallEG", fontName="Body", fontSize=8, leading=11, textColor=colors.HexColor("#4f6259"), spaceAfter=8))
    styles.add(ParagraphStyle(name="CellEG", fontName="Body", fontSize=8.5, leading=12, textColor=colors.HexColor(INK)))
    story = []
    def p(text, style="BodyEG"):
        return Paragraph(text, styles[style])
    def table(data, widths=None):
        values = [[p(str(cell), "CellEG") for cell in row] for row in data]
        t = Table(values, colWidths=widths, hAlign="LEFT", repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#e5eee8")), ("LINEBELOW", (0,0),(-1,0),.7,colors.HexColor(TEAL)),
                               ("LINEBELOW", (0,1),(-1,-1),.35,colors.HexColor("#d7ded8")), ("TOPPADDING",(0,0),(-1,-1),8),
                               ("BOTTOMPADDING",(0,0),(-1,-1),8), ("VALIGN",(0,0),(-1,-1),"TOP")]))
        return t
    def heading(title, subtitle=None):
        story.append(p(title, "TitleEG"))
        if subtitle: story.append(p(subtitle))
    def figure(filename, height=220):
        story.append(Image(str(OUT/filename), width=510, height=height, kind="proportional"))
        story.append(Spacer(1,8))
    def percent(value): return f"{value*100:.2f}%"
    now = datetime.now(timezone(timedelta(hours=8))).strftime("%d %B %Y, %H:%M UTC+8")
    heading("Retained model\ntraining results".replace("\n", "<br/>"), "EggGrade IoT / Completed collection and retraining / 19 October 2026")
    story.append(p("<b>Retraining completed. The new candidate remains inactive.</b> All three retrained candidates failed the fixed comparison checks. The current app model performed better on the same validation data."))
    story.append(p("Dataset additions", "HeadingEG"))
    story.append(table([["Collection", "Added photos", "Physical eggs"], ["Earlier three-angle views",90,"Same 30 age eggs"], ["Age sweep: 50 views per egg",1500,"Same 30 age eggs"],
                        ["Reject sweep: 50 views per egg",150,"3 additional eggs"], ["Total new photos",1740,"33 numbered eggs in total"], ["Retained data plus new photos",3831,"Includes historical source data"]], [284,95,131]))
    story.append(Spacer(1,14))
    story.append(p("Main validation result", "HeadingEG"))
    story.append(table([["176 correlated scan groups / 11 eggs", "Current", "Retrained"], ["Correctly classified",153,129], ["Wrong against recorded labels",16,16], ["Another scan requested",7,31],
                        ["Accepted accuracy",percent(baseline["sweep"]["accepted_accuracy"]),percent(after["sweep"]["accepted_accuracy"])], ["Coverage",percent(baseline["sweep"]["coverage"]),percent(after["sweep"]["coverage"])],
                        ["Correct over all inputs",percent(baseline["sweep"]["correct_of_all_inputs"]),percent(after["sweep"]["correct_of_all_inputs"])]], [300,105,105]))
    story.append(Spacer(1,10))
    story.append(p("These are development results from repeated views of 11 validation eggs: five Day 16, five Day 18, and one vendor-labeled Reject. They are not an independent accuracy estimate or a 99% claim.", "SmallEG"))
    story.append(PageBreak())
    heading("Raw confusion matrices", "Before uncertainty gates. Rows are recorded labels; columns are predicted labels. Counts are correlated three-view scan groups.")
    figure("confusion-matrix-raw.png", 225)
    story.append(p("Retrained candidate: classification report", "HeadingEG"))
    story.append(table([["Recorded class", "Precision", "Recall", "F1", "Scan groups"]] + [[name, percent(reports["retrained"][label]["precision"]), percent(reports["retrained"][label]["recall"]),
                        percent(reports["retrained"][label]["f1"]), reports["retrained"][label]["support"]] for label, name in zip(LABELS,NAMES,strict=True)], [150,90,90,90,90]))
    story.append(Spacer(1,14))
    story.append(p(f"Raw accuracy: current {percent(reports['current']['accuracy'])}; retrained {percent(reports['retrained']['accuracy'])}. Raw macro F1: current {reports['current']['macro_f1']:.4f}; retrained {reports['retrained']['macro_f1']:.4f}."))
    story.append(p("Both heads missed the recorded Reject label in all 16 scan groups from R2. This exposes a failure against the supplied label; the vendor did not supply a rejection reason, so these results do not independently establish biological condition."))
    story.append(PageBreak())
    heading("Confusion matrices\nwith recapture".replace("\n","<br/>"), "The final serving decision uses the existing quality, unfamiliar-image, margin, and three-view consensus checks.")
    figure("confusion-matrix-selective.png", 225)
    story.append(table([["Recorded class", "Current correct", "Retrained correct", "Available groups"], ["Day 16",75,72,80], ["Day 18",78,57,80], ["Vendor Reject",0,0,16]], [174,112,112,112]))
    story.append(Spacer(1,16))
    story.append(p("How to read the metrics", "HeadingEG"))
    story.append(p("<b>Accepted accuracy</b> = correct classified / all classified. <b>Coverage</b> = all classified / all scan groups. <b>Correct over all inputs</b> = correct classified / all scan groups. A recapture does not count as a correct classification."))
    story.append(p("The retrained head accepted fewer correct age groups. Its accepted accuracy also declined. These results therefore do not show an accuracy improvement hidden by more abstentions."))
    story.append(PageBreak())
    heading("What was trained", "Frozen retained image encoder plus a three-class logistic classifier. No epoch-based neural-network fine-tuning was performed.")
    story.append(table([["Dataset role", "All images", "Numbered camera eggs"], ["Training",2111,11], ["Validation",958,11], ["Reserved test",762,11]], [250,110,150]))
    story.append(Spacer(1,12))
    story.append(p("The head fitted 1,521 historical training examples plus 590 eligible camera views. Camera training uses 270 Day 16 views, 270 Day 18 views, and 50 R1 Reject views. Each egg's total weight is shared across its views. All 1,740 new photos are in the dataset; 580 are assigned to each of training, validation, and reserved test."))
    story.append(p("Three candidates used C=100, maximum 3,000 optimizer iterations, seed 42, and camera weights 20, 50, or 100 per physical egg. Thresholds were unchanged. There are no epoch loss/accuracy curves to report."))
    story.append(table([["Candidate", "Correct", "Wrong", "Recapture", "Admission"]] + [[name, r["correct_classified"],r["wrong_classified"],176-r["classified"], "Baseline" if name=="Current app" else "Failed"] for name,r,_ in comparison], [174,75,75,95,91]))
    story.append(Spacer(1,14))
    figure("candidate-comparison.png", 185)
    story.append(p("Weight 100 is the saved retrained candidate. Selection does not authorize activation: all three candidates failed the fixed gates. Test images were not opened for model inference.", "SmallEG"))
    story.append(PageBreak())
    heading("Retained-data checks", "A separate comparison on the same 368 historical validation images also detected regression.")
    figure("confusion-matrix-historical.png", 210)
    story.append(table([["Historical validation", "Current", "Retrained"], ["Raw correct / 368",359,356], ["Accepted correct",208,208], ["Accepted wrong",0,2], ["Recapture",160,158]], [300,105,105]))
    story.append(Spacer(1,12))
    story.append(p("The earlier ten three-angle camera validation groups also declined from ten correctly classified to six. The active model was retained. These validation sets are development evidence; repeated scans are correlated, and Reject validation includes only one egg with an unconfirmed vendor label."))
    story.append(p("Integrity and downloadable files", "HeadingEG"))
    story.append(p("The ZIP includes this PDF, raw/selective matrix PNGs and CSVs, a classification report, candidate comparisons, sealed metrics, the experiment plan, and the inactive candidate head and reference bank. The retained encoder is not duplicated in the bundle."))
    story.append(p("Dataset SHA-256: " + audit["manifest_sha256"], "SmallEG"))
    story.append(p("Candidate head SHA-256: " + sha(RUN/"head.npz"), "SmallEG"))
    story.append(p("Source run: ml/runs/retained-camera-50views-rejects-20261019. Report generated " + now + ".", "SmallEG"))
    def page(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor(INK)); canvas.setFont("Bold", 11)
        canvas.drawString(42, A4[1]-32, "EggGrade IoT")
        canvas.setStrokeColor(colors.HexColor("#cfdbd2")); canvas.line(42,A4[1]-42,A4[0]-42,A4[1]-42)
        canvas.setFont("Body",7.5); canvas.setFillColor(colors.HexColor("#4f6259"))
        canvas.drawString(42,25,"Development validation / appearance labels / not a food-safety assessment")
        canvas.drawRightString(A4[0]-42,25,str(doc.page)); canvas.restoreState()
    doc = SimpleDocTemplate(str(PDF),pagesize=A4,rightMargin=42,leftMargin=42,topMargin=64,bottomMargin=48,
                            title="EggGrade IoT - Model Training Results", author="EggGrade IoT")
    doc.build(story,onFirstPage=page,onLaterPages=page)
    assert len(PdfReader(str(PDF)).pages) == 5
    shutil.copyfile(PDF,OUT/PDF.name)
    for name in ("metrics.json","candidates.json","experiment-plan.json","selection-lock.json","config.json"):
        shutil.copyfile(RUN/name,OUT/name)
    shutil.copyfile(dataset/"audit.json",OUT/"dataset-audit.json")
    model = OUT/"inactive-candidate"; model.mkdir(exist_ok=True)
    for name in ("head.npz","training-references.npz","gate-policy.json"):
        shutil.copyfile(RUN/name,model/name)
    (OUT/"README.txt").write_text("EggGrade IoT - Training Results\n\nAll new 90 + 1500 + 150 photos are included in the 3831-row dataset.\nThe retrained candidate failed validation and was NOT activated.\nThe 176 scan groups are correlated observations from 11 validation eggs.\nReject labels are vendor reports without confirmed reasons. No 99% claim.\n\nThe inactive-candidate head requires the existing retained ONNX encoder; it is not a standalone full model.\nRead the PDF and metrics.json before using the artifacts.\nThe bundle does not include raw egg photographs, credentials, accounts, or runtime databases.\n")
    files = {p.relative_to(OUT).as_posix():sha(p) for p in OUT.rglob("*") if p.is_file() and p.name!="bundle-manifest.json"}
    (OUT/"bundle-manifest.json").write_text(json.dumps(files,indent=2)+"\n")
    archive = OUT.with_suffix(".zip")
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as bundle:
        for path in OUT.rglob("*"):
            if path.is_file(): bundle.write(path,path.relative_to(OUT).as_posix())
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        for name,digest in files.items(): assert hashlib.sha256(bundle.read(name)).hexdigest()==digest
    print(json.dumps({"pdf":str(PDF),"pages":5,"zip":str(archive),"files":len(files)+1,"dataset_rows":3831}))


if __name__ == "__main__":
    main()
