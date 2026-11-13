"""Freeze the 20-egg study, including verified views captured before the cohort revision."""
from collections import Counter
from pathlib import Path
import json
import os
import hashlib
import shutil
import sys
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.capture_emeet_egg import sha, verify_candidate, write

PREVIOUS = ROOT / "data/local/emeet-29-rotation-20261107"
STUDY = ROOT / "data/local/emeet-20-rotation-20261107"
REJECT = ROOT / "data/local/emeet-mobilenetv2-20261107/reject"

def make_plan():
    eggs = {}
    for age, total, train, dev in [(16, 10, 6, 8), (18, 10, 6, 8)]:
        for i in range(1, total + 1):
            eggs[f"D{age}-{i:02}"] = {"label": f"DAY_{age}", "partition": "train" if i <= train else "validation" if i <= dev else "test",
                                     "sampled_frames": 300}
    counts = Counter()
    for e in eggs.values():
        counts[e["label"]] += e["sampled_frames"]
    assert counts == {"DAY_16": 3000, "DAY_18": 3000} and len(eggs) == 20
    return {"eggs": eggs, "age_image_targets": counts, "sampled_frames": 300, "warmup_frames": 0, "sample_fps": 4,
            "capture_size": [1920,1080], "camera": "EMEET SmartCam C60E 4K",
            "physical_id_namespace": PREVIOUS.name, "prior_plan_sha256": sha(PREVIOUS/"collection-plan.json") if (PREVIOUS/"collection-plan.json").is_file() else None,
            "capture_protocol": "EMEET two placements, continuously rotating holder; 12 sectors per placement",
            "rotation_poses": ["side-A","side-B"], "steps_per_turn": 2048, "require_all_frames_distinct": True,
            "prior_cohort_overlap_possible": True, "label_authority": "Operator-confirmed incubation record at time of capture; never inferred from model",
            "reject_manifest_sha256": "a69e307f8e0a19e43cb708f93c878929c54ffa143082743391d898097ab7573a",
            "physical_test": {"attempts_per_egg": 10, "primary": "First fresh scan per reserved physical egg; unclassified and acquisition failures count as unsuccessful",
                              "secondary": "Repeatability over ten fresh scans on each reserved egg, without changing weights or thresholds",
                              "reject": "No live Reject egg supplied. Do not compute physical Reject recall or use archived images as field tests."},
            "training": "ImageNet MobileNetV2; no prior Balut weights; class and egg weighting, up to 50 epochs, patience 8 by validation macro F1",
            "rotation_limit": "Two orientations and full turns about the holder axis, not all possible 3D angles. Motor steps are estimates; no egg encoder."}

def bring_forward(plan):
    if not plan["prior_plan_sha256"]:
        return
    old_plan=json.loads((PREVIOUS/"collection-plan.json").read_text())
    if (PREVIOUS/"candidate-lock.json").exists():
        raise ValueError("Do not change eligibility after training or testing")
    for src in sorted((PREVIOUS/"captures").glob("*/*/record.json")):
        old=json.loads(src.read_text()); egg=old["egg_id"]
        if egg not in ("D16-01","D18-01") or old["partition"]!="train" or old["source_label"]!=plan["eggs"][egg]["label"] or old["plan_sha256"]!=plan["prior_plan_sha256"] or old_plan["physical_id_namespace"]!=plan["physical_id_namespace"]:
            raise ValueError("Unexpected prior capture; do not silently change labels or group identity")
        target=STUDY/"captures"/egg/"two-placements";target.mkdir(parents=True)
        new={k:old[k] for k in ["egg_id","source_label","partition","camera","started_at","model_used_for_label"]}
        new.update(status="partial",plan_sha256=sha(STUDY/"collection-plan.json"),rotation={},telemetry={},
                   prior_capture={"path":str(src),"sha256":sha(src),"prior_plan_sha256":old["plan_sha256"],"image_mapping":{}})
        for j,pose in enumerate(plan["rotation_poses"]):
            group=old["rotation"].get(pose)
            if not group:continue
            if len(group)>150 or {v["sector"] for v in group}!=set(range(12)):
                raise ValueError("Unverified old placement")
            meta=old["telemetry"][pose];trace=src.parent/meta["trace"]
            if not trace.resolve().is_relative_to(src.parent.resolve()) or sha(trace)!=meta["trace_sha256"]:
                raise ValueError("Prior motor trace changed")
            trace_copy=target/f"prior-{pose}-motor-trace.json"; shutil.copyfile(trace,trace_copy)
            new["telemetry"][pose]=[{**meta,"trace":trace_copy.name}]
            new["rotation"][pose]=[]
            for i,v in enumerate(group,1):
                original=src.parent/v["image"]
                if not original.resolve().is_relative_to(src.parent.resolve()):raise ValueError("Invalid prior image path")
                with Image.open(original) as im:
                    if hashlib.sha256(im.convert("RGB").tobytes()).hexdigest()!=v["pixel_sha256"]:raise ValueError("Prior pixels changed")
                filename=f"frame-{j*150+i:03d}.jpg"
                os.link(original,target/filename)
                new["prior_capture"]["image_mapping"][filename]={"prior_image":v["image"],"sha256":sha(original)}
                new["rotation"][pose].append({**v,"image":filename})
        write(target/"record.json",new)

