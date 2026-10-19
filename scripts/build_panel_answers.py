"""Create a ten-question panel answer PDF for the active EggGrade IoT model."""
from build_easy_defense import (
    ROOT, read, pct, sha, verify, np, PdfReader, colors, A4, ParagraphStyle,
    Paragraph, Table, TableStyle, Spacer, PageBreak, SimpleDocTemplate,
)
from xml.sax.saxutils import escape
import json

PDF = ROOT / "output/pdf/EggGrade-IoT-Panel-Answers-20261019.pdf"
PACKET = ROOT / "output/model-results/EggGrade-IoT-Scientific-Defense-20261019"
EVIDENCE = ROOT / "docs/reports/20261019/model-evidence.json"
INK, ACCENT = "#19364a", "#126c94"


def main():
    evidence = read(EVIDENCE)
    verify(evidence)
    metrics = evidence["baseline"]
    fit = read(ROOT / "output/scientific-audit-20261019/classifier-fit-script-verification.json")
    repeats = read(PACKET / "repeatability-results.json")["cases"]
    assert len(repeats) == 9 and all(row["attempts"] == 10 for row in repeats)
    assert all(row["class_agreement"] == row["decision_agreement"] == 1 for row in repeats)
    assert all(row["maximum_score_difference"] == 0 and row["failures"] == 0 for row in repeats)
    assert fit["reproduced_iterations"] == [38] and fit["converged_before_limit"]
    assert fit["float32_parameter_maximum_differences"] == {"coefficient": 0.0, "intercept": 0.0}
    assert sum([2256, 814, 649]) == 3719
    assert evidence["active_catalog"]["releaseId"] == "unfertilized-trial-20261019"

    body = ParagraphStyle("Body", fontName="Helvetica", fontSize=12, leading=17, spaceAfter=10, textColor=colors.HexColor(INK))
    title = ParagraphStyle("Title", parent=body, fontName="Helvetica-Bold", fontSize=22, leading=26, spaceAfter=14)
    heading = ParagraphStyle("Heading", parent=body, fontName="Helvetica-Bold", fontSize=13, leading=18, spaceBefore=8, spaceAfter=7)
    small = ParagraphStyle("Small", parent=body, fontSize=9.5, leading=13, spaceAfter=7)
    cell = ParagraphStyle("Cell", parent=body, fontSize=10.5, leading=14, spaceAfter=0)
    spoken = ParagraphStyle("Spoken", parent=body, backColor=colors.HexColor("#eaf4f8"), borderPadding=10, spaceBefore=4, spaceAfter=16)
    story = []

    def p(text, style=body):
        story.append(Paragraph(escape(text).replace("\n", "<br/>"), style))

    def question(number, text, answer):
        if story:
            story.append(PageBreak())
        p(f"EGGGRADE IoT  |  PANEL QUESTION {number} OF 10", small)
        p(text, title)
        p("SHORT ANSWER TO SAY", heading)
        p(answer, spoken)

    def table(rows, widths, matrix=False):
        values = [[Paragraph(escape(str(value)).replace("\n", "<br/>"), cell) for value in row] for row in rows]
        item = Table(values, colWidths=widths, repeatRows=1, hAlign="LEFT")
        commands = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dceaf1")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f6f8")]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]
        if matrix:
            commands += [("BACKGROUND", (i, i), (i, i), colors.HexColor("#c3e4ec")) for i in range(1, 4)]
        item.setStyle(TableStyle(commands))
        story.extend([item, Spacer(1, 10)])

    def note(text):
        p("WHAT THIS EVIDENCE DOES NOT SHOW", heading)
        p(text)

    def source(text):
        p("Evidence: " + text, small)

    question(1, "How did you train the model?",
             "We used pretrained image models to extract visual features, then trained a classifier to recognize Day 16, Day 18 and Reject. We kept every view of the same known egg in one data split.")
    table([["Step", "What we did"],
           ["1. Prepare the dataset", "3,719 images: 1,620 camera views of 30 eggs, plus 2,099 public images."],
           ["2. Keep related views together", "Group images by physical egg ID or recorded public image family before splitting."],
           ["3. Prepare each image", "Convert to RGB, resize to 224 x 224, and normalize using ImageNet statistics."],
           ["4. Extract features", "Use frozen DINOv2 and EfficientNet-B0. Average original and horizontally flipped image features."],
           ["5. Fit and select settings", "Fit logistic regression on 2,256 training images. Use 814 validation images to choose weighting and recapture thresholds."]], [135, 364])
    p("Your 1,590 photos are included: 90 three-view photos plus 1,500 rotation photos. The other 30 camera images are earlier views of those same eggs.")
    p("Training settings: C = 100; seed = 42; maximum 3,000 L-BFGS iterations. Per-egg weight = 20, shared across its views before class balancing.", small)
    p("Reject is the app name for the public Unfertilized source class. R1, R2 and R3 are excluded. Age labels were reported from the farm; independent incubation records were not supplied.", small)
    source("train_unfertilized.py; training experiment-plan.json and selection-lock.json; dataset manifest. Model: unfertilized-trial-20261019.")

    question(2, "Why did you choose this data split?",
             "The split protects against testing on another view of an egg already used for training. We split related eggs and source families together. The percentages follow those groups rather than a fixed 80/20 rule.")
    table([["Partition", "Images", "% of all", "D16 / D18 / Reject"],
           ["Training", "2,256", "60.66%", "315 / 327 / 1,614"],
           ["Validation", "814", "21.89%", "286 / 290 / 238"],
           ["Historical test", "649", "17.45%", "285 / 290 / 74"],
           ["Total", "3,719", "100.00%", "886 / 907 / 1,926"]], [110, 90, 90, 209])
    p("Training learns classifier weights. Validation selects settings and thresholds. The historical test measures the model on the reserved image groups.")
    p("Each partition has 10 known physical eggs: five Day 16 and five Day 18. Each egg has 54 saved views. Each partition contains 530 of your newer photos plus 10 earlier photos.")
    p("Public class counts differ because the source datasets have different sizes and group structures. We did not move images between splits just to force a standard percentage.")
    note("Thirty eggs with many photos are still only 30 physical eggs. Public egg identities and farm batches are incomplete. The historical test has already been inspected, so it is not a new independent field test.")
    source("split-counts.csv; dataset-audit/audit.json; manifest with recorded egg and source-family groups.")

    question(3, "Where are F1, recall, precision\nand the other scores?",
             "These are the measured scores for the model used by the app. They come from 649 historical images. We report each class separately and keep recaptures visible.")
    table([["Class", "Images", "Precision", "Recall", "F1"]] +
          [[name, row["support"], pct(row["precision"]), pct(row["recall"]), pct(row["f1"])] for name, row in zip(("Day 16", "Day 18", "Reject*"), metrics["per_class"])], [104, 70, 110, 105, 110])
    table([["Metric", "Measured result"],
           ["Raw / balanced accuracy", "84.75% / 88.55%"],
           ["Macro F1 / weighted F1", "88.50% / 84.72%"],
           ["Accepted accuracy", "95.27%: 423 correct out of 444 accepted"],
           ["Coverage / recapture rate", "68.41% / 31.59%: 444 accepted, 205 recaptures"],
           ["Correct accepted / all inputs", "65.18%: 423 out of 649"]], [217, 282])
    p("Confusion matrix before recapture gates", heading)
    table([["Reference / predicted", "Day 16", "Day 18", "Reject*"]] +
          [[name, *row] for name, row in zip(("Day 16", "Day 18", "Reject*"), metrics["raw_confusion_matrix"])], [200, 100, 100, 99], matrix=True)
    p("Rows are reference labels; columns are predictions. Shaded diagonal cells are correct. Reject* means public Unfertilized labels. Its 74/74 result does not establish 100% field accuracy.", small)
    p("Raw accuracy 95% cluster-bootstrap interval: 72.40%-94.61%. Resampling used 66 recorded egg/source-family clusters and 5,000 draws, seed 42.", small)
    source("baseline-metrics.json; classification-metrics.csv; reproduced historical predictions. Model: unfertilized-trial-20261019.")

    question(4, "How did you compute the metrics?",
             "We counted predictions against reference labels in the confusion matrix. Then we applied the precision, recall, F1 and accuracy formulas. We calculated accepted results and recaptures separately.")
    p("Worked example: Day 16", heading)
    p("TP = 249 correct Day 16 predictions. FP = 63 other-class images called Day 16. FN = 36 Day 16 images called another class. TN = 301 other-class images not called Day 16.", small)
    table([["Metric", "Formula", "Calculation / result"],
           ["Precision", "TP / (TP + FP)", "249 / 312 = 79.81%"],
           ["Recall", "TP / (TP + FN)", "249 / 285 = 87.37%"],
           ["F1", "2TP / (2TP + FP + FN)", "498 / 597 = 83.42%"],
           ["Accuracy", "Correct / all inputs", "(249 + 227 + 74) / 649 = 84.75%"],
           ["Balanced accuracy", "Mean of class recalls", "(87.37% + 78.28% + 100%) / 3 = 88.55%"],
           ["Macro F1", "Mean of class F1 scores", "(83.42% + 82.10% + 100%) / 3 = 88.50%"],
           ["Weighted F1", "Sum(class count x F1) / total", "(285 x 0.83417 + 290 x 0.82098 + 74 x 1) / 649 = 84.72%"],
           ["Accepted accuracy", "Correct accepted / accepted", "423 / 444 = 95.27%"],
           ["Coverage", "Accepted / all inputs", "444 / 649 = 68.41%"],
           ["Recapture rate", "Recaptures / all inputs", "205 / 649 = 31.59%"],
           ["Correct accepted / all", "Correct accepted / all inputs", "423 / 649 = 65.18%"]], [115, 180, 204])
    p("Calculations use unrounded values; displayed percentages are rounded. A zero denominator sets class precision/recall/F1 to 0 and flags missing support. Accepted accuracy is undefined when nothing is accepted.", small)
    source("scientific_metrics.py and test_scientific_metrics.py; actual matrix counts in baseline-metrics.json.")

    question(5, "Did repeated scans of the same egg\ngive consistent results?",
             "Repeated analysis of the exact same saved images gave identical classes, decisions and scores. We have not yet established the same consistency for repeated fresh camera scans of physical eggs.")
    table([["Test detail", "Actual result"],
           ["Saved input bundles", "9 bundles; 3 images per bundle."],
           ["Number of repetitions", "10 fresh analyses per bundle: 90 bundle results and 270 image inferences."],
           ["Predicted-class agreement", "100% within every tested bundle."],
           ["Accept/recapture agreement", "100% within every tested bundle."],
           ["Largest full-score difference", "0.0 across all three class scores for all three views."],
           ["Failed attempts", "0 in this saved-input test."]], [210, 289])
    p("The model was reloaded between repetitions 5 and 6. We compared every score, including scores for classes that did not win.")
    p("Six bundles came from identified Day 16/Day 18 eggs. Three came from public Unfertilized image families; their physical egg identities are unknown.")
    note("Saved images do not change lighting, position or exposure. Fresh camera scans do. Physical scan-to-scan score differences are not measured under the formal repeat protocol, so physical consistency is not established.")
    source("repeatability-results.json; case-level attempts.jsonl and full-precision-scores.npy; check_saved_repeatability.py.")

    question(6, "Why confuse Day 16 and Day 18?\nWhat is different between them?",
             "Day 18 represents two more days of incubation than Day 16. Embryonic development continues, but their candling appearances can overlap. The model recognizes appearance; it does not directly measure elapsed incubation time.")
    table([["Observed error before recapture", "Count"],
           ["Day 16 predicted as Day 18", "36 of 285 Day 16 images"],
           ["Day 18 predicted as Day 16", "63 of 290 Day 18 images"],
           ["Total age confusion", "99 of 575 age-labeled images"]], [315, 184])
    p("What we observed", heading)
    p("Inspected validation examples from both ages show large dark interiors with bright illumination below. These examples pass the configured quality checks but remain ambiguous to the classifier.")
    p("Why the visual difference is difficult", heading)
    p("During normal development, the embryo grows and its structures mature over those two days. Lighting, exposure, shell properties and orientation also change the transmitted-light image. Breed and incubation conditions affect development. These are possible contributors; the audit did not isolate one proven cause.")
    p("Biological evidence", heading)
    p("Trela and colleagues found different developmental timing in Pekin and Mulard ducks. This supports using documented incubation ages instead of assuming one visual cutoff works for every egg.")
    note("An image alone cannot confirm exact incubation age. Our age labels were user-reported; independent incubation records are needed to separate label error from visual ambiguity.")
    source("Validation error review and historical confusion matrix. Trela et al. (2025), Poultry Science 104(8):105132. https://doi.org/10.1016/j.psj.2025.105132")

    question(7, "At what epoch did training stop,\nand why?",
             "The model used by the app has no training epoch number. Its pretrained image encoders are frozen, and its logistic classifier uses L-BFGS solver iterations. Our verified reproduction converged after 38 iterations.")
    table([["Training item", "Verified value"],
           ["Trainable part", "Three-class logistic classifier."],
           ["Frozen parts", "DINOv2 and EfficientNet-B0 image encoders."],
           ["Optimizer", "L-BFGS."],
           ["Maximum allowed iterations", "3,000."],
           ["Reproduced fit", "38 iterations; converged before the limit."],
           ["Stopping tolerance setting", "0.0001 (the estimator's tolerance setting)."],
           ["Parameter reproduction check", "Maximum difference = 0.0 for the stored float32 coefficients and intercepts."]], [214, 285])
    p("Why training stopped", heading)
    p("The reproduced solver reported convergence before the maximum iteration limit. An iteration is an optimizer update step; it is not an epoch over neural-network training batches.")
    p("How to answer a follow-up", heading)
    p("\"We cannot report an epoch checkpoint for this model because that is not how its classifier was trained. We report its actual solver, limit and reproduced convergence count.\"")
    note("The original fit did not save its iteration count. The number 38 belongs to the verified reproduction, not an invented original training log. Epoch learning curves do not apply to this active classifier.")
    source("classifier-fit-script-verification.json; reproduce_retained_classifier_fit.py; LogisticRegression configuration in train_unfertilized.py.")

    question(8, "Was there leakage during training?",
             "We found no recorded cross-split overlaps in the checks we ran. Images of each known egg stayed in one partition. However, missing public egg identities and previous inspection of the test set prevent a claim that all leakage risks are eliminated.")
    table([["Audit check", "Measured finding"],
           ["File integrity", "All 3,719 files match their recorded hashes."],
           ["Exact files and decoded pixels", "0 cross-partition overlaps detected."],
           ["Known egg IDs", "0 cross-partition overlaps; 30 known eggs remain grouped."],
           ["Recorded public source families", "0 cross-partition overlaps detected."],
           ["Near-duplicate check", "0 candidates under the declared similarity rule."],
           ["Preprocessing", "Fixed image normalization and frozen encoders do not fit statistics to the test set."]], [215, 284])
    p("Near-duplicate rule: both a 64-bit dHash distance at most 3 and a 32 x 32 RGB mean difference at most 6/255.", small)
    p("Remaining risks", heading)
    p("Public physical egg IDs are unknown for 2,099 images. Farm batch IDs are missing. Reject images come from public sources, while camera images cover age classes, so source cues may influence classification.")
    p("The historical test was inspected during earlier development. Its reported score must not be presented as a fresh independent confirmation.")
    source("dataset-audit/audit.json; near-duplicate-candidates.json; audit_scientific_dataset.py; stored split assignments.")

    question(9, "Which CNN model did you use?",
             "We used EfficientNet-B0 as the CNN. The complete system is a hybrid: EfficientNet-B0 and the DINOv2 ViT-S/14 transformer extract features, and a trained logistic classifier predicts the three classes.")
    table([["Component", "Purpose", "Output"],
           ["EfficientNet-B0", "Pretrained CNN; frozen weights", "1,280 features"],
           ["DINOv2 ViT-S/14", "Pretrained vision transformer; frozen weights", "384 features"],
           ["Feature fusion", "Normalize and combine both feature vectors", "1,664 features"],
           ["Logistic classifier", "Trained on the egg-image dataset", "3 class scores"],
           ["Decision checks", "Quality, score margin and training-feature similarity", "Grade or recapture"]], [150, 245, 104])
    p("What each part contributes", heading)
    p("The two encoders convert an image into numerical visual features. The classifier learns which combinations are associated with Day 16, Day 18 or the Unfertilized source category.")
    p("Class names in the app", heading)
    p("Day 16, Day 18 and Reject. Internally, Reject maps to UNFERTILIZED. Recapture is a separate outcome when the input does not meet the decision requirements.")
    p("Scores are decision scores, not calibrated probabilities. A Reject output is not proof of food safety, spoilage or sellability.", small)
    source("feature_models.py; active model config and registry; model_service.py. Active release: unfertilized-trial-20261019. Model hash prefix: 479211e3e587.")

    question(10, "What is the field-testing accuracy?",
             "Field-testing accuracy is not yet established. Our measured 84.75% accuracy comes from a historical image evaluation. It is not the result of a new independent study using previously unseen eggs in the live device.")
    table([["Available evidence", "What it establishes"],
           ["649 historical images", "550 correct raw predictions: 84.75%."],
           ["Accepted historical results", "423 correct out of 444 accepted: 95.27%, with 205 recaptures."],
           ["Repeated saved inputs", "Deterministic results for unchanged input bytes in the tested environment."],
           ["New independent field study", "No completed study; field accuracy is not measured."]], [210, 289])
    p("How the field study will measure accuracy", heading)
    p("1. Register 90 new eggs: 30 per class, from at least three batches per class. Record independent labels and incubation dates where applicable.")
    p("2. Use the real device and its three-view workflow. Use the first attempt from each egg for the primary accuracy result.")
    p("3. Keep errors, failed captures and recaptures in the report. Repeated scans remain attached to their egg, not counted as new eggs.")
    p("4. Report per-class precision, recall, F1, coverage and uncertainty. Compare the entire score vector when checking repeated-scan consistency.")
    p("The planned repeat subset uses three eggs per class, ten scans each within ten minutes. This gives 171 planned attempts from 90 unique eggs.", small)
    note("A collection plan is not a completed experiment. We need new independently referenced eggs, including physical Unfertilized eggs, before reporting field accuracy.")
    source("scientific-field-protocol.txt; blank field-registration.csv and collection workbook; collect_scientific_field_scan.py.")

    def footer(canvas, doc):
        canvas.setStrokeColor(colors.HexColor("#c9dae5")); canvas.line(48, 39, A4[0] - 48, 39)
        canvas.setFont("Helvetica", 8); canvas.setFillColor(colors.HexColor(INK))
        canvas.drawString(48, 25, "EggGrade IoT | Panel answers | 19 October 2026")
        canvas.drawRightString(A4[0] - 48, 25, f"{doc.page} / 10")

    PDF.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(PDF), pagesize=A4, leftMargin=48, rightMargin=48, topMargin=40, bottomMargin=52,
                      title="EggGrade IoT - Ten Panel Questions and Answers", author="EggGrade IoT").build(story, onFirstPage=footer, onLaterPages=footer)
    reader = PdfReader(PDF)
    assert len(reader.pages) == 10, f"Unexpected pages: {len(reader.pages)}"
    for index, page in enumerate(reader.pages, 1):
        assert f"PANEL QUESTION {index} OF 10" in page.extract_text()
    text = "\n".join(page.extract_text() for page in reader.pages)
    for value in ("84.75%", "95.27%", "87.37%", "83.42%", "38 iterations", "0.0", "1,590"):
        assert value in text, value
    for forbidden in ("candidate model", "tested candidate", "replacement", "keep the current", "236 configurations", "C:/Users"):
        assert forbidden.lower() not in text.lower(), forbidden
    report = {"pdf": str(PDF), "pages": 10, "sha256": sha(PDF), "question_order_verified": True,
              "metric_counts_and_calculations_verified": True, "comparison_sections_present": False,
              "source_snapshot_sha256": sha(EVIDENCE), "visual_review": "PENDING"}
    (PDF.parent / "EggGrade-IoT-Panel-Answers-20261019.verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
