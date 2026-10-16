"""Package the verified single-model Windows workflow without private state."""
from pathlib import Path
import json
import argparse
import re
import zipfile
import xml.etree.ElementTree as ET
from build_serving_bundle import sha, read

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selective",action="store_true")
    parser.add_argument("--verification-prefix")
    parser.add_argument("--package-name")
    args = parser.parse_args()
    prefix = "selective" if args.selective else "automatic"
    verification_prefix = args.verification_prefix or prefix
    if not re.fullmatch(r"[A-Za-z0-9_-]+", verification_prefix):
        parser.error("Invalid verification prefix")
    release_name = "automatic-recapture-20260912" if args.selective else "automatic-three-class-20260912"
    samples = "recapture-test-samples" if args.selective else "automatic-test-samples"
    artifacts = ROOT / "artifacts"
    live = read(artifacts / f"{verification_prefix}-live-verification.json")
    ui = read(artifacts / f"{verification_prefix}-ui-verification.json")
    assert live["passed"] and ui["passed"] and live["predictions"] == ["DAY_16", "DAY_18", "REJECT"] + ([None,None] if args.selective else [])
    if args.selective:
        assert live["automatic_recapture_verified"] and live["review_required"] is False
        assert all(item["automatic_recapture_verified"] and not item["review_label_visible"] for item in ui["reports"])
    assert all(item["no_model_dropdown"] for item in ui["reports"])
    if args.verification_prefix:
        assert live["browser_test_ran"] and ui["registry_sha256"] == live["registry_sha256"]
        assert live.get("source_files_sha256"), "Fresh verification must bind the served code and dashboard"
        for name, digest in live["source_files_sha256"].items():
            assert sha(ROOT / name) == digest, "Served source changed after verification"
    for name in [f"{verification_prefix}-api-tests.xml", f"{verification_prefix}-ml-tests.xml"]:
        suite = ET.parse(artifacts / name).getroot().find("testsuite")
        assert int(suite.attrib["failures"]) == int(suite.attrib["errors"]) == 0
    web = (artifacts / f"{verification_prefix}-web-verification.log").read_text(encoding="utf-8-sig")
    assert ("8 passed" if args.selective else "6 passed") in web and "built in" in web
    release = ROOT / "deployment/releases" / release_name
    assert sha(release / "registry.json") == live["registry_sha256"]
    registry = read(release / "registry.json")
    for entry in registry["models"]:
        for key in ["model", "config", "known_answer"] + (["gate_policy","training_references"] if args.selective else []):
            assert sha(release / entry[key]["path"]) == entry[key]["sha256"]
    for example in registry["software_test_examples"]:
        assert sha(release / example["file"]["path"]) == example["file"]["sha256"]
    wheels = read(ROOT / "deployment/wheel-hashes.json")
    for name, digest in wheels.items():
        assert sha(ROOT / "deployment/wheelhouse" / name) == digest
    files = {}
    for folder in ["apps/edge_api/balut_api", "apps/web/dist", "deployment/releases/"+release_name, "deployment/wheelhouse", "data/"+samples]:
        for path in (ROOT / folder).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                files[path.relative_to(ROOT).as_posix()] = path
    for folder, names in {
        "scripts": ["Install-Balut.ps1", "Initialize-Serving.ps1", "Start-Balut.ps1", "Copy-Balut-Login.ps1", "backup_serving.py"],
        "deployment": ["requirements-serving.txt", "requirements-serving.lock.txt", "wheel-hashes.json"],
        "docs": ["WINDOWS_MODEL_SERVICE.md", "AUTOMATIC_RECAPTURE_2026-09-12.md" if args.selective else "AUTOMATIC_EGG_ANALYSIS_2026-09-12.md", "REAL_CANDLING_DATA_COLLECTION.md", "VALIDATION_LEDGER.md"],
    }.items():
        for name in names:
            files[folder + "/" + name] = ROOT / folder / name
    files["Open Balut.url"] = ROOT / "Open Balut.url"
    if args.verification_prefix:
        files["docs/HARDENING_AND_ACCURACY_2026-10-04.md"] = ROOT / "docs/HARDENING_AND_ACCURACY_2026-10-04.md"
        files["verification/production-readiness.json"] = artifacts / "production-readiness.json"
    for name in [f"{verification_prefix}-api-tests.xml", f"{verification_prefix}-ml-tests.xml", f"{verification_prefix}-live-verification.json", f"{verification_prefix}-ui-verification.json"]:
        files["verification/"+name] = artifacts / name
    package_name = args.package_name or ("balut-automatic-recapture-20260912.zip" if args.selective else "balut-automatic-analysis-20260912.zip")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.zip", package_name):
        parser.error("Package name must be a ZIP filename")
    archive = artifacts / package_name
    if archive.exists():
        raise FileExistsError("Preserve the previous package")
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        behavior = ("Automatic Day 16 / Day 18 / suspected Reject appearance prediction, with automatic recapture requests for unclear images. Unclear images remain unclassified; no mandatory human review. Historical accepted accuracy was 95/97 at 97/172 coverage; two accepted predictions were wrong. Read docs/AUTOMATIC_RECAPTURE_2026-09-12.md."
                    if args.selective else "Automatic Day 16 / Day 18 / suspected Reject prediction. All predictions need confirmation. Read docs/AUTOMATIC_EGG_ANALYSIS_2026-09-12.md.")
        bundle.writestr("README.md", "# Balut automatic image analysis\n\n"+behavior+"\n\nRequires Windows x64 and Python 3.12. Run scripts/Install-Balut.ps1, then scripts/Copy-Balut-Login.ps1, then scripts/Start-Balut.ps1 -Supervise in PowerShell. Leave the window running. Open http://127.0.0.1:8765 in Chrome or Edge, username operator, and paste the copied password. Clear your clipboard afterward.\n\nIncludes offline dependencies, the trained ONNX model, dashboard, evidence/backup tools, and software test images. Private credentials and databases are excluded and generated locally at installation. Physical camera capture and grading remain unvalidated.\n")
        inventory = {}
        for name, path in files.items():
            assert not any(part in {"private","runtime","backups","logs"} for part in Path(name).parts)
            bundle.write(path,name)
            inventory[name] = sha(path)
        bundle.writestr("file-hashes.json",json.dumps(inventory,indent=2)+"\n")
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
    result = {"package":str(archive),"bytes":archive.stat().st_size,"sha256":sha(archive),"inventory_files":len(files)}
    (artifacts / f"{verification_prefix}-package.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()
