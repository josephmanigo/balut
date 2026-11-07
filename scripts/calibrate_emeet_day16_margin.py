"""Package a Day 16 margin recalibration of the locked EMEET model."""
import shutil
import tempfile
from pathlib import Path

import numpy as np

from package_emeet_release import (
    CLASSES, RELEASE as PARENT, ROOT, STUDY, ModelService, check_scanner, locked_artifacts, read, sha256_file, write,
)
from balut_api.model_service import decode_jpeg
from balut_api.selective_gate import image_quality

RELEASE = "emeet-mobilenetv2-20261107-r2"


def eligible_views(run, artifacts, policy):
    rows = read(artifacts["development-manifest.json"])
    inputs = read(run / "calibration/serving-inputs.json")
    with np.load(artifacts["calibration/development-cpu.npz"], allow_pickle=False) as data:
        scores, features, labels, train = (data[k] for k in ("scores", "features", "truth", "train"))
    if (len(inputs) != len(rows) or any(row["partition"] not in {"train", "validation"} for row in rows)
            or not np.array_equal(train, [row["partition"] == "train" for row in rows])
            or not np.array_equal(labels, [CLASSES.index(row["source_label"]) for row in rows])):
        raise ValueError("Expected the original egg-disjoint development split")
    with np.load(artifacts["calibration/training-references.npz"], allow_pickle=False) as bank:
        day16 = bank["features"][bank["labels"] == CLASSES.index("DAY_16")]
    ordered = np.sort(scores, axis=1)
    margins = ordered[:, -1] - ordered[:, -2]
    # Only these views can change. All other classes, quality checks and similarity thresholds stay fixed.
    candidates = np.flatnonzero((scores.argmax(axis=1) == CLASSES.index("DAY_16")) &
                                (margins > 0) & (margins < policy["minimum_margin"]["DAY_16"]))
    eligible = []
    for i in candidates:
        if (features[i] @ day16.T).max() < policy["minimum_training_cosine"]["DAY_16"]:
            continue
        source = run / "calibration/inputs" / (rows[i]["source_sha256"] + ".jpg")
        if inputs[i]["source_sha256"] != rows[i]["source_sha256"] or sha256_file(source) != inputs[i]["serving_sha256"]:
            raise ValueError("Serving input mismatch")
        if not image_quality(decode_jpeg(source.read_bytes()), policy)[1]:
            eligible.append(i)
    return margins, labels, train, np.array(eligible, dtype=int)


def main():
    run = ROOT / "ml/runs" / STUDY
    artifacts = locked_artifacts(run)
    parent = ROOT / "deployment/releases" / PARENT
    target = parent.parent / RELEASE
    if target.exists():
        raise FileExistsError("Keep packaged releases immutable")
    policy = read(artifacts["calibration/gate-policy.json"])
    old = policy["minimum_margin"]["DAY_16"]
    margins, labels, train, eligible = eligible_views(run, artifacts, policy)
    development = eligible[train[eligible]]
    options = []
    for hundredths in range(1, int(old * 100) + 1):
        cutoff = hundredths / 100
        added = development[margins[development] >= cutoff]
        if len(added) and np.all(labels[added] == CLASSES.index("DAY_16")):
            options.append((len(added), cutoff))
    if not options:
        raise ValueError("No training gain without new wrong acceptances")
    gain, cutoff = max(options)  # On equal gain retain the stricter cutoff.
    val_changes = eligible[(~train[eligible]) & (margins[eligible] >= cutoff)]
    if len(val_changes):
        raise ValueError("Recheck validation before releasing a policy that changes any validation decision")
    with tempfile.TemporaryDirectory(dir=target.parent) as temporary:
        build = Path(temporary) / RELEASE
        shutil.copytree(parent, build, ignore=shutil.ignore_patterns("best.onnx"))
        directory = build / "egg-grade"
        shutil.copyfile(artifacts["best.onnx"], directory / "best.onnx")
        policy["minimum_margin"]["DAY_16"] = cutoff
        policy["calibration_scope"] = "Day 16 margin recalibrated on training eggs; verified on grouped validation."
        write(directory / "gate-policy.json", policy)
        config = read(directory / "config.json")
        config["parent_candidate_lock_sha256"] = config.pop("candidate_lock_sha256")
        config["gate_policy_sha256"] = sha256_file(directory / "gate-policy.json")
        write(directory / "config.json", config)
        registry = read(build / "registry.json")
        registry["release_id"] = RELEASE
        entry = registry["models"][0]
        for key in ("config", "gate_policy"):
            entry[key]["sha256"] = sha256_file(build / entry[key]["path"])
        write(build / "registry.json", registry)
        digest = sha256_file(build / "registry.json")
        (build / "registry.sha256").write_text(digest + "\n", encoding="ascii", newline="\n")
        service = ModelService()
        service.load(build / "registry.json", digest)
        checks = check_scanner(service, run, artifacts)
        service.close()
        write(build / "verification.json", {
            "release": RELEASE, "parent_release": PARENT, "registry_sha256": digest,
            "model_sha256": entry["model"]["sha256"], "parent_gate_sha256": sha256_file(artifacts["calibration/gate-policy.json"]),
            "gate_sha256": entry["gate_policy"]["sha256"],
            "previous_day16_margin": old, "day16_margin": cutoff, "selection": "Training-only 0.01 grid, maximize additional correct views with zero additional wrong views; stricter margin breaks ties.",
            "additional_correct_train_views": gain, "additional_wrong_train_views": 0,
            "train_views": int(train.sum()), "validation_views": int((~train).sum()), "changed_validation_views": 0,
            "three_view_software_checks": checks, "dark_input_requests_recapture": True,
            "field_accuracy_established": False, "operational_use_authorized": False,
        })
        build.rename(target)
    print(f"{PARENT} -> {RELEASE}, Day 16 margin {old} -> {cutoff}")


if __name__ == "__main__":
    main()
