"""Publish only fresh camera attempts as physical test results."""
import argparse
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.emeet_physical_metrics import load_physical_study


def pct(value):
    return 'Not measured' if value is None else f'{value:.1%}'


def table(headers, rows):
    return '<div class="scroll"><table><thead><tr>' + ''.join(f'<th scope="col">{escape(str(h))}</th>' for h in headers) + '</tr></thead><tbody>' + ''.join(
        '<tr>' + ''.join(f'<td>{escape(str(v))}</td>' for v in row) + '</tr>' for row in rows) + '</tbody></table></div>'


def results(metrics):
    rows = [[v['class'], v['support'], v['TP'], v['FP'], v['FN'], pct(v['precision']), pct(v['recall']), pct(v['f1'])] for v in metrics['per_class']]
    return (f'<p><strong>{metrics["correct"]}/{metrics["attempts"]} correct ({pct(metrics["accuracy"])}).</strong> '
            f'{metrics["wrong_classified"]} wrong, {metrics["unclassified"]} unclassified, {metrics["acquisition_failures"]} acquisition failures. '
            f'{metrics["classified"]}/{metrics["attempts"]} returned a class. Accuracy among those classified: {pct(metrics["accuracy_among_classified"])}.</p>'
            + table(['Known class', 'Attempts', 'TP', 'FP', 'FN', 'Precision', 'Recall', 'F1'], rows)
            + '<p>Confusion counts. Each row is the known class; each column is a scanner outcome.</p>'
            + table(['Known class', 'Day 16', 'Day 18', 'Reject', 'Unclassified', 'Acquisition failure'],
                    [[label, *row] for label, row in zip(metrics['class_order'], metrics['confusion_matrix'], strict=True)])
            + f'<p>Macro F1 across represented classes: {pct(metrics["macro_f1_represented_classes"])}. No physical Reject egg was available.</p>')


def build(dataset, study, output):
    evidence = load_physical_study(study, dataset)
    evidence['generated_at'] = datetime.now(timezone.utc).isoformat()
    output.mkdir(parents=True, exist_ok=True)
    (output / 'physical-test-results.json').write_text(json.dumps(evidence, indent=2, allow_nan=False) + '\n', encoding='utf-8', newline='\n')
    first, repeats = evidence['primary_first_attempt_per_egg'], evidence['repeated_attempts']
    eggs = evidence['per_egg']
    egg_table = table(['Egg / known age', 'First outcome', 'Attempts', 'Correct', 'Wrong', 'Unclassified', 'Failed', 'Median seconds', 'Exact repeat match'],
        [[e['egg_id'], e['first_outcome'], e['attempts'], e['correct_attempts'], e['valid'] - e['correct_attempts'] - e['class_counts'].get('UNCLASSIFIED', 0),
          e['class_counts'].get('UNCLASSIFIED', 0), e['failures'], f'{e["median_attempt_seconds"]:.2f}', 'Yes' if e['strict_zero_gap_passed'] else 'No'] for e in eggs])
    html = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>EggGrade | Physical testing</title>
