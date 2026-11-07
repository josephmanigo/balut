"""Publish measured study progress, epoch plots and evidence-bound panel answers."""
import argparse
from collections import Counter
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import shutil


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else None


def metric_table(metrics, show_decisions=False):
    if not metrics:
        return '<p class="pending">Not measured yet. No score is claimed.</p>'
    headings = '<tr><th>Class</th><th>Images</th><th>TP</th><th>FP</th><th>FN</th><th>Precision</th><th>Recall</th><th>F1</th></tr>'
    rows = []
    for label, value in zip(["Day 16", "Day 18", "Reject"], metrics["per_class"], strict=True):
        cells = [label, value["support"], value["TP"], value["FP"], value["FN"],
                 *[f'{value[key]:.4f}' for key in ("precision", "recall", "f1")]]
        rows.append('<tr>' + ''.join('<td>' + escape(str(cell)) + '</td>' for cell in cells) + '</tr>')
    summary = ' · '.join(f'{name}: {metrics[key]:.4f}' for name, key in [("Accuracy", "raw_accuracy"), ("Macro F1", "macro_f1"),
                           ("Balanced accuracy", "balanced_accuracy"), ("Weighted F1", "weighted_f1")])
    matrix = metrics["raw_confusion_matrix"]
    confusion = '<tr><th>Actual / predicted</th><th>Day 16</th><th>Day 18</th><th>Reject</th></tr>'
    for label, values in zip(["Day 16", "Day 18", "Reject"], matrix, strict=True):
        confusion += '<tr><th>' + label + '</th>' + ''.join(f'<td>{int(value)}</td>' for value in values) + '</tr>'
    decisions = ''
    if show_decisions:
        accepted_accuracy = f'{metrics["accepted_accuracy"]:.2%}' if metrics["accepted_accuracy"] is not None else 'undefined (none classified)'
        decisions = (f'<p>After scanner decision rules: {metrics["accepted"]} / {metrics["evaluated"]} images classified '
                     f'({metrics["coverage"]:.2%} coverage); {metrics["recaptures"]} unclassified; '
                     f'{metrics["wrong_accepted"]} wrong classified. Accuracy among classified images: {accepted_accuracy}. '
                     f'Correct classified / all images: {metrics["correct_over_all"]:.2%}.</p>')
        decisions += '<table><tr><th>Actual / scanner result</th><th>Day 16</th><th>Day 18</th><th>Reject</th><th>Unclassified</th></tr>'
        for label, values in zip(["Day 16", "Day 18", "Reject"], metrics["selective_confusion_matrix"], strict=True):
            decisions += '<tr><th>' + label + '</th>' + ''.join(f'<td>{int(value)}</td>' for value in values) + '</tr>'
        decisions += '</table>'
    return ('<p><strong>' + summary + '</strong></p><div class="scroll"><table>' + headings + ''.join(rows)
            + '</table><p>Raw confusion matrix: every evaluated image included.</p><table>' + confusion + '</table>' + decisions + '</div>')


