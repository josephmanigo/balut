"""Collect 50 fresh paused views of one original numbered egg, saving every view."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "apps/edge_api"), str(ROOT / "ml")]
from balut_api.automatic_box import prepare_camera_frame
from balut_api.model_service import decode_jpeg
from balut_api.selective_gate import image_quality
from scripts.camera_usb_bridge import open_camera, read_fresh_snapshot
from scripts.camera_egg_ids import partition_for
from scripts.spinner_control import open_spinner

CAPTURE = ROOT / "output/physical-50views-20261019"
BASE = ROOT / "data/local/retained-camera-angles-20261019"
DATA = ROOT / "data/local/retained-camera-50views-20261019"
TARGET = 50
STEPS_PER_REVOLUTION = 2048


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def angle_bin(steps, origin):
    if any(type(value) is not int or not 0 <= value <= 0xffffffff for value in (steps, origin)):
        raise ValueError("Invalid motor step counter")
    return ((steps - origin) & 0xffffffff) % STEPS_PER_REVOLUTION * TARGET // STEPS_PER_REVOLUTION


def prepared_frame(raw, policy):
    body = prepare_camera_frame(raw)
    with decode_jpeg(body) as image:
        if image.size != (600, 800):
            raise ValueError("Expected unchanged 600 by 800 camera framing")
        quality, flags = image_quality(image, policy)
        pixels = hashlib.sha256(str(image.size).encode() + image.tobytes()).hexdigest()
    if flags:
        raise ValueError("Image quality failed: " + ", ".join(flags))
    return body, pixels, quality


def save_view(target, record, body, metadata):
    index = len(record["views"]) + 1
    target.mkdir(parents=True, exist_ok=True)
    name = f"view-{index}.jpg"
    with (target / name).open("xb") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())
    record["views"].append({**metadata, "view_index": index, "image": name})
    record["completed"] = len(record["views"]) == TARGET
    temporary = target / "record.pending"
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(target / "record.json")


def collect(camera, spinner, target, record, policy, identities):
    used = {view["angle_bin"] for view in record["views"]}
    origin = record.get("angle_origin_steps")
    failures, last_progress = 0, time.monotonic()
    spinner.command("RUN")
    while len(record["views"]) < TARGET:
        if time.monotonic() - last_progress > 120:
            raise ValueError("No new usable angle for two minutes; preserve the egg and resume after checking USB")
        state, running_steps = spinner.command("STATUS")
        if state != "RUNNING":
            raise ValueError("Holder is not running between captures")
        if origin is not None and angle_bin(running_steps, origin) in used:
            time.sleep(.01)
            continue
        try:
            with spinner.capture_hold():
                _, steps = spinner.command("STATUS")
                if origin is None:
                    origin = steps
                    record["angle_origin_steps"] = origin
                slot = angle_bin(steps, origin)
                if slot in used:
                    continue
                raw = read_fresh_snapshot(camera)
                captured_at = datetime.now(timezone.utc).isoformat()
                body, pixels, quality = prepared_frame(raw, policy)
                digest = hashlib.sha256(body).hexdigest()
                if digest in identities or pixels in identities:
                    raise ValueError("Duplicate camera image; not counted")
        except ValueError as exc:
            failures += 1
            print(json.dumps({"egg": record["egg_id"], "saved": len(record["views"]),
                              "discarded": str(exc), "consecutive_failures": failures}), flush=True)
            if failures >= 10:
                raise ValueError("Ten consecutive failed captures; earlier saved photos are preserved") from exc
            time.sleep(.5)
            continue
        save_view(target, record, body, {"motor_steps": steps, "angle_bin": slot,
                  "commanded_angle_degrees": round(((steps - origin) & 0xffffffff) % STEPS_PER_REVOLUTION * 360 / STEPS_PER_REVOLUTION, 6),
                  "angles_verified": False, "captured_at": captured_at, "raw_sha256": hashlib.sha256(raw).hexdigest(),
                  "sha256": digest, "pixel_sha256": pixels, "quality_measurements": quality})
        used.add(slot)
        identities.update((digest, pixels))
        failures, last_progress = 0, time.monotonic()
        print(json.dumps({"egg": record["egg_id"], "saved": len(record["views"]), "target": TARGET,
                          "commanded_angle_bins": len(used), "holder_resumed": True}), flush=True)


def build_dataset(partial=False):
    from balut_ml.camera_angles import import_records
    return import_records(BASE, CAPTURE, DATA, TARGET, partial)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("egg_id")
    parser.add_argument("--resume", action="store_true", help="Only while the same egg remains undisturbed and the spinner stays powered")
    args = parser.parse_args()
    age, partition = partition_for(args.egg_id)
    original_path = ROOT / "output/physical-pilot-20261018" / f"{args.egg_id}.json"
    original = json.loads(original_path.read_text())
    if original["egg_id"] != args.egg_id or original["partition"] != partition or original["reported_age_days"] != age:
        raise ValueError("Original egg identity or partition changed")
    target = CAPTURE / args.egg_id
    record_path = target / "record.json"
    if target.exists():
        if not args.resume or not record_path.is_file():
            raise FileExistsError("Preserve existing captures; resume requires a valid saved record")
        build_dataset(partial=True)
        record = json.loads(record_path.read_text())
        if record["egg_id"] != args.egg_id:
            raise ValueError("Saved egg identity changed")
    else:
        record = {"egg_id": args.egg_id, "reported_age_days": age, "partition": partition,
                  "physical_egg_id": f"physical-camera-20261018:{args.egg_id}", "original_record_sha256": sha(original_path),
                  "label_authority": original["label_authority"], "label_reference": "Original numbered egg cohort; current elapsed incubation age not independently verified",
                  "shell_marks": "operator_reports_unmarked_shells", "model_used_for_label": False,
                  "capture_session_id": CAPTURE.name, "capture_protocol": "fifty-paused-views-v1", "target_views": TARGET,
                  "steps_per_revolution": STEPS_PER_REVOLUTION, "angle_origin_steps": None, "angles_verified": False,
                  "rotation": "50 distinct commanded angle bins over approximate motor rotations; no physical position encoder",
                  "test_status": "closed_original_pilot_test" if partition == "test" else None, "completed": False, "views": []}
    identities = set()
    baseline = BASE / "manifest.jsonl"
    audit = json.loads((BASE / "audit.json").read_text())
    if sha(baseline) != audit["manifest_sha256"]:
        raise ValueError("Preserved dataset changed")
    for line in baseline.read_text().splitlines():
        row = json.loads(line)
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
                            raise ValueError("Spinner counter reset; preserve the partial collection for review")
                    collect(camera, spinner, target, record, policy, identities)
                finally:
                    spinner.command("RUN")
    finally:
        if record_path.is_file():
            result = build_dataset(partial=True)
            print(json.dumps({"egg": args.egg_id, "saved_views": len(json.loads(record_path.read_text())["views"]),
                              "dataset_new_views": result["new_views"], "completed_eggs": result["completed_eggs"],
                              "active_model_changed": False}), flush=True)


if __name__ == "__main__":
    main()