def prepare_physical_protocol():
    lock=verify_candidate(STUDY)
    plan=json.loads((STUDY/"collection-plan.json").read_text())
    ids=[e for e,assignment in plan["eggs"].items() if assignment["partition"]=="test"]
    protocol={"scope":"Fresh EMEET scans of the four reserved physical eggs in this cohort; no saved images scored as tests.",
              "selected_eggs":ids,"candidate_lock_sha256":sha(STUDY/"candidate-lock.json"),
              "attempts_per_egg":plan["physical_test"]["attempts_per_egg"],"imported_original_physical_records":[],
              "count_all_scheduled_attempts":True,
              "plan_sha256":lock["collection_plan_sha256"],"primary":plan["physical_test"]["primary"],
              "physical_reject_eggs":0,"fresh_population_independence_verified":False}
    target=ROOT/"ml/runs"/(STUDY.name+"-physical")/"protocol.json"
    if target.exists():
        if json.loads(target.read_text())!=protocol:raise ValueError("Never modify a running physical test protocol")
    else:
        target.parent.mkdir(parents=True,exist_ok=False)
        write(target,protocol)
    return target

if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--physical-protocol", action="store_true")
    if parser.parse_args().physical_protocol:
        print(prepare_physical_protocol())
        sys.exit(0)
    plan = make_plan()
    audit = json.loads((REJECT / "audit.json").read_text())
    if sha(REJECT / "manifest.jsonl") != plan["reject_manifest_sha256"] or audit["manifest_sha256"] != plan["reject_manifest_sha256"]:
        raise ValueError("Wrong Reject dataset")
    rows = [json.loads(x) for x in (REJECT / "manifest.jsonl").read_text().splitlines()]
    if len(rows) != 3814 or any(r["source_label"] != "REJECT" or not Path(r["image_path"]).resolve().is_relative_to(REJECT.resolve()) or sha(Path(r["image_path"])) != r["source_sha256"] for r in rows):
        raise ValueError("Preserved Reject image or label changed")
    STUDY.mkdir(exist_ok=False)
    (STUDY / "reject").mkdir()
    for name in ["audit.json", "manifest.jsonl"]:
        shutil.copyfile(REJECT / name, STUDY / "reject" / name)
    write(STUDY / "collection-plan.json", plan)
    bring_forward(plan)
    (ROOT / "data/active-study.txt").write_text(STUDY.relative_to(ROOT / "data").as_posix() + "\n", encoding="ascii")
    print(json.dumps({"study": str(STUDY), "eggs": len(plan["eggs"]), "targets": plan["age_image_targets"],
                      "reject_verified": len(rows), "test_eggs": [e for e,v in plan["eggs"].items() if v["partition"]=="test"]}))