def build(dataset, run, output):
    output.mkdir(parents=True, exist_ok=True)
    plan = read(dataset / "collection-plan.json")
    completed = [read(path) for path in sorted((dataset / "captures").glob("*/*/record.json"))]
    completed = [r for r in completed if r["status"] == "complete"]
    if len({r["egg_id"] for r in completed}) != len(completed):
        raise ValueError("Duplicate physical egg captures must be resolved before reporting")
    counts = Counter()
    for record in completed:
        counts[record["source_label"]] += len(record["views"])
    reject = read(dataset / "reject/audit.json")
    metrics = read(run / "metrics.json")
    export = read(run / "calibration/verification.json")
    validation_decisions = read(run / "calibration/validation-outcomes.json")
    test = read(run / "test/metrics.json")
    repeat = read(run / "repeatability/metrics.json")
    study_stage = 'Controlled training and test study complete; this MobileNetV2 candidate has not been promoted.' if test else 'Collection and development study in progress.'
    history = [json.loads(line) for line in (run / "history.jsonl").read_text().splitlines()] if (run / "history.jsonl").exists() else []
    status = {"generated_at": datetime.now(timezone.utc).isoformat(), "age_images_saved": dict(counts),
              "age_eggs_saved": len(completed), "target_age_images": plan["requested_age_images"],
              "reject": reject, "dataset_audit": read(dataset / "audit.json"), "training": metrics, "serving_verification": export, "test": test, "physical_repeatability": repeat,
              "epochs_recorded": len(history), "field_accuracy_established": False,
              "operational_use_authorized": False}
    (output / "study-evidence.json").write_text(json.dumps(status, indent=2, allow_nan=False) + '\n')
    charts = '<p class="pending">Epoch chart pending real training measurements. No example curve or invented score is shown.</p>'
    repeated_scans = '<p class="pending">Fresh physical-repeat scans have not been measured.</p>'
    if repeat:
        repeated_scans = '<p>Fresh acquisitions on the same identified eggs, using the local locked model. These are correlated attempts, not additional independent eggs or a deployed-browser field test.</p>'
        repeated_scans += '<div class="scroll"><table><tr><th>Egg / truth</th><th>Attempts</th><th>Correct</th><th>Wrong</th><th>Unclassified</th><th>Acquisition failures</th></tr>'
        for value in repeat['per_egg']:
            uncertain = value['class_counts'].get('UNCLASSIFIED', 0)
            wrong = value['valid'] - uncertain - value['correct_attempts']
            repeated_scans += (f'<tr><th>{escape(value["egg_id"])} / {escape(value["truth"])}</th>'
                               f'<td>{value["attempts"]}</td><td>{value["correct_attempts"]}</td><td>{wrong}</td>'
                               f'<td>{uncertain}</td><td>{value["failures"]}</td></tr>')
        repeated_scans += '</table></div>'
        if any(r['correct_attempts'] != r['expected_repeats'] or not r['strict_zero_gap_passed'] for r in repeat['per_egg']):
            repeated_scans += '<p class="pending"><strong>This candidate failed the repeated-scan requirement.</strong> Wrong or unclassified outcomes and numerical score changes remain. High development accuracy does not override this result.</p>'
    serving = '<p class="pending">Export verification and scanner calibration are not complete.</p>'
    if export and validation_decisions:
        serving = (f'<p>CPU PyTorch and exported ONNX class predictions agree for all {export["development_images_verified"]:,} development images. '
                   f'Maximum score difference: {export["cpu_pytorch_onnx_max_score_difference"]:.8g}. '
                   'Training epoch logs used GPU arithmetic; the scanner uses CPU float32. '
                   f'GPU versus CPU raw predictions differ on {export["gpu_cpu_raw_prediction_changes"]} development images. '
                   f'CPU validation accuracy: {export["serving_validation"]["raw_accuracy"]:.2%}; '
                   f'macro F1: {export["serving_validation"]["macro_f1"]:.2%}.</p>')
        serving += '<div class="scroll"><table><tr><th>Validation truth</th><th>Images</th><th>Correct classified</th><th>Wrong classified</th><th>Unclassified</th></tr>'
        for label in ("DAY_16", "DAY_18", "REJECT"):
            decisions = [r for r in validation_decisions if r["truth"] == label]
            correct = sum(r["sourcePrediction"] == label for r in decisions)
            wrong = sum(r["sourcePrediction"] is not None and r["sourcePrediction"] != label for r in decisions)
            serving += f'<tr><th>{label}</th><td>{len(decisions)}</td><td>{correct}</td><td>{wrong}</td><td>{len(decisions) - correct - wrong}</td></tr>'
        serving += '</table></div><p>These validation decisions were used for calibration. They are development results, not an independent final test.</p>'
    pilot = ''
    if test and test.get("controlled_age_pilot"):
        value = test["controlled_age_pilot"]
        bounds = value["interval"]
        raw, selective = test['overall']['raw_confusion_matrix'], test['overall']['selective_confusion_matrix']
        age_total = sum(sum(row) for row in raw[:2])
        age_raw_correct = raw[0][0] + raw[1][1]
        age_correct = selective[0][0] + selective[1][1]
        age_unclassified = selective[0][3] + selective[1][3]
        pilot = (f'<h3>Age images only: public Reject excluded</h3><p>Raw correct: {age_raw_correct} / {age_total} '
                 f'({age_raw_correct / age_total:.2%}). After scanner rules: {age_correct} correct, '
                 f'{age_total - age_correct - age_unclassified} wrong classified, {age_unclassified} unclassified. '
                 'These images are correlated views of six eggs.</p>'
                 f'<h3>Reserved age-egg pilot</h3><p>Replay of the first three frames per reserved egg, not a deployed-browser field test. '
                 f'Correct classified eggs on the first group: {value["first_attempt_correct"]} / {value["total"]}. '
                 f'95% Wilson interval: {bounds["lower"]:.1%}–{bounds["upper"]:.1%}. '
                 'This interval ignores unknown batch dependence. The 600 age images represent only six eggs.</p>'
                 f'<p>Classified image coverage: {test["overall"]["coverage"]:.1%}; unclassified: {test["overall"]["recaptures"]}; '
                 f'wrong classified: {test["overall"]["wrong_accepted"]}. Public Reject results do not establish physical EMEET Reject accuracy.</p>')
        pilot += '<table><tr><th>Reserved egg</th><th>Confirmed age label</th><th>First three-frame result</th></tr>'
        for egg in value['eggs']:
            pilot += (f'<tr><td>{escape(egg["egg_id"])}</td><td>{escape(egg["truth"])}</td>'
                      f'<td>{escape(egg["attempts"][0]["sourcePrediction"] or "UNCLASSIFIED")}</td></tr>')
        pilot += '</table>'
    if history and (run / "epoch-curves.png").exists():
        shutil.copy2(run / "epoch-curves.png", output / "epoch-curves.png")
        charts = '<img src="epoch-curves.png" alt="Measured training and validation loss, accuracy, precision, recall, F1 and balanced accuracy by epoch">'
    downloads = []
    for filename, title in [("experiment-plan.json", "Exact training recipe"), ("history.jsonl", "Every measured epoch")]:
        if (run / filename).exists():
            shutil.copy2(run / filename, output / filename)
            downloads.append(f'<a href="{filename}">{title}</a>')
    epoch_answer = (f'Training completed {metrics["epochs_completed"]} epochs. The selected checkpoint is epoch {metrics["selected_epoch"]}. '
                    f'The recorded stop reason is {metrics["stop_reason"]}. '
                    'The recipe allows at most 50 epochs. Eight epochs without a validation macro-F1 improvement greater than 0.001 trigger early stopping after warmup. '
                    'An equal-F1 checkpoint with lower validation loss can replace the saved checkpoint without resetting patience. '
                    'The restored checkpoint can therefore precede the final completed epoch. The test set did not select the checkpoint.' if metrics else
                    'The new MobileNetV2 run has not completed. The prepared recipe allows at most 50 epochs, with three head-only warmup epochs. '
                    'Thereafter the last five feature blocks and classifier can learn. Early stopping uses eight stale validation epochs and a macro-F1 improvement greater than 0.001. '
                    'An equal-F1 checkpoint with lower validation loss can replace the saved checkpoint without resetting patience. The final report must name the actual selected epoch and stop reason.')
    training_answer = ('The new run uses' if metrics else 'The prepared training code uses') + (' ImageNet-pretrained MobileNetV2 with a three-class output. '
                    'New EMEET age images replace old age data. The retained third class combines source Reject and Unfertilized annotations, preserving their provenance. '
                    'Images are resized to 224×224 and normalized. AdamW optimizes weighted cross-entropy in genuine minibatch epochs. '
                    'The recipe uses seed 42, batch size 32, classifier learning rate 0.0003, encoder learning rate 0.00001 and weight decay 0.0001. '
                    'The first three epochs train the classifier; later epochs also tune the final five feature blocks while batch-normalization statistics remain fixed. '
                    'Only training images receive mild geometric and brightness augmentation. A complete clean pass measures training and validation metrics after each epoch. '
                    'Each egg/source family receives equal total weight within its class, and each class receives equal total training weight.')
    computation = 'No measured count example is available until training completes. '
    if metrics:
        value = metrics['validation']['per_class'][0]
        tp, fp, fn = value['TP'], value['FP'], value['FN']
        computation = (f'Actual selected-checkpoint Day 16 validation counts are TP={tp}, FP={fp}, FN={fn}. '
                       f'Precision = {tp}/{tp + fp} = {value["precision"]:.4f}; '
                       f'recall = {tp}/{tp + fn} = {value["recall"]:.4f}; '
                       f'F1 = {2 * tp}/{2 * tp + fp + fn} = {value["f1"]:.4f}. ')
    repeat_answer = 'No new-model physical-repeatability result is available yet; exact zero-gap consistency is not demonstrated.'
    if repeat:
        repeat_answer = ' '.join(
            f'{r["egg_id"]}: {r["correct_attempts"]}/{r["attempts"]} attempts correct, {r["failures"]} failures; '
            f'class agreement={r["class_agreement"]}, decision agreement={r["decision_agreement"]}, '
            f'maximum score difference={r["maximum_score_difference"]}; strict zero-gap passed={r["strict_zero_gap_passed"]}. '
            f'Scope: {r["scope"]}.' for r in repeat['per_egg'])
    questions = [
        ('How did you train the model?', training_answer),
        ('Why is the split like that?', 'Age images use a 60/20/20 physical-egg split: Day 16 has 12/4/4 eggs and Day 18 has 6/2/2 eggs. '
         'At 75 frames per Day 16 egg and 150 per Day 18 egg, each age class has 900/300/300 images. '
         'Training fits weights; validation selects epochs and calibrates thresholds; test stays closed until the candidate is fixed. '
         'With only ten Day 18 eggs, this keeps two separate validation and two separate test eggs. It is a practical pilot split, not a guarantee of generalization. '
         'Retained Reject keeps its previous audited source-family split: 3,033 training, 570 validation and 211 historical public test images. '
         'It is intentionally not described as an exact 60/20/20 split of the entire dataset.'),
        ('Where are precision, recall, F1 and the other metrics?', 'The tables above show per-class support, TP, FP, FN, precision, recall and F1 when measured. '
         'Overall accuracy, balanced accuracy, macro F1 and weighted F1 accompany them. Training and validation curves come from actual epoch logs. '
         'The test result must identify its independent age-egg count and historical Reject source scope. Unclassified scans and failures are reported separately; they are never silently removed.'),
        ('How are those values computed?', 'For each class, TP means correct predictions of that class, FP means other classes predicted as it, and FN means its true examples predicted otherwise. '
         'Precision = TP/(TP+FP); recall = TP/(TP+FN); F1 = 2TP/(2TP+FP+FN). Accuracy = sum of the confusion-matrix diagonal / all evaluated examples. '
         'Macro F1 is the arithmetic mean of the three class F1 scores; weighted F1 weights each class by its true support. Balanced accuracy is mean class recall. '
         + computation +
         'Coverage = classified/all attempts; accepted accuracy = correct/classified; correct-over-all = correct/all attempts. Zero-denominator class metrics use 0; accepted accuracy is undefined when none are classified.'),
        ('Did you scan the same egg many times? Was it consistent?', 'Training recordings contain many correlated views of each egg. This does not establish repeated live-scan consistency. '
         'A separate locked-model test must repeat fresh scans of the same identified egg, recording class agreement, classified/unclassified agreement, score spread, failures and elapsed time. '
         'Replaying an identical saved image tests software determinism only. Consistency can still be consistently wrong, so accuracy is measured separately. '
         + repeat_answer),
        ('Why confuse Day 16 and Day 18? What is the difference?', 'The nominal difference between the age labels is 48 hours of incubation; exact entry timestamps were not supplied. These are nearby developmental stages with overlapping visual appearance. '
         'As embryos develop, their shadows occupy more of the egg and transmitted light changes, but a fixed darkness cutoff cannot determine exact age across eggs. '
         'Shell properties, orientation, lighting and individual development can obscure the distinction. Some actual EMEET recordings are very dark, which can hide useful detail. '
         'The model estimates resemblance to labeled examples; incubation records establish age. We do not claim that the CNN directly measures a specific anatomical milestone or confirms viability. '
         'Metzer Farms documents progressive duck-egg candling appearance; that reference is background context, not validation of this classifier.'),
        ('Where did the epochs stop, and why?', epoch_answer),
        ('Is there data leakage?', 'The workflow keeps every frame of a known egg in one split, preserves Reject source families, checks byte and pixel identities across labels/partitions, '
         'applies augmentation only after splitting, and keeps test images out of fitting, epoch selection and calibration. '
         'These checks prevent known overlap. They cannot prove complete independence: public Reject physical egg/batch IDs are unknown, and the new age eggs lack documented batch IDs. '
         'Camera domain is also confounded with the Reject label: all new age images use EMEET, while Reject images come from a public source. The CNN may learn camera/background differences. '
         'Backgrounds remain visible in the age images; background and lighting shortcuts have not been ruled out. '
         'Validation was used for both checkpoint selection and decision-threshold calibration, so its results are development measurements, not an unbiased final estimate. '
         'All image-level metrics disclose correlated views. A test result after inspecting or tuning on that same test must be labeled exploratory, not independent.'),
        ('Which CNN model did you use?', 'This new study specifies MobileNetV2, matching Objective 1. It uses inverted residual blocks, depthwise convolutions and linear bottlenecks. '
         + ('The completed run’s architecture is MobileNetV2.' if metrics else f'Training is in progress ({len(history)} complete epochs).' if history else 'Its implementation and pretrained weights are prepared; training is pending collection.')
         + ' The existing deployed release is a separate DINOv2/EfficientNet model until a tested MobileNetV2 release is explicitly promoted. '
         'The ESP32 controls the holder/display; CNN inference runs on the computer/server. Do not claim that MobileNetV2 currently executes on the ESP32.'),
        ('What is the field-testing accuracy?', 'FIELD ACCURACY NOT YET ESTABLISHED. The six reserved age eggs provide a small controlled pilot test after locking the model. '
         'The public Reject test is not a physical EMEET Reject test. A defensible field result needs new independently labeled eggs, confirmed Reject cases, documented farms/batches and conditions, '
         'first-attempt outcomes including failures, response times and repeatability. Report a confusion matrix, per-class metrics and uncertainty at the egg/batch level. '
         'A large number of frames from a few eggs does not create a large independent field study.')]
    answers = ''.join(f'<details open><summary>{i}. {escape(q)}</summary><p>{escape(a)}</p></details>' for i, (q, a) in enumerate(questions, 1))
    source_links = [('MobileNetV2 paper', 'https://arxiv.org/abs/1801.04381'),
                    ('Torchvision MobileNetV2 weights', 'https://docs.pytorch.org/vision/main/models/generated/torchvision.models.mobilenet_v2.html'),
                    ('Retained Reject source: Pat Balut Eggs v8', 'https://universe.roboflow.com/pat-bteu2/balut-eggs-project-unfertilized-fertilized-and-reject-tgibj/dataset/8'),
                    ('Source dataset license: CC BY 4.0', 'https://creativecommons.org/licenses/by/4.0/'),
                    ('Classification metrics', 'https://scikit-learn.org/stable/modules/generated/sklearn.metrics.classification_report.html'),
                    ('Duck egg candling reference', 'https://www.metzerfarms.com/candling-pictures.html'),
                    ('ISO/IEC 25010:2011 (withdrawn)', 'https://www.iso.org/standard/35733.html'),
                    ('ISO/IEC 25010:2023', 'https://www.iso.org/standard/78176.html')]
    html = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EggGrade · MobileNetV2 study evidence</title><style>