<style>body{{margin:0;background:#f4f7f6;color:#18312f;font:17px/1.55 system-ui}}main{{max-width:1080px;margin:auto;padding:24px}}h1,h2,h3{{line-height:1.2}}h1{{font-size:2.4rem}}section{{background:#fff;padding:20px;margin:20px 0;border:1px solid #d6dfdb;border-radius:10px}}a{{color:#006251}}.summary{{background:#e7f2ed;border-left:5px solid #337658;padding:16px}}.scroll{{overflow:auto}}table{{border-collapse:collapse;font-size:15px}}th,td{{text-align:left;padding:8px;border-bottom:1px solid #d6dfdb}}details{{margin:14px 0}}summary{{cursor:pointer;font-weight:650}}img{{max-width:100%;height:auto}}@media(max-width:600px){{main{{padding:12px}}section{{padding:12px}}h1{{font-size:1.75rem}}}}</style>
<main><p>EGGGRADE · EMEET · CONTROLLED PHYSICAL TEST</p><h1>Testing with physical duck eggs</h1>
<div class="summary"><strong>First scan: {first['correct']} of {first['attempts']} eggs correct ({pct(first['accuracy'])}).</strong><br>
All repeated scans: {repeats['correct']} of {repeats['attempts']} correct ({pct(repeats['accuracy'])}). Repeated scans of the same egg are correlated.</div>
<p>{evidence['completed_eggs']} of {evidence['planned_eggs']} reserved eggs completed ten fresh camera acquisitions. The test uses the EMEET webcam, the local locked MobileNetV2 candidate and the scanner’s three-view decision rule. No saved dataset images or synthetic examples enter these test counts.</p>
<section><h2>Primary result: one first scan per egg</h2>{results(first)}</section>
<section><h2>Repeated scans: consistency and errors</h2>{egg_table}{results(repeats)}
<p>Exact repeat match requires the same class, decision and all full-precision scores on every expected attempt. Median seconds include camera acquisition and local analysis.</p></section>
<section><h2>How the physical test was done</h2><p>The operator identified each egg against the original incubation labels. Each attempt reopened the EMEET camera, discarded two warmup frames and analyzed three fresh views. At least two distinct accepted views had to agree, with no conflicting accepted class. Every attempted scan counts, including wrong grades, unclassified outcomes and acquisition failures.</p>
<p>Two sessions (D16-17 and D18-09) were acquired in the original physical trial. Their records are included once and preserved unchanged. The expanded protocol was set after those results were known. The remaining sessions use the same candidate and procedure. The eggs were reserved from weight fitting; they are the same previously examined cohort, not a new independent sample.</p>
<p>A monitor was visible behind the holder, and its displayed content changed during some scans. The egg remained visible in the reviewed views. We did not isolate the effect of the background, illumination or rotation angle. These local camera measurements do not test a deployed browser, automatic bin sorting, or a production site. <strong>Field accuracy has not been established.</strong></p></section>
<section><h2>Training and validation</h2><p>The original dataset contains 1,500 Day 16 and 1,500 Day 18 EMEET frames from 30 physical eggs, plus the retained historical Reject data. The chart below describes training and validation only.</p>
<img loading="lazy" src="/assets/study-20261107-v2/full-epochs.png" alt="Original MobileNetV2 training and validation metrics by epoch">
<p><a href="/assets/study-20261107-v2/full-history.jsonl">Download epoch measurements</a> · <a href="/assets/study-20261107-v2/index.html">Archived model comparison and offline analysis</a></p></section>
<section><h2>Panel answers</h2>
<details><summary>1. How did you train the model?</summary><p>We used ImageNet-pretrained MobileNetV2, trained the classifier head for three epochs, then fine-tuned the last five encoder blocks with AdamW. Only training images received augmentation. Class totals were balanced, and repeated views shared their egg’s training weight.</p></details>
<details><summary>2. Why use this split?</summary><p>We assigned whole eggs: 18 training, six validation and six reserved for testing. Training learned weights; validation selected the checkpoint and calibrated scanner thresholds. Keeping every frame of an egg in one partition prevents a second view of the same egg from masquerading as a new test subject.</p></details>
<details><summary>3. Where are accuracy, precision, recall and F1?</summary><p>See the first-scan and repeat-scan tables above. Reject has no physical test support and is marked “Not measured.”</p></details>
<details><summary>4. How were the results computed?</summary><p>Accuracy = correct / all attempted scans. Precision = TP/(TP+FP), recall = TP/(TP+FN), and F1 = 2TP/(2TP+FP+FN). An unclassified result or acquisition failure is incorrect and contributes an FN to the known class. For a represented class with no positive predictions, precision is reported as zero. Classes with no actual examples are not scored.</p></details>
<details><summary>5. Did the same egg give a consistent result?</summary><p>Each completed egg had ten fresh acquisitions. The per-egg table shows the observed counts and exact repeat-match result. A consistently wrong grade would still be an error.</p></details>
<details><summary>6. Why can Day 16 and Day 18 be confused?</summary><p>The labels are two days apart in recorded incubation time. The scanner observes candled appearance, not elapsed time. Developmental differences may be difficult to see under changes in shell, exposure or angle. The observed errors show overlap; this experiment does not establish a biological cause or a unique visual marker for either day.</p></details>
<details><summary>7. Which epoch was selected, and why?</summary><p>The selected original model used epoch 4. Training stopped after epoch 12, when eight epochs did not improve validation macro F1 beyond the specified threshold. The two later preprocessing variants did not beat the original validation result.</p></details>
<details><summary>8. Was there data leakage?</summary><p>Identified age eggs and exact image duplicates did not cross partitions in the original audit. Unknown public egg or batch relationships cannot be ruled out. Earlier results on these reserved eggs were known before the expanded physical test, so it is a controlled follow-up, not fresh independent validation.</p></details>
<details><summary>9. Which CNN was tested?</summary><p>The physical test used the locked original three-class MobileNetV2 on the local CPU. The camera supplied fresh images. The live website’s classifier was not replaced by this experiment.</p></details>
<details><summary>10. What is the field-testing accuracy?</summary><p>Field accuracy has not been established. The controlled physical result is {first['correct']}/{first['attempts']} correct on the first scan per egg and {repeats['correct']}/{repeats['attempts']} correct across repeated attempts. There were no physical Reject examples. These figures do not estimate performance across vendors, farms or batches.</p></details></section>
<p><a href="physical-test-results.json">Download the physical test counts</a> · <a href="/assets/study-20261107-v1/evaluation-instrument.html">Blank system-quality evaluation instrument</a></p></main></html>'''
    (output / 'index.html').write_text(html, encoding='utf-8', newline='\n')
    return evidence


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('dataset', 'study', 'output'):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    value = build(args.dataset.resolve(), args.study.resolve(), args.output.resolve())
    print(f"{value['eggs_tested']} physical eggs; {value['repeated_attempts']['attempts']} attempted scans")
