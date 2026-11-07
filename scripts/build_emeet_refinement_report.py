"""Compare the two declared development refinements without selecting on test results."""
import argparse
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_emeet_study_report import metric_table, read
from scripts.capture_emeet_egg import sha, verify_candidate, write


def choose(candidates):
    return max(candidates, key=lambda name: (candidates[name]["validation"]["macro_f1"],
                                            -candidates[name]["validation"]["loss"]))


def build(dataset, original, refinement, output):
    original_lock = verify_candidate(dataset)
    if Path(original_lock["run"]).resolve() != original.resolve():
        raise ValueError("Original study run differs from the frozen candidate")
    protocol = read(refinement / "protocol.json")
    if protocol["original_candidate_lock_sha256"] != sha(dataset / "candidate-lock.json"):
        raise ValueError("Original candidate changed after the refinement plan")
    runs = {"full": original, **{name: refinement / name for name in protocol["candidates"]}}
    measured, hashes = {}, {}
    for name, run in runs.items():
        lock = read(run / "training-lock.json")
        if not lock or any(sha(run / path) != digest for path, digest in lock["artifacts"].items()):
            raise ValueError(f"Incomplete or changed training run: {name}")
        measured[name] = read(run / "metrics.json")
        hashes[name] = sha(run / "training-lock.json")
    selected = choose(measured)
    selection = {"selected": selected, "criterion": protocol["selection"], "training_lock_sha256": hashes,
                 "protocol_sha256": sha(refinement / "protocol.json"), "test_used_for_candidate_selection": False,
                 "prior_test_examined": True, "fresh_independent_test": False}
    selection_path = refinement / "selection.json"
    if selection_path.exists() and read(selection_path) != selection:
        raise ValueError("Preserve the recorded validation selection")
    if not selection_path.exists():
        write(selection_path, selection)
    selected_run = runs[selected]
    test = read(selected_run / "test/metrics.json")
    if selected != "full" and test and not test.get("prior_test_examined"):
        raise ValueError("Refinement results must disclose that this is a retest")
    output.mkdir(parents=True, exist_ok=True)
    evidence = {"generated_at": datetime.now(timezone.utc).isoformat(), "protocol": protocol,
                "selection": selection, "candidates": measured, "selected_test": test,
                "new_images_captured": 0, "unique_age_eggs": 30, "physical_reject_eggs": 0,
                "fresh_independent_test": False, "field_accuracy_established": False, "promoted": False}
    write(output / "refinement-evidence.json", evidence)
    shutil.copyfile(refinement / "protocol.json", output / "protocol.json")
    comparison, sections = [], []
    titles = {"full": "Original full frame", "egg-roi": "Fixed egg-region crop",
              "egg-roi-gamma": "Crop + shadow brightening"}
    for name, run in runs.items():
        value = measured[name]; val = value["validation"]
        comparison.append(f'<tr><th>{titles[name]}</th><td>{value["epochs_completed"]}</td>'
                          f'<td>{value["selected_epoch"]}</td><td>{val["raw_accuracy"]:.2%}</td>'
                          f'<td>{val["macro_f1"]:.2%}</td><td>{val["per_class"][1]["recall"]:.2%}</td>'
                          f'<td>{val["loss"]:.5f}</td></tr>')
        chart = name + '-epochs.png'; history = name + '-history.jsonl'
        shutil.copyfile(run / "epoch-curves.png", output / chart)
        shutil.copyfile(run / "history.jsonl", output / history)
        sections.append(f'<section><h2>{titles[name]}</h2><p>{value["epochs_completed"]} completed epochs; '
                        f'checkpoint from epoch {value["selected_epoch"]}. Stop reason: {escape(value["stop_reason"])}. '
                        'Each epoch is one pass through the augmented training images. Validation macro F1 selects the checkpoint; '
                        'eight stale epochs stop training. Equal-F1, lower-loss ties can replace the checkpoint without resetting patience.</p>'
                        f'<img src="{chart}" alt="Measured training and validation loss, accuracy, precision, recall and F1 by epoch">'
                        f'<p><a href="{history}">Download every measured epoch</a></p>'
                        f'<h3>Selected checkpoint: validation</h3>{metric_table(val)}</section>')
    outcome = ('Neither declared preprocessing change improved validation macro F1. The original research checkpoint remains selected. '
               'Reliable Day 18 classification remains unresolved.' if selected == "full" else
               f'Development validation selected {titles[selected].lower()}. This is an exploratory candidate; '
               'validation improvement does not establish reliable scanning or field accuracy.')
    test_scope = ('Original first-test measurements, preserved unchanged; the original model was not retested or retrained on test eggs.'
                  if selected == "full" else 'Exploratory retest of the same previously examined six age eggs and historical Reject images; no fresh independent test.')
    test_html = metric_table(test["overall"], show_decisions=True) if test else '<p>Evaluation pending. No retest score is claimed.</p>'
    if test:
        matrix = test["overall"]["raw_confusion_matrix"]
        age_correct = matrix[0][0] + matrix[1][1]
        age_total = sum(matrix[0]) + sum(matrix[1])
        test_html += (f'<p><strong>Age-only raw result: {age_correct}/{age_total} = {age_correct / age_total:.2%}.</strong> '
                      'The aggregate above also includes historical public Reject images. These are image-level results; '
                      '600 age frames still represent only six eggs.</p>')
    html = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>EggGrade — existing-egg refinement evidence</title><style>