body{{font:16px/1.65 system-ui,sans-serif;color:#18332c;background:#f5f6f1;max-width:1100px;margin:36px auto;padding:0 24px}}h1,h2{{line-height:1.2}}h1{{font-size:36px}}section,details{{background:white;border:1px solid #d8e0d9;border-radius:10px;padding:22px;margin:18px 0}}summary{{font-weight:700;cursor:pointer}}table{{border-collapse:collapse;width:100%}}th,td{{text-align:left;padding:10px;border-bottom:1px solid #dae3dc}}.scroll{{overflow:auto}}.pending{{color:#7d461a;background:#fff5df;padding:14px}}img{{max-width:100%}}a{{color:#176150}}code{{overflow-wrap:anywhere}}@media print{{body{{margin:0;background:white}}details,section{{break-inside:avoid}}}}
</style><h1>EggGrade · MobileNetV2 study evidence</h1>
<p>Generated {escape(status['generated_at'])}. {study_stage} No field-accuracy or food-safety guarantee.</p>
<section><h2>New dataset progress</h2><p><strong>{sum(counts.values()):,} / 3,000 age images saved from {len(completed)} physical eggs.</strong></p>
<table><tr><th>Class</th><th>Saved / target</th><th>Planned unique eggs</th></tr><tr><td>Day 16</td><td>{counts['DAY_16']} / 1,500</td><td>20</td></tr><tr><td>Day 18</td><td>{counts['DAY_18']} / 1,500</td><td>10</td></tr><tr><td>Retained Reject</td><td>{reject['images'] if reject else 0}</td><td>Unknown public-source identities; 0 confirmed physical Reject eggs</td></tr></table>
<p>The new age images are real EMEET camera frames. Repeated views and augmented inputs are not new independent eggs. All old age datasets are excluded from this study. Retained Reject images are source-derived public crops, not new EMEET captures or 3,814 independent eggs. Their original Reject/Unfertilized annotations and image-family partitions are preserved; both annotations map to the requested Reject output. Attribution: Pat, Balut Eggs Project v8, CC BY 4.0 according to the archived source license.</p></section>
<section><h2>Alignment with the four objectives</h2><ol>
<li><strong>AIoT and MobileNetV2:</strong> EMEET supplies images; ESP32 controls rotation/display; the new CNN runs on the computer/server. Physical hardware deployment must be verified separately.</li>
<li><strong>Labeled data and classification:</strong> new Day 16/18 collection, retained Reject annotations, fixed groups, epoch records and visible metrics. Confirmed dead/spoiled EMEET samples remain missing.</li>
<li><strong>Decision rule and holder:</strong> current software combines three views; at least two distinct accepted views must agree, with no conflicting accepted class. The rotating holder and display support scanning. Automatic routing into separate physical bins is not demonstrated by the spinner firmware.</li>
<li><strong>System-quality and field evaluation:</strong> the accompanying blank evaluation instrument covers the four qualities named in the objectives. No evaluator responses or field result are invented. The objectives use 2011-era ISO terminology; record the adviser-approved edition because ISO/IEC 25010:2011 is withdrawn and 2023 is the current product model.</li></ol></section>
<section><h2>Training and validation by epoch</h2>{charts}<p>Epoch curves and checkpoint tables record the actual GPU training measurements. CPU serving verification is reported separately.</p><p>{' · '.join(downloads)}</p><h3>Selected checkpoint: training</h3>{metric_table(metrics['train'] if metrics else None)}<h3>Selected checkpoint: validation</h3>{metric_table(metrics['validation'] if metrics else None)}
<h3>Export and scanner checks</h3>{serving}
<h3>Locked held-out test</h3>{metric_table(test['overall'] if test and 'overall' in test else None, show_decisions=True)}{pilot}</section>
<section><h2>Fresh repeated scans</h2>{repeated_scans}</section>
<h2>Panel questions: evidence-bound answers</h2>{answers}
<section><h2>Sources and data</h2><p>{' · '.join(f'<a href="{url}">{title}</a>' for title, url in source_links)}</p><p><a href="study-evidence.json">Machine-readable study evidence</a> · <a href="evaluation-instrument.html">Blank system-quality evaluation instrument</a></p></section></html>'''
    (output / "index.html").write_text(html, encoding="utf-8")
    instrument = '''<!doctype html><html lang="en"><meta charset="utf-8"><title>EggGrade evaluation instrument — blank draft</title><style>body{font:17px/1.6 system-ui;max-width:900px;margin:40px auto;padding:20px}table{border-collapse:collapse}td,th{border:1px solid #aaa;padding:10px}h2{margin-top:32px}</style>
<h1>System-quality evaluation instrument</h1><p>Blank draft for adviser review. No participant responses have been collected by this form. Study-specific items informed by the four qualities in the objectives; not an ISO certification or a reproduced standardized questionnaire.</p>
<p>Participant code: ______ Role (vendor / poultry farmer / technical evaluator): ______ Date: ______<br>Build/model release: ______ Camera: ______ Batch/setting: ______ ISO edition used by the study: ______</p>
<h2>Observed tasks</h2><ol><li>Connect the EMEET camera and scan an independently labeled egg.</li><li>Read the displayed class or unclassified result and locate its history.</li><li>Repeat a scan, then recover from a disconnected camera.</li><li>Observe the rotating holder and verify that the result matches the intended egg.</li></ol>
<p>Rate each item: 1 strongly disagree, 2 disagree, 3 neutral, 4 agree, 5 strongly agree; N/O if not observed. Record the task evidence beside the rating.</p>
<table><tr><th>Quality</th><th>Study item</th><th>Rating</th><th>Evidence/comment</th></tr>
<tr><td>Functional suitability</td><td>The system captures the intended egg and presents the required class or a clear unclassified result.</td><td>___</td><td>___</td></tr>
<tr><td>Functional suitability</td><td>The displayed result and stored history refer to the correct scan.</td><td>___</td><td>___</td></tr>
<tr><td>Performance efficiency</td><td>Time from scan start to result is acceptable for the observed workflow.</td><td>___</td><td>___</td></tr>
<tr><td>Performance efficiency</td><td>The preview and controls remain responsive during analysis.</td><td>___</td><td>___</td></tr>
<tr><td>Usability</td><td>I can connect, start a scan and understand its result without assistance.</td><td>___</td><td>___</td></tr>
<tr><td>Usability</td><td>Instructions explain how to recover from an unclear scan or camera error.</td><td>___</td><td>___</td></tr>
<tr><td>Reliability</td><td>The system completes the observed scans without crashes or missing records.</td><td>___</td><td>___</td></tr>
<tr><td>Reliability</td><td>The system recovers from interruption without showing a stale result for a different egg.</td><td>___</td><td>___</td></tr></table>
<h2>Measured observations</h2><p>Tasks attempted/completed: ___ / ___ · Scans attempted/completed: ___ / ___<br>First-attempt correct / all attempted: ___ / ___ · Unclassified: ___ · Failures: ___<br>Scan latency seconds, all attempts: __________________ · Repeated-egg disagreement count: ___</p>
<p>Report response counts and missing/N/O counts. Show rating distributions and median per item; a mean, if required by the approved study, equals the sum of numeric ratings divided by the number of nonmissing ratings. Never replace missing responses with 0 or 5. Report vendors, farmers and technical evaluators separately before any combined summary. These opinions do not substitute for independent classification accuracy.</p></html>'''
    (output / "evaluation-instrument.html").write_text(instrument, encoding="utf-8")
    return status


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path); parser.add_argument("run", type=Path); parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = build(args.dataset, args.run, args.output)
    print(json.dumps({"age_images_saved": result["age_images_saved"], "age_eggs_saved": result["age_eggs_saved"], "epochs_recorded": result["epochs_recorded"], "report": str(args.output / "index.html")}))
