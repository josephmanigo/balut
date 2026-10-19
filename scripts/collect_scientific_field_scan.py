"""Collect a preregistered egg using the existing three-view capture and CPU model."""
import argparse
from collections import Counter, defaultdict
from contextlib import redirect_stdout
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ml"), str(ROOT / "apps/edge_api")]
CLASSES = ["DAY_16", "DAY_18", "UNFERTILIZED"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def registration(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 90 or Counter(r["reference_class"] for r in rows) != Counter(dict.fromkeys(CLASSES, 30)):
        raise ValueError("Preregister 90 new eggs, 30 per class, before collecting predictions")
    if len({r["slot"] for r in rows}) != 90 or len({r["egg_id"] for r in rows}) != 90:
        raise ValueError("Slot and egg identities must be unique")
    batches = defaultdict(set); repeat_batches = defaultdict(set); repeats = Counter(); references = {}
    for row in rows:
        for key in ("egg_id", "batch_id", "assessor", "reference_file", "reference_method"):
            if not row[key].strip():
                raise ValueError(f"{row['slot']}: missing {key}")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", row["slot"]):
            raise ValueError("Slot must be a safe filename")
        if row["unseen_egg"] != "YES" or row["independent_reference"] != "YES":
            raise ValueError("Require independent reference labels and previously unseen eggs")
        reference = Path(row["reference_file"])
        if not reference.is_absolute() or not reference.is_file():
            raise ValueError("Reference file must be an existing absolute path")
        references[str(reference)] = sha(reference)
        if row["reference_class"] != "UNFERTILIZED":
            start = datetime.fromisoformat(row["incubation_start_utc"])
            if start.utcoffset() is None:
                raise ValueError("Incubation start requires a timezone")
        if row["repeats"] not in ("1", "10"):
            raise ValueError("Use one primary scan or ten predefined repeat scans")
        repeats[row["reference_class"]] += row["repeats"] == "10"
        if row["repeats"] == "10":
            repeat_batches[row["reference_class"]].add(row["batch_id"])
        batches[row["reference_class"]].add(row["batch_id"])
    if any(len(batches[c]) < 3 or repeats[c] != 3 or len(repeat_batches[c]) != 3 for c in CLASSES):
        raise ValueError("Require at least three batches and exactly three repeated eggs per class")
    return rows, references


def score_record(result):
    scores = [[v["sourceClassDecisionScores"][c] for c in CLASSES] for v in result["multiView"]["views"]]
    if len(scores) != 3:
        raise ValueError("Missing one of the three view score vectors")
    means = [sum(view[i] for view in scores) / 3 for i in range(3)]
    return {"score_vector": [s for view in scores for s in view],
            "score_vector_hex": [float(s).hex() for view in scores for s in view],
            "raw_scan_mean_scores": dict(zip(CLASSES, means)),
            "raw_scan_prediction": CLASSES[max(range(3), key=means.__getitem__)]}


def camera_status(camera):
    camera.reset_input_buffer(); camera.write(b"STATUS\n"); camera.flush()
    deadline = time.monotonic() + 2; lines = []
    while time.monotonic() < deadline:
        line = camera.readline(256).decode("ascii", errors="replace").strip()
        if line:
            lines.append(line)
            if line.startswith("BALUT_EXPOSURE "):
                return lines
    return lines + ["EXPOSURE_STATUS_NOT_RETURNED"]


def collect_attempt(camera, spinner, service, folder, *, capture, prepare, read_module):
    """Record every CRC-valid frame, including flush frames and later-discarded views."""
    folder.mkdir(); original = read_module.read_snapshot; frames = []
    record = {"started_at": datetime.now(timezone.utc).isoformat(), "result": None, "score_vector": None}
    def recorded_read(port):
        body = original(port)
        path = folder / f"sensor-frame-{len(frames)+1:02d}.jpg"; path.write_bytes(body)
        frames.append({"file": path.name, "sha256": sha(path), "received_at": datetime.now(timezone.utc).isoformat()})
        return body
    read_module.read_snapshot = recorded_read
    try:
        with (folder / "capture.log").open("w", encoding="utf-8") as log, redirect_stdout(log):
            views = capture(camera, spinner)
        bodies = []
        for i, (body, metadata) in enumerate(views, 1):
            prepared = prepare(body); path = folder / f"input-{i}.jpg"; path.write_bytes(prepared)
            write(folder / f"view-{i}.json", {**metadata, "prepared_sha256": sha(path)})
            bodies.append(prepared)
        result = service.predict_views(service.analysis_model_id, bodies)
        record["result"] = result
        record.update(score_record(result))
    except Exception as error:
        record["error"] = type(error).__name__ + ": " + str(error)
    finally:
        read_module.read_snapshot = original
        record.update(finished_at=datetime.now(timezone.utc).isoformat(), sensor_frames=frames)
        write(folder / "attempt.json", record)
    return record


def main(args):
    rows, references = registration(args.registration)
    row = next(r for r in rows if r["slot"] == args.slot)
    conditions = json.loads(args.conditions.read_text())
    for key in ("lighting", "position", "ambient_conditions", "operator", "camera_settings_policy"):
        if not isinstance(conditions.get(key), str) or not conditions[key].strip() or "FILL" in conditions[key]:
            raise ValueError(f"Document field condition: {key}")
    from balut_api.model_service import ModelService, active_registry
    registry = active_registry(ROOT)
    if sha(registry) != conditions["registry_sha256"]:
        raise ValueError("Loaded release differs from the preregistered model")
    plan = {"registration_sha256": sha(args.registration), "conditions_sha256": sha(args.conditions),
            "references": references, "registry_sha256": sha(registry), "collector_sha256": sha(__file__),
            "capture_sha256": sha(ROOT / "scripts/spinner_control.py"),
            "camera_bridge_sha256": sha(ROOT / "scripts/camera_usb_bridge.py"),
            "preprocessing_sha256": sha(ROOT / "apps/edge_api/balut_api/automatic_box.py"),
            "inference_sha256": sha(ROOT / "apps/edge_api/balut_api/model_service.py"),
            "quality_gates_sha256": sha(ROOT / "apps/edge_api/balut_api/selective_gate.py"),
            "aggregation_functions": "view_consensus and combine_views in the hashed model_service.py",
            "measurement_code_sha256": sha(ROOT / "ml/balut_ml/scientific_metrics.py"),
            "python_version": sys.version,
            "runtime_versions": {name: importlib.metadata.version(name) for name in ("numpy", "onnxruntime", "Pillow", "pyserial")},
            "maximum_repeat_window_seconds": 600, "strict_score_tolerance": 0,
            "raw_scan_rule": "argmax arithmetic mean of three raw score vectors; fixed class-order tie break",
            "app_decision_rule": "unchanged ModelService.predict_views quality gates and three-view consensus",
            "primary_denominator": "90 preregistered eggs, first attempt only; capture failures count unsuccessful",
            "repeats_are_independent_eggs": False}
    if args.validate_only:
        print(json.dumps({"registration_valid": True, "hardware_opened": False, "plan": plan}, indent=2)); return
    if row["reference_class"] != "UNFERTILIZED":
        hours = (datetime.now(timezone.utc) - datetime.fromisoformat(row["incubation_start_utc"])).total_seconds() / 3600
        lower = 384 if row["reference_class"] == "DAY_16" else 432
        if not lower <= hours < lower + 24:
            raise ValueError("Current elapsed incubation age is outside the preregistered 24-hour age bin")
    args.output.mkdir(parents=True, exist_ok=True)
    lock = args.output / "study-lock.json"
    if lock.exists():
        if json.loads(lock.read_text()) != plan:
            raise ValueError("Study configuration changed after first capture")
    else:
        write(lock, plan)
    folder = args.output / args.slot
    folder.mkdir()  # Never replace an attempted egg, including failed captures.
    write(folder / "registration.json", row)
    from balut_api.automatic_box import prepare_camera_frame
    from balut_ml.scientific_metrics import repeatability
    import camera_usb_bridge
    import spinner_control
    service = ModelService(); camera = spinner = None; records = []
    try:
        service.load(registry, plan["registry_sha256"])
        camera = camera_usb_bridge.open_camera(); spinner = spinner_control.open_spinner()
        started = time.monotonic()
        for number in range(1, int(row["repeats"]) + 1):
            if time.monotonic() - started >= 600:
                records.append({"repeat": number, "result": None, "score_vector": None,
                                "error": "Repeat window expired", "started_at": datetime.now(timezone.utc).isoformat()})
            else:
                status = camera_status(camera)
                record = collect_attempt(camera, spinner, service, folder / f"attempt-{number:02d}",
                                         capture=spinner_control.capture_views, prepare=prepare_camera_frame,
                                         read_module=camera_usb_bridge)
                record.update(repeat=number, camera_status=status, elapsed_seconds=time.monotonic() - started)
                if record["elapsed_seconds"] > 600:
                    record.update(protocol_error="Repeat window exceeded", score_vector=None)
                records.append(record)
            with (folder / "attempts.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(records[-1], allow_nan=False) + "\n")
            print(f"{row['slot']}: attempt {number}/{row['repeats']} saved", flush=True)
    except Exception as error:
        write(folder / "fatal-error.json", {"error": type(error).__name__ + ": " + str(error),
              "at": datetime.now(timezone.utc).isoformat(), "remaining_attempts_not_collected": int(row["repeats"]) - len(records)})
        raise
    finally:
        cleanup_errors = []
        if spinner is not None:
            try:
                spinner.command("RUN")
            except Exception as error:
                cleanup_errors.append("Motor resume failed: " + str(error))
            finally:
                try:
                    spinner.close()
                except Exception as error:
                    cleanup_errors.append("Spinner close failed: " + str(error))
        if camera is not None:
            try:
                camera.close()
            except Exception as error:
                cleanup_errors.append("Camera close failed: " + str(error))
        service.close()
        write(folder / "summary.json", {"slot": row["slot"], "scope": "FRESH_PHYSICAL_SCANS",
              **repeatability(records, int(row["repeats"])), "repeat_test_applicable": row["repeats"] == "10",
              "cleanup_errors": cleanup_errors})
        write(folder / "evidence-lock.json", {"artifacts": {str(p.relative_to(folder)): sha(p) for p in folder.rglob("*") if p.is_file()}})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registration", type=Path, required=True)
    parser.add_argument("--conditions", type=Path, required=True)
    parser.add_argument("--slot", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    main(parser.parse_args())
