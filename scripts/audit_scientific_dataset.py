"""Recheck file, pixel, identity, source-family and near-duplicate split evidence."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ml"), str(ROOT / "apps/edge_api")]
import numpy as np
from PIL import Image, ImageOps
from balut_ml.public_data import near_duplicate
from balut_ml.scientific_metrics import classification_metrics, cluster_intervals

DATA = ROOT / "data/local/retained-camera-epochs-reject-20261019"
OUT = ROOT / "output/scientific-audit-20261019/dataset-audit"
BASELINE = ROOT / "ml/runs/baseline-reproduction-20261019-v3"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def crossing(rows, key):
    groups = defaultdict(list)
    for index, row in enumerate(rows):
        identity = key(row)
        if identity:
            groups[identity].append(index)
    crossed = [{"identity": identity, "row_indexes": values, "partitions": sorted({rows[i]["partition"] for i in values}),
                "labels": sorted({rows[i]["source_label"] for i in values})}
               for identity, values in groups.items() if len({rows[i]["partition"] for i in values}) > 1]
    return {"known_groups": len(groups), "repeated_groups": sum(len(v) > 1 for v in groups.values()),
            "cross_partition_groups": len(crossed), "crossings": crossed}


def main():
    if OUT.exists():
        raise FileExistsError("Preserve completed or interrupted audit evidence")
    rows = [json.loads(line) for line in (DATA / "manifest.jsonl").read_text().splitlines()]
    assert sha(DATA / "manifest.jsonl") == json.loads((DATA / "audit.json").read_text())["manifest_sha256"]
    OUT.mkdir()
    write(OUT / "protocol.json", {"started_at": datetime.now(timezone.utc).isoformat(), "images": len(rows),
          "manifest_sha256": sha(DATA / "manifest.jsonl"), "source_sha256": sha(Path(__file__)),
          "near_duplicate_rule": "Existing public_data.near_duplicate: 64-bit dHash Hamming<=3 AND mean absolute RGB thumbnail difference<=6/255",
          "near_duplicate_scope": "Every cross-partition pair; flag candidates, do not equate visual similarity with proof of shared egg identity",
          "no_training_or_threshold_changes": True, "confidence_interval": "5000 complete-egg/source-family cluster bootstrap draws, seed42"})
    thumbnails = []; hashes = []; mismatches = []; spans = defaultdict(list)
    for index, row in enumerate(rows):
        path = Path(row["image_path"])
        if sha(path) != row["source_sha256"]:
            mismatches.append({"row": index, "type": "source_sha256"})
        with Image.open(path) as source:
            rgb = ImageOps.exif_transpose(source).convert("RGB"); rgb.load()
            pixel = hashlib.sha256(str(rgb.size).encode() + rgb.tobytes()).hexdigest()
            if pixel != row["pixel_sha256"]:
                mismatches.append({"row": index, "type": "pixel_sha256"})
            thumbnails.append(np.asarray(rgb.resize((32, 32)), dtype=np.int16))
            gray = rgb.convert("L").resize((9, 8)).tobytes()
            hashes.append(sum(int(gray[y*9+x] > gray[y*9+x+1]) << (y*8+x) for y in range(8) for x in range(8)))
        timestamp = row.get("capture_record", {}).get("captured_at")
        if row.get("physical_egg_id") and timestamp:
            spans[row["physical_egg_id"]].append(datetime.fromisoformat(timestamp.replace("Z", "+00:00")))
        if (index + 1) % 500 == 0:
            print(json.dumps({"verified_images": index + 1, "total": len(rows)}), flush=True)
    checks = {
        "file_hash": crossing(rows, lambda r:r["source_sha256"]),
        "decoded_pixel_hash": crossing(rows, lambda r:r["pixel_sha256"]),
        "physical_egg": crossing(rows, lambda r:r.get("physical_egg_id")),
        "recorded_source_family": crossing(rows, lambda r:r.get("physical_egg_id") or r["duplicate_group"]),
        "source_original_filename": crossing(rows, lambda r:(r["source_dataset"] + ":" + r["source_stem"]) if r.get("source_stem") else None),
        "original_source_image": crossing(rows, lambda r:r.get("crop_provenance", {}).get("source_image_sha256")),
        "known_batch": crossing(rows, lambda r:r.get("batch_id")),
    }
    near = []
    for i, row in enumerate(rows):
        for j in range(i):
            if row["partition"] == rows[j]["partition"]:
                continue
            if near_duplicate(hashes[i], hashes[j], thumbnails[i], thumbnails[j]):
                near.append({"row_a": j, "row_b": i, "hamming": (hashes[i] ^ hashes[j]).bit_count(),
                             "rgb_mean_absolute_difference": float(np.abs(thumbnails[i]-thumbnails[j]).mean()),
                             "same_recorded_egg": bool(row.get("physical_egg_id")) and row.get("physical_egg_id") == rows[j].get("physical_egg_id"),
                             "labels": [rows[j]["source_label"], row["source_label"]], "partitions": [rows[j]["partition"], row["partition"]],
                             "source_sha256": [rows[j]["source_sha256"], row["source_sha256"]]})
    write(OUT / "near-duplicate-candidates.json", near)
    splits = []
    for partition in ("train", "validation", "test"):
        subset = [r for r in rows if r["partition"] == partition]
        for label in ("DAY_16", "DAY_18", "UNFERTILIZED"):
            selected = [r for r in subset if r["source_label"] == label]
            total_class = sum(r["source_label"] == label for r in rows)
            splits.append({"partition": partition, "class": label, "images": len(selected), "percent_of_entire_dataset":100*len(selected)/len(rows),
                           "percent_of_class":100*len(selected)/total_class,
                           "known_physical_eggs":len({r["physical_egg_id"] for r in selected if r.get("physical_egg_id")}),
                           "public_source_families":len({r["duplicate_group"] for r in selected if not r.get("physical_egg_id")}),
                           "known_batches":len({r["batch_id"] for r in selected if r.get("batch_id")})})
    fold_bank = json.loads((ROOT / "ml/runs/grouped-camera-20261019/folds.json").read_text())
    development = [r for r in rows if r["partition"] != "test"]
    np.testing.assert_array_equal(fold_bank["source_sha256"], [r["source_sha256"] for r in development])
    fold_groups = defaultdict(set)
    for r, fold in zip(development, fold_bank["fold"], strict=True):
        fold_groups[r.get("physical_egg_id") or r["duplicate_group"]].add(fold)
    fold_crossings = {key:sorted(value) for key,value in fold_groups.items() if len(value)>1}
    report = {"images":len(rows), "hash_mismatches":mismatches, "identity_checks":checks,
              "near_duplicate_candidate_pairs_across_partitions":len(near), "near_duplicate_pairs_are_not_confirmed_identity_leakage":True,
              "grouped_development_fold_crossings":fold_crossings, "splits":splits,
              "source_class_counts":dict(Counter(r["source_dataset"] + ":" + r["source_label"] for r in rows)),
              "missing_batch_id_images":sum(not r.get("batch_id") for r in rows),
              "missing_physical_egg_id_images":sum(not r.get("physical_egg_id") for r in rows),
              "independently_verified_incubation_hours_images":sum(r.get("verified_incubation_hours") is not None for r in rows),
              "excluded_vendor_rejects_present":sum((r.get("physical_egg_id") or "").startswith("physical-reject") for r in rows),
              "capture_time_span_hours_by_egg":{egg:(max(t)-min(t)).total_seconds()/3600 for egg,t in spans.items()},
              "age_at_each_capture_independently_verified":False,
              "historical_test_already_inspected":True, "fresh_independent_holdout_available":False,
              "batch_or_farm_generalization_established":False,
              "interpretation":"Zero identity crossings means no overlap detected by those recorded checks, not proof of complete absence of leakage. Public batch/egg identities and longitudinal age records are missing."}
    write(OUT / "audit.json", report)
    baseline = json.loads((BASELINE / "metrics.json").read_text())["overall"]
    records = [json.loads(line) for line in (BASELINE / "outcomes.jsonl").read_text().splitlines()]
    measured = classification_metrics(baseline["raw_confusion_matrix"], baseline["selective_confusion_matrix"])
    intervals = cluster_intervals(records,["DAY_16","DAY_18","UNFERTILIZED"])
    write(OUT / "baseline-metrics.json", {"scope":"REPRODUCED_HISTORICAL_IMAGE_RESULTS", "metrics":measured,"uncertainty":intervals})
    write(OUT / "evidence-lock.json", {"artifacts":{str(p.relative_to(OUT)):sha(p) for p in OUT.rglob("*") if p.is_file()}})
    print(json.dumps({"complete":True,"images":len(rows),"hash_mismatches":len(mismatches),
                      "cross_partition_groups":{k:v["cross_partition_groups"] for k,v in checks.items()},
                      "near_duplicate_candidate_pairs":len(near),"fold_crossings":len(fold_crossings),"confidence_intervals":intervals}),flush=True)


if __name__ == "__main__":
    main()
