"""Measure ten fresh three-view EMEET attempts per preselected reserved egg."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "ml"), str(ROOT / "apps/edge_api")]
import numpy as np
import onnxruntime as ort
from balut_api.model_service import decode_jpeg, preprocess, view_consensus
from balut_api.selective_gate import decide
from balut_ml.scientific_metrics import repeatability
from scripts.capture_emeet_egg import finish, sha, verify_candidate, write

SELECTED_EGGS = ("D16-17", "D18-09")
REPEATS = 10


def summarize(attempts, truth):
    result = repeatability(attempts, REPEATS)
    valid = [a for a in attempts if a.get("result") is not None]
    correct = sum(a["result"]["sourcePrediction"] == truth for a in valid)
    result.update(correct_attempts=correct, correct_over_attempts=correct / len(attempts) if attempts else None,
                  class_counts=dict(Counter(a["result"]["sourcePrediction"] or "UNCLASSIFIED" for a in valid)),
                  median_attempt_seconds=float(np.median([a["elapsed_seconds"] for a in attempts])) if attempts else None,
                  expected_repeats=REPEATS)
    return result


def load_engine(run):
    policy = json.loads((run / 'calibration/gate-policy.json').read_text())
    with np.load(run / 'calibration/training-references.npz', allow_pickle=False) as bank:
        references, labels = bank['features'], bank['labels']
    options = ort.SessionOptions(); options.intra_op_num_threads = 4; options.inter_op_num_threads = 1
    session = ort.InferenceSession(str(run / 'best.onnx'), sess_options=options, providers=['CPUExecutionProvider'])
    return session, policy, references, labels


def score_view(engine, pixels, image):
    session, policy, references, labels = engine
    scores, embedding = session.run(None, {'images': pixels})
    return {'scores': scores[0].tolist(), **decide(scores[0], embedding[0], image, policy, references, labels)}


def combine_views(views):
    prediction, reasons, accepted = view_consensus(views, [v['sha256'] for v in views])
    return {'sourcePrediction': prediction, 'analysisOutcome': 'CLASSIFIED' if prediction else 'RECAPTURE_REQUIRED',
            'recaptureRequested': prediction is None, 'recaptureReasons': reasons, 'accepted_views': accepted}


def run_repeats(dataset, egg, study=None, candidate_path=None):
    lock_path = candidate_path or dataset / 'candidate-lock.json'
    lock = verify_candidate(dataset, lock_path)
    baseline = None
    if candidate_path and not study:
        raise ValueError('A separate physical protocol is required for paired retesting')
    plan = json.loads((dataset / "collection-plan.json").read_text())
    selected_eggs = list(SELECTED_EGGS)
    protocol_sha = None
    count_all_attempts = False
    if study is not None:
        protocol = json.loads((study / "protocol.json").read_text())
        protocol_sha = sha(study / "protocol.json")
        count_all_attempts = protocol.get("count_all_scheduled_attempts") is True
        selected_eggs = protocol["selected_eggs"]
        heldout = {key for key, value in plan["eggs"].items() if value["partition"] == "test"}
        if (len(selected_eggs) != len(set(selected_eggs)) or set(selected_eggs) != heldout
                or protocol["candidate_lock_sha256"] != sha(lock_path)
                or protocol["attempts_per_egg"] != REPEATS):
            raise ValueError("Physical study must preserve the candidate, all reserved egg identities and ten attempts per egg")
        if candidate_path:
            if protocol.get('imported_original_physical_records') != [] or protocol.get('baseline_candidate_lock_sha256') != sha(dataset/'candidate-lock.json'):
                raise ValueError('Paired retesting needs fresh-only captures and the original locked comparator')
            baseline = load_engine(Path(verify_candidate(dataset)['run']))
    if egg not in selected_eggs or plan["eggs"][egg]["partition"] != "test":
        raise ValueError("Use a reserved egg listed in the chosen physical test protocol")
    captured = [p for p in (dataset / "captures" / egg).glob("*/record.json") if json.loads(p.read_text())["status"] == "complete"]
    if len(captured) != 1:
        raise ValueError("Complete this egg's reserved dataset capture before repeating scans")
    if candidate_path:
        # Fresh paired retests need the registered identity, not the previously stored test photographs.
        identity=json.loads(captured[0].read_text())
        if (identity['egg_id'] != egg or identity['partition'] != 'test' or identity['source_label'] != plan['eggs'][egg]['label']
                or identity['physical_egg_id'] != f"{plan.get('physical_id_namespace',dataset.name)}:{egg}"
                or identity['plan_sha256'] != sha(dataset/'collection-plan.json')):
            raise ValueError('Reserved egg identity differs from the frozen plan')
    else:
        identity = finish(dataset, captured[0].parent)
    run = Path(lock["run"])
    study_root = study if study is not None else run / "repeatability"
    output = study_root / egg
    output.mkdir(parents=True, exist_ok=False)
    engine = load_engine(run)
    config = {"normalization_mean": [.485, .456, .406], "normalization_std": [.229, .224, .225]}
    record = {"egg_id": egg, "physical_egg_id": identity["physical_egg_id"], "truth": identity["source_label"],
              "candidate_lock_sha256": sha(lock_path), "selected_eggs": selected_eggs,
              "physical_study_protocol_sha256": protocol_sha,
              "scope": "Fresh separate camera acquisitions in the same holder, local CPU model and production decision rules; not a deployed browser or repositioning test",
              "rotation_angles_verified": False, "new_independent_eggs": 0, "included_in_training_dataset": False,
              "capture_protocol": "Each attempt reopens EMEET, samples 1fps, discards two warmup frames, then analyzes three fresh views",
              "attempts": []}
    if baseline:
        record['baseline_candidate_lock_sha256'] = sha(dataset/'candidate-lock.json')
    write(output / "record.json", record)
    seen_pixels = set()
    for number in range(1, REPEATS + 1):
        folder = output / f"attempt-{number:02d}"
        folder.mkdir()
        started = time.perf_counter()
        attempt = {"number": number, "started_at": datetime.now(timezone.utc).isoformat(), "result": None, "score_vector": None}
        try:
            command = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-f", "dshow", "-rtbufsize", "128M",
                       "-use_wallclock_as_timestamps", "1", "-video_size", "1920x1080", "-framerate", "30", "-vcodec", "mjpeg",
                       "-i", "video=" + plan["camera"], "-an", "-vf", "fps=1", "-frames:v", "5", "-q:v", "2", str(folder / "frame-%03d.jpg")]
            subprocess.run(command, check=True, capture_output=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            frames = sorted(folder.glob("frame-*.jpg"))
            if len(frames) != 5:
                raise ValueError("Incomplete fresh acquisition")
            views, control_views = [], []
            for frame in frames[2:]:
                body = frame.read_bytes()
                with decode_jpeg(body) as image:
                    digest = hashlib.sha256(image.tobytes()).hexdigest()
                    if digest in seen_pixels or list(image.size) != plan["capture_size"]:
                        raise ValueError("Repeated pixels or unexpected camera dimensions")
                    seen_pixels.add(digest)
                    tensor = preprocess(body, config); file_hash = sha(frame)
                    views.append({'path': str(frame), 'sha256': file_hash, 'pixel_sha256': digest, **score_view(engine,tensor,image)})
                    if baseline: control_views.append({'sha256': file_hash, **score_view(baseline,tensor,image)})
            if baseline: attempt.update(baseline_views=control_views, baseline_result=combine_views(control_views))
            attempt.update(views=views, score_vector=[s for v in views for s in v['scores']], result=combine_views(views))
        except (subprocess.SubprocessError, OSError, ValueError, RuntimeError) as exc:
            attempt.update(error=str(exc), stderr=(getattr(exc, "stderr", b"") or b"").decode(errors="replace")[-2000:])
        attempt["elapsed_seconds"] = time.perf_counter() - started
        record["attempts"].append(attempt)
        record["metrics"] = summarize(record["attempts"], record["truth"])
        write(output / "record.json", record)
        print(json.dumps({"egg": egg, "attempt": number, "result": attempt["result"], "failed": attempt["result"] is None}), flush=True)
        if attempt["result"] is None and not count_all_attempts:
            break
    verify_candidate(dataset,lock_path)
    if study is not None and sha(study / "protocol.json") != protocol_sha:
        raise ValueError("Physical study protocol changed during capture")
    records = [json.loads(p.read_text()) for p in study_root.glob("*/record.json")]
    write(study_root / "metrics.json", {"selected_eggs": selected_eggs, "eggs_tested": len(records),
          "per_egg": [{"egg_id": r["egg_id"], "truth": r["truth"], "scope": r["scope"], **r["metrics"]} for r in records],
          "field_accuracy_established": False, "fresh_physical_reject_eggs": 0})
    if len(record["attempts"]) != REPEATS or (record["metrics"]["failures"] and not count_all_attempts):
        raise RuntimeError("Incomplete repeat study; failed attempts preserved, not silently retried or removed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--egg", required=True)
    parser.add_argument("--study", type=Path, help="Separate physical-only study with a frozen protocol; preserves the original repeat study")
    parser.add_argument('--candidate', type=Path, help='Locked research model for same-view paired physical retesting')
    args = parser.parse_args()
    run_repeats(args.dataset.resolve(), args.egg, args.study.resolve() if args.study else None, args.candidate.resolve() if args.candidate else None)
