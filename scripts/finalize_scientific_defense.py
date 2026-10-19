"""Verify the retained CPU release and seal the visually reviewed defense packet."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/edge_api"))
import httpx
import numpy as np
from balut_api.model_service import ModelService, active_registry, preprocess, sha256_file
from balut_api.supabase_store import Supabase
from balut_api.cloud_sessions import CloudSessions
from balut_api.browser_auth import COOKIE_NAME

OUT = ROOT / "output/model-results/EggGrade-IoT-Scientific-Defense-20261019"
PDF = ROOT / "output/pdf/EggGrade-IoT-Scientific-Defense-20261019.pdf"
XLSX = ROOT / "outputs/01a14f30-3fda-79d1-938c-4bf71af88388/EggGrade-IoT-Field-Collection.xlsx"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def live_status():
    profile = json.loads((ROOT / "deployment/private/supabase.json").read_text(encoding="utf-8-sig"))
    cloud = Supabase(profile["url"], profile["secret_key"])
    sessions = CloudSessions(cloud)
    username = cloud.request("GET", "/rest/v1/balut_account", params={"id": "eq.1", "select": "username"}).json()[0]["username"]
    token = sessions.issue(username)
    origin = "https://egggradeiot.vercel.app"
    try:
        with httpx.Client(base_url=origin, timeout=45, trust_env=False, cookies={COOKIE_NAME: token},
                          headers={"X-Balut-Origin": "local", "Origin": origin}) as client:
            response = client.get("/api/v1/models"); response.raise_for_status(); catalog = response.json()
            response = client.get("/api/v1/box/status"); response.raise_for_status(); box = response.json()
            response = client.get("/ready"); response.raise_for_status(); ready = response.json()
        return {"catalog": catalog, "readiness": ready, "box": {key: box.get(key) for key in ("state", "connected", "enabled", "error")},
                "verified_at": datetime.now(timezone.utc).isoformat(), "capture_or_calibration_command_sent": False}
    finally:
        sessions.revoke(token)


def main(reviewed):
    if not reviewed:
        raise ValueError("Render and visually review every PDF page and the workbook before packaging")
    registry = active_registry(ROOT); digest = sha256_file(registry)
    assert digest == "d83a2fddd1d2bc46f910850cba7f56780e0bbfbcab33479e5a9e40801d64ab04"
    service = ModelService(); errors = []; cases = 0
    try:
        service.load(registry, digest)  # Checks every registered artifact and known-answer contract.
        model = service.models[service.analysis_model_id]
        for case in sorted((ROOT / "output/scientific-audit-20261019/identical-input-repeatability").glob("case-*")):
            for source in sorted(case.glob("input-*.jpg")):
                scores, embedding = model["session"].run(None, {model["input_name"]: preprocess(source.read_bytes(), model["config"])})
                camera = embedding @ model["camera"]["coefficient"].T + model["camera"]["intercept"]
                np.testing.assert_allclose(scores, camera, atol=1e-4, rtol=1e-4)
                assert np.array_equal(scores.argmax(1), camera.argmax(1))
                errors.append(float(np.max(np.abs(scores-camera)))); cases += 1
        report = {"verified_at": datetime.now(timezone.utc).isoformat(), "local_catalog": service.describe(),
                  "registered_hashes_and_known_answers_passed": True, "parity_input_images": cases,
                  "onnx_embedded_vs_camera_head_maximum_score_difference": max(errors),
                  "parity_tolerance": {"atol": 1e-4, "rtol": 1e-4}, "argmax_agreement": 1.0,
                  "scope": "DIFFERENT_NUMERICAL_EXECUTION_PATH_EXPORT_PARITY_NOT_THE_ZERO_GAP_REPEAT_TEST",
                  "active_registry_unchanged": sha256_file(registry) == digest}
        try:
            live = live_status()
            report.update(live_catalog=live["catalog"], live_status=live, temporary_verification_session_revoked=True)
            assert report["live_catalog"]["registrySha256"] == digest
            report["live_matches_local"] = True
        except (httpx.HTTPError, ValueError) as error:
            report.update(live_matches_local=None, live_check_error=type(error).__name__ + ": " + str(error))
        write(OUT / "final-runtime-verification.json", report)
    finally:
        service.close()
    with zipfile.ZipFile(XLSX) as archive:
        assert archive.testzip() is None
        xml = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        values = [int(cell.find("m:v", ns).text) for cell in xml.findall(".//m:c", ns)
                  if cell.attrib["r"].startswith("C") and cell.attrib["r"] != "C1"]
        assert len(values) == 90 and sum(values) == 171
        assert xml.find(".//m:pane", ns) is not None and xml.find(".//m:dataValidations", ns) is not None
    check = read(OUT / "report-verification.json")
    assert check["pdf_sha256"] == sha256_file(PDF) and check["pages"] == 11
    check.update(visual_review="ALL_11_PAGES_AND_WORKBOOK_REVIEWED", focused_tests_passed=10,
                 xlsx_zip_and_planned_counts_verified=True, native_excel_interaction_tested=False)
    field_check = read(OUT / "field-validation-self-check.json")
    assert field_check["collector_sha256"] == sha256_file(ROOT / "scripts/collect_scientific_field_scan.py")
    assert field_check["code_and_runtime_lock_verified"] and not field_check["hardware_opened"]
    assert field_check["physical_measurements_collected"] == 0
    check["field_collector_validation_self_check"] = "PASSED_SYNTHETIC_SOFTWARE_SCOPE_ONLY"
    write(OUT / "report-verification.json", check)
    audit = [
        ("Active runtime, artifacts, preprocessing, mappings, gates and aggregation", "VERIFIED", "model-identity.json; final-runtime-verification.json; active-model-config.json; active-gate-policy.json"),
        ("Baseline reproduced with unchanged pipeline", "VERIFIED", "550/649 raw; every historical score exactly matched prior reproduction"),
        ("Use existing1590 photographs", "VERIFIED", "90 three-view +1500 rotation images; grouped with30 original views; no R1/R2/R3"),
        ("Improvement experiments with grouping and saved configurations", "COMPLETED_AVAILABLE_DATA_WORK", "236 development configurations; experiment-ledger.json; no unsupported promotion"),
        ("Independent accuracy>=96% and pursuit98–99%", "NOT_ESTABLISHED", "Best selected development overall96.87%; physical ages95.19/94.63; no fresh independent holdout"),
        ("All requested metrics, counts and confidence intervals", "VERIFIED", "baseline-metrics.json; classification-metrics.csv; experiment-ledger.json"),
        ("Leakage and split audit", "COMPLETED_WITH_LIMITATIONS", "No detected recorded overlaps; public eggs/batches unknown; historical test reused"),
        ("PartA identical-input strict zero gap", "PASSED_TESTED_SCOPE", "9 three-file bundles ×10 fresh inferences; maximum score difference0; not physical every-class proof"),
        ("PartB fresh physical strict zero gap", "ZERO-GAP REQUIREMENT NOT MET", "No qualifying fresh physical repeat study; maximum gap not measured"),
        ("Panel questions1–10 with A/B/C/D", "DELIVERED", "defense-answers.txt;11-page PDF"),
        ("Actual applicable learning curves", "DELIVERED", "results.png is inactive MLP; active logistic has no epochs; solver fit reproduced38 iterations"),
        ("Field accuracy and runnable collection", "FIELD ACCURACY NOT YET ESTABLISHED", "Protocol, blank90-egg sheet, collector and tests prepared; physical execution pending"),
        ("Preserve data, release and three-view rotation", "VERIFIED_SOFTWARE_SCOPE", "No active release change; collector reuses existing capture; fresh physical verification not performed")]
    write(OUT / "requirement-audit.json", {"requirements": [dict(requirement=a, status=b, evidence=c) for a,b,c in audit],
          "goal_complete": False, "remaining_blockers": ["New independently referenced age/Unfertilized physical eggs and batches unavailable", "Fresh final holdout unavailable", "Strict fresh-camera zero-gap unmeasured", "Automatic-restart cause unresolved for GPU work"]})
    shutil.copyfile(PDF, OUT / PDF.name); shutil.copyfile(XLSX, OUT / XLSX.name)
    guide = ROOT / "docs/reports/20261019"
    if guide.is_dir():
        for source in guide.iterdir():
            if source.suffix in (".pdf", ".png", ".json", ".md"):
                target = OUT / "easy-guide" / source.name
                target.parent.mkdir(exist_ok=True)
                shutil.copyfile(source, target)
    for entry in read(OUT / "experiment-ledger.json"):
        source = ROOT / "ml/runs" / entry["run"]; target = OUT / "experiment-records" / entry["run"]; target.mkdir(parents=True, exist_ok=True)
        for name in ("experiment-plan.json", "metrics.json", "selection-lock.json", "search.jsonl", "folds.json"):
            if (source / name).is_file(): shutil.copyfile(source / name, target / name)
    for source in (ROOT / "ml/runs/nested-feature-epochs-20261019").glob("hidden-*/fold-*/*"):
        if source.name in ("history.jsonl", "summary.json"):
            target = OUT / "epoch-logs" / source.relative_to(ROOT / "ml/runs/nested-feature-epochs-20261019")
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, target)
    repeat_source = ROOT / "output/scientific-audit-20261019/identical-input-repeatability"
    for source in repeat_source.glob("case-*/*"):
        if source.name in ("attempts.jsonl", "summary.json", "full-precision-scores.npy", "input-manifest.json"):
            target = OUT / "repeat-logs" / source.relative_to(repeat_source)
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, target)
    paths = sorted(p for p in OUT.rglob("*") if p.is_file() and p.name != "packet-sha256.json")
    write(OUT / "packet-sha256.json", {path.relative_to(OUT).as_posix(): sha256_file(path) for path in paths})
    target = OUT.with_suffix(".zip")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(OUT.rglob("*")):
            if source.is_file(): archive.write(source, source.relative_to(OUT))
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        for name, digest in read(OUT / "packet-sha256.json").items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
    print(json.dumps({"packet": str(target), "bytes": target.stat().st_size, "sha256": sha256_file(target),
                      "runtime_matches_live": report.get("live_matches_local"), "parity_max_difference": max(errors), "goal_complete": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--visual-review-complete", action="store_true")
    main(parser.parse_args().visual_review_complete)
