"""Build a local defense report for the 20-egg EMEET study from measured results."""
from collections import Counter
from html import escape
import json
from pathlib import Path
import shutil
from statistics import median
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "ml"), str(ROOT / "apps/edge_api")]
from scripts.build_emeet_physical_report import pct, results, table
from scripts.build_emeet_study_report import metric_table
from scripts.capture_emeet_egg import sha, verify_candidate
from scripts.emeet_physical_metrics import load_physical_study
from scripts.prepare_emeet_rotation_study import STUDY

RUN = ROOT / "ml/runs" / STUDY.name
TRIAL = RUN.with_name(RUN.name + "-physical")
OUT = ROOT / "output" / (STUDY.name + "-panel")
LABELS = ("DAY_16", "DAY_18", "REJECT")


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def physical_section():
    if not (TRIAL / "protocol.json").exists():
        return "<p>Physical testing awaits the locked model.</p>"
    evidence = load_physical_study(TRIAL, STUDY)
    (OUT / "physical-results.json").write_text(json.dumps(evidence, indent=2, allow_nan=False), encoding="utf-8")
    if not evidence["eggs_tested"]:
        return "<p>The four reserved eggs have no completed scan attempts yet.</p>"
    rows = [[r["egg_id"], r["first_outcome"], r["attempts"], r["correct_attempts"],
             pct(r["class_agreement"]), pct(r["decision_agreement"]), r["maximum_score_difference"],
             "Yes" if r["strict_zero_gap_passed"] else "No"] for r in evidence["per_egg"]]
    seconds = [a["seconds"] for a in evidence["scan_log"]]
    view_rows = []
    for egg in evidence["per_egg"]:
        record = read(TRIAL / egg["egg_id"] / "record.json")
        winners = Counter(LABELS[max(range(len(LABELS)), key=view["scores"].__getitem__)]
                          for attempt in record["attempts"] for view in attempt.get("views", []))
        view_rows.append([egg["egg_id"], *(winners[label] for label in LABELS)])
    return (f'<p>Ten attempts completed on {evidence["completed_eggs"]} of {evidence["planned_eggs"]} reserved eggs.</p>'
            '<h3>First scan per egg</h3>' + results(evidence["primary_first_attempt_per_egg"]) +
            '<h3>All repeat attempts</h3>' + results(evidence["repeated_attempts"]) +
            table(["Egg", "First outcome", "Attempts", "Correct", "Class agreement", "Decision agreement",
                   "Maximum score difference", "Exact repeat match"], rows) +
            f'<p>Elapsed time per recorded attempt, including acquisition and inference, had a median of {median(seconds):.1f} seconds '
            f'and a range of {min(seconds):.1f} to {max(seconds):.1f} seconds.</p>' +
            '<p>Class agreement is the fraction of valid scans with the most frequent class outcome, including unclassified. '
            'Decision agreement compares the decision to classify or request another scan. '
            'Exact repeat match also requires identical score vectors and all ten successful acquisitions.</p>'
            '<h3>What each physical camera view predicted</h3>'
            + table(["Egg", "Day 16 top prediction", "Day 18 top prediction", "Reject top prediction"], view_rows)
            + '<p>These are the raw network predictions from the fresh physical scans. The scanner then applies its '
            'decision rules and combines three views for each result.</p>'
            '<p><a href="physical-results.json">Physical records, confusion counts and timing</a></p>')


def calibration_section():
    path = RUN / "calibration/edge-comparison.json"
    if not path.exists():
        return ""
    evidence = read(path)
    shutil.copyfile(path, OUT / path.name)
    chosen = evidence["candidate"] if evidence["changed"] else evidence["baseline"]
    rows = []
    for label in LABELS:
        entry = chosen["per_class"][label]
        rows.append([label, pct(entry["coverage"]), pct(entry["gated_precision"]), pct(entry["gated_recall"]),
                     pct(entry["gated_f1"]), entry["recapture_reasons"].get("IMAGE_TOO_BLURRY", 0)])
    day18_old = evidence["baseline"]["per_class"]["DAY_18"]
    day18_new = chosen["per_class"]["DAY_18"]
    return (f'<p>Before comparing the two settings, the training egg edge measurements suggested a second sharpness threshold '
            f'of {evidence["candidate_floor"]:g}. The original threshold was {evidence["original_floor"]:g}. '
            f'The development comparison selected {evidence["selected_edge_floor"]:g}. For Day 18, the original setting returned '
            f'{day18_old["correct_accepted"]} correct and {day18_old["wrong_accepted"]} wrong grades. The selected setting returned '
            f'{day18_new["correct_accepted"]} correct and {day18_new["wrong_accepted"]} wrong grades across the same {day18_new["views"]} views.</p>'
            + table(["Known class","Coverage","Precision","Recall","F1","Views flagged for low edge variance"], rows)
            + '<p><a href="edge-comparison.json">Per-egg and per-class calibration evidence</a></p>')


