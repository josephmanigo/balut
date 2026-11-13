"""Publish the paired physical comparison from verified, fresh acquisitions."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.build_emeet_physical_report import pct, results, table
from scripts.emeet_physical_metrics import load_physical_study


def build(dataset,run,study,output):
    evidence=load_physical_study(study,dataset,run/'candidate-lock.json')
    if evidence['completed_eggs']!=6 or evidence['repeated_attempts']['attempts']!=60:
        raise ValueError('Publish the full paired physical result after all six sessions; keep incomplete observations locally')
    old=evidence['paired_baseline']; metrics=json.loads((run/'metrics.json').read_text()); plan=json.loads((run/'protocol.json').read_text())
    output.mkdir(parents=True,exist_ok=True)
    evidence.update(training=metrics,training_plan=plan,automatic_grading_authorized=False)
    (output/'physical-retest.json').write_text(json.dumps(evidence,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    for name in ['epoch-curves.png','history.jsonl']: shutil.copyfile(run/name,output/name)
    first=evidence['primary_first_attempt_per_egg']; repeat=evidence['repeated_attempts']; base=old['repeated_attempts']; bf=old['primary_first_attempt_per_egg']
    pairs=table(['Known egg','Original first result','Candidate first result','Original correct / attempts','Candidate correct / attempts','Candidate wrong','Candidate unclassified','Acquisition failures'],
        [[e['egg_id'],next(a['baseline_outcome'] for a in evidence['scan_log'] if a['egg_id']==e['egg_id']),e['first_outcome'],
          f"{old['per_egg'][e['egg_id']]['correct']}/{e['attempts']}",f"{e['correct_attempts']}/{e['attempts']}",
          e['valid']-e['correct_attempts']-e['class_counts'].get('UNCLASSIFIED',0),e['class_counts'].get('UNCLASSIFIED',0),e['failures']] for e in evidence['per_egg']])
    css='body{font:17px/1.55 system-ui;color:#16312d;background:#f4f7f5;max-width:1100px;margin:auto;padding:20px}section{background:white;border:1px solid #d6dfdb;padding:20px;margin:18px 0;border-radius:10px}.lead{border-left:5px solid #38705c;padding:14px;background:#e7f1ec}table{border-collapse:collapse;font-size:15px}th,td{text-align:left;padding:8px;border-bottom:1px solid #d6dfdb}.scroll{overflow:auto}img{max-width:100%;height:auto}a{color:#006553}h1,h2{line-height:1.2}@media(max-width:600px){body,section{padding:12px}}'
    day18=repeat['per_class'][1]; old18=base['per_class'][1]; day16=repeat['per_class'][0]; old16=base['per_class'][0]
    html=f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>EggGrade | Paired physical retest</title><style>{css}</style><main>
<p>EGGGRADE · LIVE EMEET CAMERA · PAIRED RESEARCH RETEST</p><h1>Did the scanner recognize Day 18?</h1>
<p class="lead"><strong>Day 18: {day18['TP']}/{day18['support']} correct for the candidate; {old18['TP']}/{old18['support']} for the original on the same scans.</strong><br>
Day 16: {day16['TP']}/{day16['support']} correct for the candidate; {old16['TP']}/{old16['support']} for the original.</p>
<section><h2>Physical results</h2><p>First scan per egg: candidate {first['correct']}/{first['attempts']} ({pct(first['accuracy'])}); original {bf['correct']}/{bf['attempts']} ({pct(bf['accuracy'])}). All attempts: candidate {repeat['correct']}/{repeat['attempts']} ({pct(repeat['accuracy'])}); original {base['correct']}/{base['attempts']} ({pct(base['accuracy'])}).</p>{pairs}
<p>Each attempt reopened the EMEET camera and supplied both frozen models the same three fresh views. No earlier recordings entered this comparison. The denominator includes every attempted scan. Ten scans of one egg remain one physical subject.</p></section>
<section><h2>Candidate: one first scan per egg</h2>{results(first)}<h2>Candidate: all fresh scans</h2>{results(repeat)}<details><summary>Original model on these same physical views</summary>{results(base)}</details></section>
<section><h2>What changed</h2><p>The frozen MobileNetV2 branch retains the previously trained crop model’s Reject-versus-age decision. For age, a new binary classifier learns from sixteen measurements of transmitted red/green light and its variation across four bands inside the egg. The background is outside those age measurements. The graded classes are Day 16, Day 18 and Reject; uncertain views still abstain.</p>
<p>The age classifier learned weights only from the 18 training eggs. Six separate validation eggs guided the checkpoint and acceptance limits. Historical Reject images were used only in development and for the CNN branch; no physical Reject eggs were available for testing. Epoch {metrics['selected_epoch']} was retained after {metrics['completed_epochs']} completed epochs. Selection prioritized the lower of the two validation age recalls, then mean age recall and age loss. After eight stale epochs or the 50-epoch cap, training ends.</p>
<img src="epoch-curves.png" alt="Measured training and validation curves by epoch"><p><a href="history.jsonl">Download actual epoch measurements</a></p></section>
<section><h2>What these numbers mean</h2><p>The same six previously examined eggs were retested. The earlier physical failures informed the new model design. No reserved egg was used to fit weights, select the checkpoint or calibrate thresholds. Results describe a controlled paired retest; they do not establish independent field accuracy, physical Reject accuracy or food safety.</p>
<p>Precision = TP/(TP+FP), recall = TP/(TP+FN), F1 = 2TP/(2TP+FP+FN). Unclassified and failed attempts count against the true class. Macro F1 includes only classes with physical support.</p>
<p><a href="physical-retest.json">Download the complete paired scan log and metrics</a> · <a href="/assets/study-20261107-v3/index.html">Original physical study and panel questions</a></p></section></main></html>'''
    (output/'index.html').write_text(html,encoding='utf-8',newline='\n')
    return evidence


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('dataset','run','study','output'): p.add_argument(name,type=Path)
    args=p.parse_args(); build(args.dataset.resolve(),args.run.resolve(),args.study.resolve(),args.output.resolve())
