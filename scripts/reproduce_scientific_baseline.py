"""Reproduce the active release on the historical population without fitting."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import evaluate_unfertilized_holdout as evaluation

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "ml/runs/baseline-reproduction-20261019-v2"
PRIOR = ROOT / "ml/runs/unfertilized-heldout-20261019-v1"


def main(output):
    active = (ROOT / "deployment/active-release.txt").read_text().strip()
    if active != evaluation.RELEASE.name:
        raise ValueError("Active release changed; establish a new baseline protocol")
    prior_lock = json.loads((PRIOR / "evaluation-lock.json").read_text())
    assert all(evaluation.sha(PRIOR / name) == digest for name, digest in prior_lock["artifacts"].items())
    global OUT
    OUT = output.resolve()
    evaluation.OUT = OUT
    evaluation.main()
    old = json.loads((PRIOR / "metrics.json").read_text())["overall"]
    new = json.loads((OUT / "metrics.json").read_text())["overall"]
    first = [json.loads(line) for line in (PRIOR / "outcomes.jsonl").read_text().splitlines()]
    second = [json.loads(line) for line in (OUT / "outcomes.jsonl").read_text().splitlines()]
    assert len(first) == len(second) == 649
    differences = []
    for a, b in zip(first, second, strict=True):
        assert a["source_sha256"] == b["source_sha256"] and a["serving_jpeg_sha256"] == b["serving_jpeg_sha256"]
        differences.extend(abs(a["sourceClassDecisionScores"][label] - b["sourceClassDecisionScores"][label]) for label in evaluation.CLASSES)
    assert (ROOT / "deployment/active-release.txt").read_text().strip() == active
    receipt = {"completed_at": datetime.now(timezone.utc).isoformat(), "active_release": active,
               "scope": "REPRODUCTION_OF_PREVIOUSLY_INSPECTED_HISTORICAL_BASELINE_NOT_FRESH_FINAL_TEST",
               "same_population": True, "all_summary_metrics_identical": old == new,
               "maximum_full_precision_score_difference_from_previous_run": max(differences),
               "new_evaluation_lock_sha256": evaluation.sha(OUT / "evaluation-lock.json"),
               "previous_evaluation_lock_sha256": evaluation.sha(PRIOR / "evaluation-lock.json"),
               "source_sha256": evaluation.sha(Path(__file__)), "fitting_or_threshold_changes": False}
    evaluation.write(OUT / "reproduction.json", receipt)
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUT)
    main(parser.parse_args().output)
