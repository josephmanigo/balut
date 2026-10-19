"""Run ten fresh inferences of each unchanged three-file bundle, without hardware."""
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ml"), str(ROOT / "apps/edge_api")]
import numpy as np
from PIL import Image, ImageOps
from balut_api.model_service import ModelService, active_registry, sha256_file
from balut_ml.scientific_metrics import repeatability

OUT = ROOT / "output/scientific-audit-20261019/identical-input-repeatability"
MANIFEST = ROOT / "data/local/retained-camera-epochs-reject-20261019/manifest.jsonl"
REPEATS = 10


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def main():
    if OUT.exists():
        raise FileExistsError("Preserve the previous repeatability evidence")
    rows = [json.loads(line) for line in MANIFEST.read_text().splitlines()]
    validation = [r for r in rows if r["partition"] == "validation"]
    bundles = []
    for label in ("DAY_16", "DAY_18", "UNFERTILIZED"):
        groups = defaultdict(list)
        for row in validation:
            if row["source_label"] != label:
                continue
            if label != "UNFERTILIZED" and row["source_dataset"] != "physical-multiangle-20261019":
                continue
            groups[row.get("physical_egg_id") or row["duplicate_group"]].append(row)
        eligible = [(key, sorted(values, key=lambda r: r["image_path"])) for key, values in sorted(groups.items())
                    if len({r["source_sha256"] for r in values}) >= 3]
        if len(eligible) < 3:
            raise ValueError("Need three recorded groups with three distinct files per class")
        for key, values in eligible[:3]:
            bundles.append({"identity": key, "source_label": label, "physical_egg_id": values[0].get("physical_egg_id"), "rows": values[:3]})
    registry = active_registry(ROOT); digest = sha256_file(registry)
    OUT.mkdir()
    plan = {"created_at": datetime.now(timezone.utc).isoformat(), "protocol": "A_IDENTICAL_SAVED_INPUTS_FRESH_INFERENCE_EACH_TIME",
            "repeats_per_bundle": REPEATS, "cases": len(bundles), "physical_age_eggs": 6, "public_unfertilized_families": 3,
            "selection": "First three lexically sorted eligible validation groups per class, selected without predictions",
            "input_condition": "Same three JPEG byte strings, same order; all three full-precision score vectors compared",
            "model_reload": "Fresh ModelService before repeats1-5 and again before repeats6-10",
            "strict_tolerance": 0, "physical_scan_evidence": False,
            "source_scope": "Reject public families lack physical egg identity; they do not establish independently identified Reject eggs",
            "registry_sha256": digest, "dataset_sha256": sha256_file(MANIFEST), "script_sha256": sha256_file(Path(__file__)),
            "bundles": [{k: v for k, v in b.items() if k != "rows"} for b in bundles]}
    write(OUT / "protocol.json", plan)
    inputs = []
    for number, bundle in enumerate(bundles, 1):
        folder = OUT / f"case-{number:02d}"; folder.mkdir(); bodies = []; evidence = []
        for view, row in enumerate(bundle["rows"], 1):
            source = Path(row["image_path"]); assert sha256_file(source) == row["source_sha256"]
            original = source.read_bytes(); body = original
            (folder / f"original-{view}{source.suffix.lower()}").write_bytes(original)
            with Image.open(io.BytesIO(body)) as image:
                if image.format != "JPEG":
                    buffer = io.BytesIO(); ImageOps.exif_transpose(image).convert("RGB").save(buffer, "JPEG", quality=95); body = buffer.getvalue()
            target = folder / f"input-{view}.jpg"; target.write_bytes(body); bodies.append(body)
            evidence.append({"view": view, "source_sha256": row["source_sha256"], "serving_sha256": hashlib.sha256(body).hexdigest()})
        assert len({hashlib.sha256(b).hexdigest() for b in bodies}) == 3
        write(folder / "input-manifest.json", {**plan["bundles"][number-1], "inputs": evidence})
        (folder / "attempts.jsonl").touch(exist_ok=False); inputs.append(bodies)
    attempts = [[] for _ in bundles]
    for session in range(2):
        service = ModelService()
        try:
            service.load(registry, digest)
            classes = service.models[service.analysis_model_id]["config"]["class_order"]
            for repetition in range(session * 5 + 1, session * 5 + 6):
                for number, bodies in enumerate(inputs):
                    record = {"repeat": repetition, "session": session + 1, "started_at": datetime.now(timezone.utc).isoformat()}
                    try:
                        result = service.predict_views(service.analysis_model_id, bodies)
                        vector = [view["sourceClassDecisionScores"][label] for view in result["multiView"]["views"] for label in classes]
                        record.update(result=result, score_vector=vector, score_vector_hex=[float(v).hex() for v in vector], class_order=classes)
                    except Exception as error:
                        record.update(error=type(error).__name__ + ": " + str(error), result=None, score_vector=None)
                    record["finished_at"] = datetime.now(timezone.utc).isoformat(); attempts[number].append(record)
                    with (OUT / f"case-{number+1:02d}" / "attempts.jsonl").open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(record, allow_nan=False) + "\n")
                print(json.dumps({"completed_repeat": repetition, "cases": len(bundles)}), flush=True)
        finally:
            service.close()
    summaries = []
    for number, records in enumerate(attempts, 1):
        measured = {**plan["bundles"][number-1], **repeatability(records, REPEATS)}
        write(OUT / f"case-{number:02d}" / "summary.json", measured); summaries.append(measured)
        vectors = np.array([r["score_vector"] for r in records if r["score_vector"] is not None], dtype=np.float64)
        np.save(OUT / f"case-{number:02d}" / "full-precision-scores.npy", vectors, allow_pickle=False)
    assert sha256_file(registry) == digest and active_registry(ROOT) == registry
    report = {"scope": "IDENTICAL_SAVED_INPUTS_ONLY", "cases": summaries, "all_cases_passed": all(s["strict_zero_gap_passed"] for s in summaries),
              "fresh_physical_scan_zero_gap": "NOT MEASURED", "project_status": "ZERO-GAP REQUIREMENT NOT MET",
              "reason": "Part A does not establish Part B. No fresh physical repeats from every independently identified class were collected."}
    write(OUT / "summary.json", report)
    write(OUT / "evidence-lock.json", {"artifacts": {str(p.relative_to(OUT)): sha256_file(p) for p in OUT.rglob("*") if p.is_file()}})
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
