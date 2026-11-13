"""Count fresh physical scan attempts, keeping abstentions and acquisition failures."""
import hashlib
import json
from pathlib import Path

from scripts.capture_emeet_egg import sha, verify_candidate, write
from scripts.repeat_emeet_candidate import REPEATS, summarize, combine_views
from balut_api.model_service import decode_jpeg

CLASSES = ("DAY_16", "DAY_18", "REJECT")
OUTCOMES = (*CLASSES, "UNCLASSIFIED", "ACQUISITION_FAILURE")


def outcome(attempt):
    result = attempt.get("result")
    return "ACQUISITION_FAILURE" if result is None else result["sourcePrediction"] or "UNCLASSIFIED"


def count_attempts(records, first_only=False):
    matrix = [[0] * len(OUTCOMES) for _ in CLASSES]
    for record in records:
        attempts = record["attempts"][:1] if first_only else record["attempts"]
        for attempt in attempts:
            matrix[CLASSES.index(record["truth"])][OUTCOMES.index(outcome(attempt))] += 1
    total = sum(map(sum, matrix))
    correct = sum(matrix[i][i] for i in range(3))
    accepted = sum(sum(row[:3]) for row in matrix)
    per_class = []
    for i, label in enumerate(CLASSES):
        support = sum(matrix[i]); tp = matrix[i][i]
        fp = sum(row[i] for row in matrix) - tp; fn = support - tp
        per_class.append({"class": label, "support": support, "TP": tp, "FP": fp, "FN": fn,
                          "precision": tp / (tp + fp) if support and tp + fp else 0. if support else None,
                          "recall": tp / support if support else None,
                          "f1": 2 * tp / (2 * tp + fp + fn) if support else None})
    represented = [row for row in per_class if row["support"]]
    return {"attempts": total, "correct": correct, "wrong_classified": accepted - correct,
            "unclassified": sum(row[3] for row in matrix), "acquisition_failures": sum(row[4] for row in matrix),
            "accuracy": correct / total if total else None, "classified": accepted,
            "coverage": accepted / total if total else None,
            "accuracy_among_classified": correct / accepted if accepted else None,
            "class_order": list(CLASSES), "outcome_order": list(OUTCOMES), "confusion_matrix": matrix,
            "per_class": per_class,
            "macro_f1_represented_classes": sum(row["f1"] for row in represented) / len(represented) if represented else None,
            "unrepresented_classes": [row["class"] for row in per_class if not row["support"]],
            "counting": "Unclassified and acquisition failures count as incorrect and as FN for the known class; unsupported classes are not scored"}