def build():
    lock = verify_candidate(STUDY)
    metrics = read(RUN / "metrics.json")
    recipe = read(RUN / "experiment-plan.json")
    if Path(lock["run"]).resolve() != RUN or recipe["collection_plan_sha256"] != sha(STUDY / "collection-plan.json"):
        raise ValueError("The model and collection must refer to the same study")
    OUT.mkdir(exist_ok=True, parents=True)
    for name in ("epoch-curves.png", "history.jsonl", "experiment-plan.json", "metrics.json"):
        shutil.copyfile(RUN / name, OUT / name)
    plan = read(STUDY / "collection-plan.json")
    dev = read(RUN / "development-manifest.json")
    outcomes = read(RUN / "calibration/validation-outcomes.json")
    verify = read(RUN / "calibration/verification.json")
    validation = verify["serving_validation"]
    assert validation["evaluated"] == len(outcomes) == sum(r["partition"] == "validation" for r in dev)
    outcome_counts = Counter((r["truth"], r["sourcePrediction"]) for r in outcomes)
    decisions = []
    for label in LABELS:
        correct = outcome_counts[label, label]
        support = sum(r["truth"] == label for r in outcomes)
        unanswered = outcome_counts[label, None]
        decisions.append([label, support, correct, support - correct - unanswered, unanswered, pct(correct / support)])
    records = [read(p) for p in (STUDY / "captures").glob("*/*/record.json")]
    records = [r for r in records if r["status"] == "complete"]
    split = []
    for partition in ("train", "validation", "test"):
        for label in LABELS[:2]:
            eggs = [key for key, v in plan["eggs"].items() if (v["partition"], v["label"]) == (partition, label)]
            observed = [r for r in records if r["egg_id"] in eggs]
            split.append([partition, label, len(eggs), len(observed), sum(len(r["views"]) for r in observed)])
    day18 = validation["per_class"][1]
    tp, fp, fn = (day18[key] for key in ("TP", "FP", "FN"))
    matrix = validation["raw_confusion_matrix"]
    src = "https://pubmed.ncbi.nlm.nih.gov/40460742/"
    physical = physical_section()
    headline = ""
    if (OUT / "physical-results.json").is_file():
        evidence = read(OUT / "physical-results.json")
        first = evidence["primary_first_attempt_per_egg"]
        repeats = evidence["repeated_attempts"]
        if first["attempts"]:
            headline = (f'<h2>Physical results</h2><p>The first fresh scan correctly classified <strong>{first["correct"]} of '
                        f'{first["attempts"]} reserved eggs ({pct(first["accuracy"])})</strong>. Across {repeats["attempts"]} scans '
                        f'of the same eggs, {repeats["correct"]} returned the correct age, {repeats["wrong_classified"]} returned the wrong age '
                        f'and {repeats["unclassified"]} asked for recapture. Camera acquisitions failed on {repeats["acquisition_failures"]} scans.</p>')
    document = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EggGrade · 20-egg EMEET study</title><style>