body{{font:17px/1.6 system-ui;color:#172c34;background:#f3f6f7;max-width:1120px;margin:auto;padding:28px}}
h1,h2,h3{{line-height:1.2}}h1{{font-size:2.3rem}}section{{background:white;padding:24px;margin:24px 0;border-radius:12px}}
.notice{{border-left:6px solid #a54b17;padding:16px;background:#fff1df}}a{{color:#006151}}img{{max-width:100%;height:auto}}
table{{border-collapse:collapse;width:100%;font-size:15px}}th,td{{text-align:left;padding:10px;border-bottom:1px solid #d6dee1}}
.scroll{{overflow-x:auto}}.muted{{color:#4a626b}}code{{overflow-wrap:anywhere}}@media(max-width:600px){{body{{padding:12px}}section{{padding:16px}}h1{{font-size:1.8rem}}}}
</style><main><p class="muted">EGGGRADE · DEVELOPMENT REFINEMENT · 7 NOVEMBER 2026</p>
<h1>What the existing 30 eggs can tell us</h1><p class="notice"><strong>{outcome}</strong><br>FIELD ACCURACY NOT YET ESTABLISHED.</p>
<p>No new independent eggs or photographs were added. The original 3,000 real age frames and retained Reject data remain intact.
<a href="/assets/study-20261107-v1/index.html">Open the original study, all ten panel answers and the evaluation instrument.</a></p>
<section><h2>Validation comparison</h2><p>All three models use ImageNet-pretrained MobileNetV2 and the same whole-egg development partitions.
The selection rule was recorded before these two training runs: highest validation macro F1, then lower validation loss. Test results did not select between these candidates.</p>
<div class="scroll"><table><tr><th>Representation</th><th>Epochs completed</th><th>Selected epoch</th><th>Accuracy</th><th>Macro F1</th><th>Day 18 recall</th><th>Loss</th></tr>{''.join(comparison)}</table></div>
<p><strong>Selected: {titles[selected]}.</strong> Scores above use 1,170 validation images: 300 Day 16, 300 Day 18 and 570 historical Reject images.</p></section>
<section><h2>What changed and what was measured</h2><p>The crop removes the outer left and right background using fixed columns 48–175 of the 224-pixel input,
resizes the crop and applies an elliptical mask. The second candidate also uses gamma 0.5 to brighten shadows. Both transformations are embedded in the exported ONNX graph.
They cannot recover biological detail absent from the capture. The geometry was inspected using development captures only.</p>
<p>Both refinements used seed 42, AdamW, batch size 32, head learning rate 0.0003, encoder learning rate 0.00001, weight decay 0.0001,
three head-only warmup epochs and then the last five encoder blocks. Batch-normalization statistics stayed frozen.
Each physical egg or public source family received equal weight within its class; classes received equal total weight.
The maximum was 30 epochs per refinement; patience was eight epochs without a macro-F1 gain greater than 0.001.</p>
<p>TF32 was disabled for the refinements to reduce GPU/CPU numerical differences; the original run used its preserved GPU settings.
This comparison evaluates complete training recipes, not an isolated causal estimate of cropping or gamma.</p></section>
<section><h2>Split and leakage disclosure</h2><p>The 60/20/20 age split remains 18 training eggs, six validation eggs and six original test eggs.
Training uses 12 Day 16 + six Day 18 eggs; validation and test each use four Day 16 + two Day 18 eggs.
Every frame from an identified egg stays in one partition. The six test eggs never enter weight fitting or threshold calibration.</p>
<p><strong>The original test failures were already seen before this refinement.</strong> They motivated the new experiment, so any later reuse of those test eggs is a retest.
Group separation prevents known same-egg frame leakage; it does not restore a fresh test after inspecting its results.
Unknown public egg identities, shared incubation batches and class-specific camera backgrounds remain limitations.</p></section>
{''.join(sections)}
<section><h2>Test evidence and its limits</h2><p>{test_scope}</p>{test_html}
<p>No physical Reject egg has been tested. Historical Reject/Unfertilized annotations do not establish recognition of confirmed dead embryos or spoiled eggs through EMEET.
Unclassified results remain separate from Reject. No automatic operational promotion was made.</p></section>
<section><h2>Panel answers after this refinement</h2><p>The original linked report preserves the ten complete answers, including formulas and fresh repeat scans.
The added answer is: “We tried two declared preprocessing refinements on the same development eggs and selected only by validation macro F1.
We report all attempts, including unsuccessful ones. More views of the same 30 eggs do not create new independent test subjects.”</p>
<p>Precision = TP/(TP+FP); recall = TP/(TP+FN); F1 = 2TP/(2TP+FP+FN); accuracy = correct/total.
Macro F1 is the arithmetic mean of the three class F1 scores. Counts and confusion matrices above make those computations reproducible.</p>
<p>The initial fresh-repeat study remains unchanged: Day 16 was correct in 9/10 scans with one unclassified;
Day 18 was correct in 0/10, with seven wrong Day 16 outputs and three unclassified. Those correlated attempts are not ten new eggs.
No new physical-repeat result is claimed for the refinement. Exact zero-gap consistency and field accuracy remain unestablished.</p>
<p><a href="refinement-evidence.json">Download measured comparison and selection</a> · <a href="protocol.json">Download the declared experiment plan</a></p></section>
<p class="muted">Generated {escape(evidence['generated_at'])}. Original evidence preserved; model deployment and physical field validation remain separate.</p></main></html>'''
    (output / "index.html").write_text(html, encoding="utf-8")
    return selection


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "original", "refinement", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.dataset, args.original, args.refinement, args.output)))
