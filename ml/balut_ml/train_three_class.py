"""Fit one Day 16 / Day 18 / Reject source-label model from audited crops."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

CLASSES = ["DAY_16", "DAY_18", "REJECT"]
MAPPING = {"age": {"Fertile-Day-16": "DAY_16", "Fertile-Day-18": "DAY_18"}, "pat": {"Reject": "REJECT"}}


def combine_rows(sources):
    """Keep original partitions and only explicitly supported source labels."""
    rows, hashes = [], {}
    for source, original in sources.items():
        for index, row in enumerate(original):
            if row["source_label"] not in MAPPING[source]:
                continue
            label = MAPPING[source][row["source_label"]]
            identity = (row["partition"], label)
            for field in ["pixel_sha256", "source_sha256"]:
                key = (field, row[field])
                if key in hashes and hashes[key] != identity:
                    raise ValueError("Combined sources contain conflicting labels or cross-partition duplicates")
                hashes[key] = identity
            rows.append({**row, "source_label": label, "original_source_label": row["source_label"],
                         "source_dataset": source, "original_row_index": index,
                         "duplicate_group": source + ":" + row["duplicate_group"]})
    for partition in ["train", "validation", "test"]:
        if {row["source_label"] for row in rows if row["partition"] == partition} != set(CLASSES):
            raise ValueError("Each partition must contain all three supported labels")
    return rows


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Choose a fresh experiment directory")
    from .benchmark_public import BACKBONES, GRID, extract, make_estimator, metrics_for, selection_key, write_json
    from .feature_models import DINO_REVISION, MEAN, STD, FeatureEncoder, SourceClassifier, build_backbone, build_head, portable_head
    from .train_public import load_audited_rows
    import numpy as np
    import torch
    from PIL import Image, ImageOps

    torch.set_num_threads(4)
    torch.manual_seed(42)
    np.random.seed(42)
    torch.use_deterministic_algorithms(True)
    root = Path(__file__).resolve().parents[2]
    prior = root / "ml/runs/accuracy-v2"
    manifests = {"age": root / "data/public/thesis-egg-candling/audit-v1/manifest.jsonl",
                 "pat": root / "data/public/pat-balut/audit-v2/manifest.jsonl"}
    caches = {"age": "source-age16-18", "pat": "pat-balut"}
    sources, audits = {}, {}
    for source, path in manifests.items():
        sources[source], audits[source] = load_audited_rows(path)
    rows = combine_rows(sources)
    # Check the combined sources for the same near-duplicate rule as the audits.
    near_matches = 0
    thumbnails = {}
    for row in rows:
        with Image.open(row["image_path"]) as image:
            thumbnails[row["pixel_sha256"]] = np.asarray(ImageOps.exif_transpose(image).convert("RGB").resize((32, 32)), dtype=np.float32)
    age = [row for row in rows if row["source_dataset"] == "age"]
    pat = [row for row in rows if row["source_dataset"] == "pat"]
    for a in age:
        for b in pat:
            if (int(a["dhash"], 16) ^ int(b["dhash"], 16)).bit_count() <= 3:
                if np.abs(thumbnails[a["pixel_sha256"]] - thumbnails[b["pixel_sha256"]]).mean() <= 6:
                    near_matches += 1
                    if a["partition"] != b["partition"] or a["source_label"] != b["source_label"]:
                        raise ValueError("Cross-source near duplicate needs audit before training")
    args.output.mkdir(parents=True)
    manifest = args.output / "manifest.jsonl"
    manifest.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    limitations = ["Day labels come from a species-unverified public source; chronological age is not independently confirmed.",
                  "Reject examples come from a different public dataset than age examples. Source appearance is confounded with Reject and may inflate mixed-source results.",
                  "No physical egg/session identities are available. Public image grouping cannot establish independent eggs.",
                  "Reject retains the original source label; other Pat labels are excluded and are not relabelled as Reject or assigned an age.",
                  "All predictions require human review; no physical sorting, food-safety decision, or automatic operational grading is authorized."]
    plan = {"classes": CLASSES, "mapping": MAPPING, "backbones": BACKBONES, "grid": GRID, "seed": 42,
            "selection": "validation macro F1, balanced accuracy, accuracy; stable first candidate tie-break",
            "test_policy": "Lock selected model before evaluating the existing historical test crops once.",
            "manifest_sha256": sha(manifest), "source_manifests": {key: sha(path) for key, path in manifests.items()},
            "cross_source_near_duplicate_matches": near_matches,
            "counts": {part: dict(Counter(row["source_label"] for row in rows if row["partition"] == part)) for part in ["train", "validation", "test"]},
            "limitations": limitations}
    write_json(args.output / "experiment-plan.json", plan)
    print(json.dumps({"stage": "audited_three_class_data", "counts": plan["counts"]}), flush=True)
    best = None
    for backbone in BACKBONES:
        bank = {}
        for source, cache_name in caches.items():
            with np.load(prior / cache_name / f"{backbone}-development.npz") as cache:
                if str(cache["manifest_sha256"]) != plan["source_manifests"][source]:
                    raise ValueError("Cached features do not match audited source manifest")
                classes = sorted({row["source_label"] for row in sources[source]})
                for index, feature, label in zip(cache["indexes"], cache["features"], cache["labels"]):
                    row = sources[source][int(index)]
                    if row["partition"] == "test" or classes[int(label)] != row["source_label"]:
                        raise ValueError("Invalid development feature identity")
                    bank[(source, int(index))] = feature
        indexes = np.array([i for i, row in enumerate(rows) if row["partition"] != "test"])
        features = np.stack([bank[(rows[i]["source_dataset"], rows[i]["original_row_index"])] for i in indexes])
        labels = np.array([CLASSES.index(rows[i]["source_label"]) for i in indexes])
        training = np.array([rows[i]["partition"] == "train" for i in indexes])
        for spec in GRID:
            estimator = make_estimator(spec)
            estimator.fit(features[training], labels[training])
            predicted = estimator.predict(features[~training])
            measured = metrics_for(labels[~training], predicted, CLASSES)
            head, head_spec = portable_head(estimator, spec["kind"])
            with torch.inference_mode():
                scores = head(torch.from_numpy(features[~training])).numpy()
            if not np.array_equal(scores.argmax(1), predicted):
                raise ValueError("Portable model differs from fitted classifier")
            record = {"backbone": backbone, "hyperparameters": spec, "head": head_spec, "validation": measured}
            with (args.output / "candidates.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
            if best is None or selection_key(measured) > selection_key(best["validation"]):
                best = record
                torch.save({"state_dict": head.state_dict(), "spec": head_spec}, args.output / "selected-head.pt")
                np.savez_compressed(args.output / "selected-validation.npz", scores=scores, truth=labels[~training], indexes=indexes[~training])
        print(json.dumps({"stage": "validation_selection", "completed_backbone": backbone, "best": best["backbone"], "macro_f1": best["validation"]["macro_f1"]}), flush=True)
    lock = args.output / "selection-lock.json"
    write_json(lock, {**best, "manifest_sha256": sha(manifest)})
    lock_hash = sha(lock)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    encoder = FeatureEncoder(build_backbone(best["backbone"])).eval()
    encoder_path = prior / f"{best['backbone']}-encoder.pt"
    encoder.load_state_dict(torch.load(encoder_path, weights_only=True, map_location="cpu"))
    encoder.to(device)
    payload = torch.load(args.output / "selected-head.pt", weights_only=True, map_location="cpu")
    head = build_head(payload["spec"])
    head.load_state_dict(payload["state_dict"])
    head.eval()
    if sha(lock) != lock_hash:
        raise ValueError("Selection lock changed")
    features, labels, indexes = extract(encoder, rows, {"test"}, CLASSES, device, 32)
    with torch.inference_mode():
        scores = head(torch.from_numpy(features)).numpy()
    test = metrics_for(labels, scores.argmax(1), CLASSES)
    config = {"status": "EXPLORATORY_FROZEN_FEATURE_CLASSIFIER", "task": "THREE_CLASS_EGG_APPEARANCE",
              "operational_use_authorized": False, "backbone": best["backbone"], "head": payload["spec"],
              "class_order": CLASSES, "input_size": 224, "normalization_mean": MEAN, "normalization_std": STD,
              "view_policy": "resize224_plus_horizontal_flip_mean_then_L2", "hyperparameters": best["hyperparameters"],
              "manifest_sha256": sha(manifest), "selection_lock_sha256": lock_hash,
              "encoder_sha256": sha(encoder_path), "dinov2_revision": DINO_REVISION if best["backbone"] == "dinov2_vits14" else None,
              "provenance": {"sources": {key: value["provenance"] for key, value in audits.items()}, "label_mapping": MAPPING},
              "limitations": limitations, "output_semantics": "Uncalibrated three-class decision scores; image appearance prediction, always review required."}
    model = SourceClassifier(encoder.cpu(), head.cpu()).eval()
    torch.save({"state_dict": model.state_dict(), "config": config}, args.output / "best.pt")
    write_json(args.output / "config.json", config)
    write_json(args.output / "metrics.json", {"status": "EXPLORATORY_ONLY", "validation": best["validation"], "test": test,
               "selection_lock_sha256": lock_hash, "checkpoint_sha256": sha(args.output / "best.pt"),
               "test_interpretation": "Mixed public-source historical image holdout; Reject is confounded with dataset source. Not independent duck-egg accuracy."})
    np.savez_compressed(args.output / "selected-test.npz", scores=scores, truth=labels, indexes=indexes)
    with (args.output / "test-predictions.jsonl").open("w", encoding="utf-8") as handle:
        for index, label, score in zip(indexes, labels, scores):
            handle.write(json.dumps({"row_index": int(index), "true_source_label": CLASSES[label], "predicted_source_label": CLASSES[int(score.argmax())], "decision_scores": score.tolist()}) + "\n")
    (args.output / "model-card.md").write_text("# Three-class egg appearance model\n\nSingle-image predictions: Day 16, Day 18, or Reject. One classifier chooses among all three; there is no user model selection or hand-written reject cascade.\n\n" + "\n".join("- " + text for text in limitations) + "\n", encoding="utf-8")
    print(json.dumps({"stage": "complete", "selected_backbone": best["backbone"], "test": test}), flush=True)


if __name__ == "__main__":
    main()