def load_physical_study(study, dataset, candidate_path=None):
    verify_candidate(dataset,candidate_path)
    candidate_hash = sha(candidate_path or dataset / "candidate-lock.json")
    collection = json.loads((dataset / "collection-plan.json").read_text())
    protocol_path = study / "protocol.json"
    protocol = json.loads(protocol_path.read_text())
    if protocol["candidate_lock_sha256"] != candidate_hash or protocol["attempts_per_egg"] != REPEATS:
        raise ValueError("Physical study candidate or attempt count changed")
    imported = {r["egg_id"]: r["record_sha256"] for r in protocol["imported_original_physical_records"]}
    baseline_hash = sha(dataset/'candidate-lock.json') if candidate_path else None
    if candidate_path and (imported or protocol.get('baseline_candidate_lock_sha256') != baseline_hash):
        raise ValueError('Paired physical study must use only fresh scans and the original comparator')
    heldout = {egg for egg, item in collection["eggs"].items() if item["partition"] == "test"}
    if len(protocol["selected_eggs"]) != len(heldout) or set(protocol["selected_eggs"]) != heldout:
        raise ValueError("Physical study must include the complete reserved cohort")
    records, pixels = [], set()
    for egg in protocol["selected_eggs"]:
        path = study / egg / "record.json"
        if not path.exists():
            continue
        record = json.loads(path.read_text())
        if (record["egg_id"] != egg or record["candidate_lock_sha256"] != candidate_hash
                or record["truth"] != collection["eggs"][egg]["label"]
                or record["physical_egg_id"] != f"{collection.get('physical_id_namespace', dataset.name)}:{egg}"
                or not 0 < len(record["attempts"]) <= REPEATS):
            raise ValueError("Physical scan identity, model or attempt count changed")
        if egg in imported:
            if sha(path) != imported[egg]:
                raise ValueError("Imported original physical evidence changed")
        elif record["physical_study_protocol_sha256"] != sha(protocol_path):
            raise ValueError("Physical study protocol changed")
        for index, attempt in enumerate(record["attempts"], start=1):
            if attempt["number"] != index or (attempt.get("result") is not None and len(attempt.get("views", [])) != 3):
                raise ValueError("Unexpected attempt order or camera view count")
            if candidate_path and attempt.get('result') is not None:
                controls = attempt.get('baseline_views',[]); main = attempt['views']
                if (record.get('baseline_candidate_lock_sha256') != baseline_hash
                        or [v['sha256'] for v in controls] != [v['sha256'] for v in main]
                        or attempt.get('baseline_result') != combine_views(controls) or attempt['result'] != combine_views(main)):
                    raise ValueError('Physical comparison does not match the same three views and locked decision rule')
            for view in attempt.get("views", []):
                body = Path(view["path"]).read_bytes()
                with decode_jpeg(body) as image:
                    digest = hashlib.sha256(image.tobytes()).hexdigest()
                if digest in pixels or digest != view["pixel_sha256"] or hashlib.sha256(body).hexdigest() != view["sha256"]:
                    raise ValueError("Physical camera evidence changed")
                pixels.add(digest)
        records.append(record)
    if len({r["physical_egg_id"] for r in records}) != len(records):
        raise ValueError("The same physical egg appears twice")
    seal = {"protocol_sha256": sha(protocol_path), "candidate_lock_sha256": candidate_hash,
            "record_sha256": {r["egg_id"]: sha(study / r["egg_id"] / 'record.json') for r in records}}
    seal_path = study / 'physical-evaluation-lock.json'
    if seal_path.exists() and json.loads(seal_path.read_text()) != seal:
        raise ValueError("Completed physical evidence changed")
    if not seal_path.exists() and len(records) == len(heldout) and all(len(r['attempts']) == REPEATS for r in records):
        write(seal_path, seal)
    summary = {**seal,
               "scope": protocol["scope"], "planned_eggs": len(protocol["selected_eggs"]),
               "eggs_tested": len(records), "planned_attempts": len(protocol["selected_eggs"]) * REPEATS,
               "completed_eggs": sum(len(r["attempts"]) == REPEATS for r in records),
               "primary_first_attempt_per_egg": count_attempts(records, first_only=True),
               "repeated_attempts": count_attempts(records),
               "unique_scored_camera_views": len(pixels),
               "scan_log": [{"egg_id": r["egg_id"], "truth": r["truth"], "attempt": a["number"],
                             "outcome": outcome(a), "seconds": a["elapsed_seconds"],
                             "reasons": (a.get("result") or {}).get("recaptureReasons", [])}
                            for r in records for a in r["attempts"]],
               "per_egg": [{"egg_id": r["egg_id"], "truth": r["truth"],
                            "imported_original_session": r["egg_id"] in imported,
                            "first_outcome": outcome(r["attempts"][0]),
                            **summarize(r["attempts"], r["truth"])} for r in records],
               "physical_reject_eggs": sum(r["truth"] == "REJECT" for r in records),
               "new_independent_eggs": 0, "field_accuracy_established": False,
               "measurement_scope": "Physical EMEET camera + local locked MobileNetV2 + production decision rules; no saved-dataset replay, deployed-browser, verified repositioning, or production-field test"}
    if candidate_path:
        controls = [{'truth':r['truth'],'attempts':[{'result':a.get('baseline_result')} for a in r['attempts']]} for r in records]
        summary['paired_baseline'] = {'candidate_lock_sha256':baseline_hash,
            'primary_first_attempt_per_egg':count_attempts(controls,first_only=True),'repeated_attempts':count_attempts(controls),
            'per_egg':{r['egg_id']:count_attempts([c]) for r,c in zip(records,controls,strict=True)}}
        for log,control in zip(summary['scan_log'],(a for r in controls for a in r['attempts']),strict=True):
            log['baseline_outcome']=outcome(control)
    return summary