body{{font:16px/1.55 system-ui,sans-serif;color:#18272c;max-width:1000px;margin:auto;padding:24px}}
h1,h2,h3{{line-height:1.2}} h2{{margin-top:2em;border-bottom:1px solid #a3bbb3;padding-bottom:.4em}}
section{{margin:2rem 0}} table{{border-collapse:collapse;margin:.8em 0;min-width:60%}}td,th{{border:1px solid #cbd7d3;padding:.4rem .65rem;text-align:left}}
thead,th{{background:#eaf2ef}}img{{width:100%;height:auto}}a{{color:#105955}}.scroll{{overflow:auto}}
@media print{{body{{font-size:10pt}}table,img{{break-inside:avoid}}}}</style><main>
<h1>EggGrade · 20-egg EMEET study</h1>
{headline}
<p>Research candidate for Day 16, Day 18 and Reject. The EMEET C60E supplied fresh camera views while the microcontroller turned the egg holder. MobileNetV2 trained on the host GPU. The local CPU runs the locked model for physical trials.</p>
<h2>How did you train the model, and which CNN did you use?</h2>
<p>We initialized MobileNetV2 from ImageNet weights and fitted a three-class output. Images were resized to 224 × 224 and normalized. AdamW optimized weighted cross-entropy in batches of {recipe["batch_size"]}.
The first three epochs trained the classifier. Later epochs also updated the last five feature blocks. Each egg or annotated source family contributed equal total weight within its class, and the three classes received equal total weight. Small geometric and brightness changes augmented the training set during fitting.</p>
<h2>Why use this split? How did you check for leakage?</h2>
<p>We assigned six eggs per age to training, two to validation and two to physical testing before fitting. This 60/20/20 split keeps every view of an egg in one partition. Each egg contributes 300 real images from two placements. Each placement covers 12 estimated holder sectors.</p>
{table(["Partition","Known age","Assigned eggs","Captured eggs","Recorded images"], split)}
<p>The preserved Reject collection contributed 3,033 training and 570 validation images. Its 211 archived test images are excluded from physical testing. Source labels include Reject and Unfertilized. There were no confirmed dead-embryo or spoiled eggs in this cohort and no physical Reject test eggs. Accuracy for those conditions remains unknown.</p>
<p>Development checks verified egg and source-family assignments, image hashes, and exact pixel identities. Thousands of views do not increase the number of independent eggs. Unknown public egg or batch identities limit any leakage guarantee. Some eggs may overlap prior experiments. The four reserved eggs stayed outside this candidate’s fitting and calibration.</p>
<h2>Which epoch was selected, and why did training stop?</h2>
<p>Training finished after <strong>{metrics["epochs_completed"]} epochs</strong>. The checkpoint from <strong>epoch {metrics["selected_epoch"]}</strong> was restored. The recorded stopping condition was <strong>{escape(metrics["stop_reason"].replace("_"," "))}</strong>.
The cap was {recipe["maximum_epochs"]} epochs. Patience was {recipe["patience"]} stale epochs after warmup. Progress required a validation macro-F1 gain greater than {recipe["minimum_f1_improvement"]}. Lower validation loss could break an equal-F1 tie without resetting patience.</p>
<img src="epoch-curves.png" alt="Training and validation loss, accuracy, precision, recall, macro F1 and balanced accuracy by completed epoch">
<p><a href="history.jsonl">Epoch measurements</a> · <a href="experiment-plan.json">Training recipe</a> · <a href="metrics.json">Checkpoint metrics</a></p>
<h2>Where are accuracy, precision, recall and F1?</h2>
<h3>Training images · selected GPU checkpoint</h3>{metric_table(metrics["train"])}
<h3>Validation images · exported CPU model</h3>{metric_table(validation)}
<h3>Validation decisions with the scanner rules</h3>
{table(["Known class","Images","Correct","Wrong class","Unclassified","Correct / all"], decisions)}
{calibration_section()}
<p>These validation examples informed calibration. The physical test below uses new camera scans with all decision thresholds frozen.</p>
<h2>How were these values computed?</h2>
<p>For a class, TP counts correct predictions, FP counts other classes predicted as that class, and FN counts its missed examples.
Precision = TP / (TP + FP). Recall = TP / (TP + FN). F1 = 2TP / (2TP + FP + FN).
For Day 18 in the raw CPU validation table, TP = {tp}, FP = {fp}, FN = {fn}, giving precision {pct(day18["precision"])}, recall {pct(day18["recall"])} and F1 {pct(day18["f1"])}.
Accuracy is total correct divided by all evaluated images or attempts. Macro F1 averages the class F1 values. Coverage is classified attempts divided by all attempts.
Physical accuracy counts wrong, unclassified and failed acquisitions as unsuccessful, and physical Reject recall is unmeasured.</p>
<h2>Why can Day 16 and Day 18 be confused?</h2>
<p>The CPU model gave {matrix[1][0]} known Day 18 validation views a Day 16 top prediction and {matrix[0][1]} known Day 16 views a Day 18 top prediction. The incubation records differ by two days. The EMEET sees light transmitted through the egg. Some eggs of either age showed a dark center and bright rim. Angle, shell and exposure can change that pattern, and a low edge score can trigger recapture. The exact biological cause of each error was not measured. Embryonic stages can progress at different rates across duck types. <a href="{src}">Published Pekin and Mulard staging study</a>.</p>
<h2>How consistent is the same egg? What is the field accuracy?</h2>
{physical}
<p>The planned primary physical result uses the first fresh scan on each of four eggs. Ten fresh scans per egg describe repeatability. With two eggs per age, one changed first-scan result changes that age’s observed recall by 50 percentage points. Production-field accuracy across farms, vendors or batches remains unestablished.</p>
<h2>Progress against the study objectives</h2>
<p>The capture records verify camera acquisition, holder motion and CNN training. The physical trial measures scanner decisions, repeatability and time per attempt. Mechanical routing into the correct grade bins requires a separate observed sorting trial.
The study’s software-quality objective also requires participant responses on functional suitability, performance, usability and reliability. The available <a href="evaluation-instrument.html">evaluation instrument</a> is blank. No participant quality score is claimed.</p>
</main></html>"""
    instrument = ROOT / "output/emeet-mobilenetv2-study/evaluation-instrument.html"
    shutil.copyfile(instrument, OUT / "evaluation-instrument.html")
    (OUT / "index.html").write_text(document, encoding="utf-8")
    return OUT / "index.html"


if __name__ == "__main__":
    print(build())
