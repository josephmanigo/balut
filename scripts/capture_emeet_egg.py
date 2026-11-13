"""Capture a labeled EMEET video sample under a frozen physical-egg split."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/edge_api"))
from balut_api.model_service import decode_jpeg
from balut_api.selective_gate import image_quality


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def verify_candidate(dataset, lock_path=None):
    original = dataset / 'candidate-lock.json'
    lock_path = lock_path or original
    if not lock_path.is_file():
        raise ValueError("Keep test eggs unscanned until the candidate is locked")
    try:
        lock = json.loads(lock_path.read_text())
        if lock_path.resolve() != original.resolve():
            verify_candidate(dataset)
            run = Path(lock['run']).resolve()
            files = {Path(a['path']).resolve() for a in lock['artifacts']}
            required = {run / n for n in ('best.onnx', 'calibration/gate-policy.json', 'calibration/training-references.npz', 'protocol.json')}
            if (lock['original_candidate_sha256'] != sha(original)
                    or lock_path.resolve() != run / 'candidate-lock.json' or not required <= files
                    or any(not path.is_relative_to(run) for path in files)):
                raise ValueError('Research candidate must preserve its original study and run identity')
        if lock["schema_version"] != 1 or lock["collection_plan_sha256"] != sha(dataset / "collection-plan.json") or not lock["artifacts"]:
            raise ValueError("Invalid candidate lock")
        for artifact in lock["artifacts"]:
            if sha(Path(artifact["path"])) != artifact["sha256"]:
                raise ValueError("Locked candidate artifacts changed")
    except (KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid candidate lock") from exc
    return lock


def finish(dataset, folder):
    dataset, folder = dataset.resolve(), folder.resolve()
    if not folder.is_relative_to(dataset / "captures"):
        raise ValueError("Capture must belong to this dataset")
    plan_path = dataset / "collection-plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    record_path = folder / "record.json"
    record = json.loads(record_path.read_text(encoding="utf-8-sig"))
    if record["plan_sha256"] != sha(plan_path):
        raise ValueError("Collection plan changed after capture")
    assignment = plan["eggs"][record["egg_id"]]
    if record["source_label"] != assignment["label"] or record["partition"] != assignment["partition"]:
        raise ValueError("Egg label or partition differs from collection plan")
    if record["status"] == "complete":
        if any(not re.fullmatch(r"frame-[0-9]{3}\.jpg", view["image"])
               or sha(folder / view["image"]) != view["sha256"] for view in record["views"]):
            raise ValueError("Completed capture evidence changed")
        return record
    paths = sorted(folder.glob("frame-*.jpg"))
    sampled_frames = assignment.get("sampled_frames", plan["sampled_frames"])
    if len(paths) != sampled_frames + plan["warmup_frames"]:
        raise ValueError("Incomplete video sample; preserve it and capture a new session")
    angle_views = {}
    if plan.get("rotation_poses"):
        for pose, expected in zip(plan["rotation_poses"], [sampled_frames // 2, sampled_frames - sampled_frames // 2], strict=True):
            group = record.get("rotation", {}).get(pose, [])
            if len(group) != expected or {v["sector"] for v in group} != set(range(12)):
                raise ValueError("Two confirmed placements with full holder rotation are required")
            angle_views.update({v["image"]: {**v, "pose": pose} for v in group})
        if set(angle_views) != {p.name for p in paths[plan["warmup_frames"]:]}:
            raise ValueError("Rotation evidence does not match captured files")
    quality = json.loads((ROOT / "deployment/releases/unfertilized-trial-20261019/egg-grade/gate-policy.json").read_text())
    views = []
    for index, path in enumerate(paths[plan["warmup_frames"]:]):
        with decode_jpeg(path.read_bytes()) as image:
            if list(image.size) != plan["capture_size"]:
                raise ValueError("Unexpected webcam dimensions")
            measurements, flags = image_quality(image, quality)
            gray = np.asarray(image.convert("L"))
            h, w = gray.shape
            interior = gray[int(h * .2):int(h * .75), int(w * .35):int(w * .65)]
            views.append({"image": path.name, "view_index": index, "sha256": sha(path),
                          **angle_views.get(path.name, {}),
                          "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
                          "quality_measurements": measurements, "quality_flags": flags,
                          "interior_median": float(np.median(interior)),
                          "interior_fraction_below4": float(np.mean(interior < 4))})
    if len({view["pixel_sha256"] for view in views}) < (sampled_frames if plan.get("require_all_frames_distinct") else 3):
        raise ValueError("Video did not provide enough distinct frames")
    record.update(status="complete", physical_egg_id=f"{plan.get('physical_id_namespace', dataset.name)}:{record['egg_id']}",
                  batch_id=None, label_authority=plan["label_authority"], verified_incubation_hours=None,
                  model_used_for_label=False, capture_protocol=plan.get("capture_protocol", "emeet-video-1fps-after-2s-warmup-v1"),
                  completed_at=datetime.now(timezone.utc).isoformat(), views=views,
                  limitations=["Incubation records reported by operator; source documents not supplied",
                               "Multiple frames are correlated observations of one physical egg",
                               "No verified reject subtype samples in this collection"])
    write(record_path, record)
    return record


def capture(dataset, egg_id):
    dataset = dataset.resolve()
    if not re.fullmatch(r"(?:D16|D18|R)-[0-9]{2}", egg_id):
        raise ValueError("Invalid physical egg ID")
    plan_path = dataset / "collection-plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    assignment = plan["eggs"][egg_id]
    if plan.get("rotation_poses"):
        raise ValueError("Use capture_rotating_emeet.py for this study's two physical placements")
    if assignment["partition"] == "test":
        verify_candidate(dataset)
    if assignment["partition"] != "test" and (dataset / "candidate-lock.json").exists():
        raise ValueError("Candidate is locked; do not add development data to this study")
    if any(json.loads(p.read_text(encoding="utf-8-sig"))["status"] == "complete"
           for p in (dataset / "captures" / egg_id).glob("*/record.json")):
        raise ValueError("Egg already captured; do not count it as another physical egg")
    started = datetime.now(timezone.utc)
    folder = dataset / "captures" / egg_id / started.strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True)
    record_path = folder / "record.json"
    record = {"egg_id": egg_id, "source_label": assignment["label"], "partition": assignment["partition"],
              "camera": plan["camera"], "started_at": started.isoformat(), "status": "capturing",
              "plan_sha256": sha(plan_path), "model_used_for_label": False}
    write(record_path, record)
    sample_fps = plan.get("sample_fps", 1)
    frame_count = assignment.get("sampled_frames", plan["sampled_frames"]) + plan["warmup_frames"]
    command = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-f", "dshow",
               "-rtbufsize", "128M", "-use_wallclock_as_timestamps", "1", "-video_size", "1920x1080",
               "-framerate", "30", "-vcodec", "mjpeg", "-i", "video=" + plan["camera"],
               "-an", "-vf", f"fps={sample_fps}", "-frames:v", str(frame_count), "-q:v", "2", str(folder / "frame-%03d.jpg")]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=frame_count / sample_fps + 25,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        record = finish(dataset, folder)
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        record.update(status="failed", error=str(exc), stderr=(getattr(exc, "stderr", b"") or b"").decode(errors="replace")[-3000:])
        write(record_path, record)
        raise RuntimeError(f"Capture incomplete; preserved at {folder}. Close other camera apps and retry the same egg ID.") from exc
    return folder, record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--egg")
    action.add_argument("--finish", type=Path)
    args = parser.parse_args()
    folder, record = (args.finish, finish(args.dataset, args.finish)) if args.finish else capture(args.dataset, args.egg)
    print(json.dumps({"folder": str(folder), "egg": record["egg_id"], "partition": record["partition"],
                      "frames": len(record["views"]), "independent_eggs": 1,
                      "median_interior": float(np.median([v["interior_median"] for v in record["views"]]))}))
