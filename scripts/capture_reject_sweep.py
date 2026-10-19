"""Capture 50 paused views of each of three vendor-labeled Reject eggs."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps/edge_api"), str(ROOT / "ml")]
from scripts.capture_camera_sweep import collect, sha, TARGET, STEPS_PER_REVOLUTION
from scripts.camera_usb_bridge import open_camera
from scripts.spinner_control import open_spinner
from balut_ml.camera_angles import import_records

BASE = ROOT / "data/local/retained-camera-50views-20261019"
CAPTURE = ROOT / "output/physical-reject-20261019"
DATA = ROOT / "data/local/retained-camera-rejects-20261019"
PLAN = CAPTURE / "collection-plan.json"
SPLITS = {"R1": "train", "R2": "validation", "R3": "test"}


def plan():
    if sha(PLAN) != (CAPTURE / "collection-plan.sha256").read_text().strip():
        raise ValueError("Frozen Reject collection plan changed")
    value = json.loads(PLAN.read_text())
    if value["egg_partitions"] != SPLITS or sha(BASE / "manifest.jsonl") != value["base_manifest_sha256"]:
        raise ValueError("Reject partitions or original dataset changed")
    for name, digest in value["protected_files"].items():
        if sha(ROOT / name) != digest:
            raise ValueError("Protected source, camera model, or prior data changed")
    return value


def build_dataset(partial=False):
    plan()
    return import_records(BASE, CAPTURE, DATA, TARGET, partial, reject_plan=PLAN)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("egg_id", choices=SPLITS)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    settings = plan()
    target = CAPTURE / args.egg_id
    record_path = target / "record.json"
    if target.exists():
        if not args.resume or not record_path.is_file():
            raise FileExistsError("Preserve earlier photos; resume requires the same undisturbed egg")
        build_dataset(partial=True)
        record = json.loads(record_path.read_text())
    else:
        record = {"egg_id": args.egg_id, "source_label": "REJECT", "partition": SPLITS[args.egg_id],
                  "physical_egg_id": f"physical-reject-20261019:{args.egg_id}",
                  "reject_plan_sha256": sha(PLAN), "label_authority": settings["label_authority"],
                  "label_reference": settings["label_authority"], "defect_independently_confirmed": False,
                  "uncooked": True, "shell_marks": "operator_reports_unmarked_shells", "model_used_for_label": False,
                  "capture_session_id": CAPTURE.name, "capture_protocol": "fifty-paused-views-v1", "target_views": TARGET,
                  "steps_per_revolution": STEPS_PER_REVOLUTION, "angle_origin_steps": None, "angles_verified": False,
                  "rotation": "50 distinct commanded bins; physical angles not encoder verified", "completed": False, "views": []}
    identities = set()
    for row in map(json.loads, (BASE / "manifest.jsonl").read_text().splitlines()):
        identities.update((row["source_sha256"], row["pixel_sha256"]))
    for saved in CAPTURE.glob("*/record.json"):
        for view in json.loads(saved.read_text())["views"]:
            identities.update((view["sha256"], view["pixel_sha256"]))
    policy = json.loads((ROOT / "ml/runs/selective-v2/gate-policy.json").read_text())
    try:
        if len(record["views"]) < TARGET:
            with closing(open_camera()) as camera, closing(open_spinner()) as spinner:
                try:
                    if record["views"]:
                        _, steps = spinner.command("STATUS")
                        if ((steps - record["views"][-1]["motor_steps"]) & 0xffffffff) >= 0x80000000:
                            raise ValueError("Spinner counter reset; preserve the partial capture for review")
                    collect(camera, spinner, target, record, policy, identities)
                finally:
                    spinner.command("RUN")
    finally:
        if record_path.is_file():
            audit = build_dataset(partial=True)
            print(json.dumps({"egg": args.egg_id, "saved_views": len(json.loads(record_path.read_text())["views"]),
                              "dataset_new_reject_views": audit["new_views"], "completed_reject_eggs": audit["completed_eggs"]}), flush=True)


if __name__ == "__main__":
    main()
