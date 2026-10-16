"""Assemble the verified Windows software-first handoff, excluding private state."""
from pathlib import Path
import hashlib
import json
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024*1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    artifacts = ROOT / "artifacts"
    live = read(artifacts / "production-live-verification.json")
    ui = read(artifacts / "production-ui-verification.json")
    npm = read(artifacts / "production-npm-audit.json")
    python = read(artifacts / "production-python-audit.json")
    suite = ET.parse(artifacts / "production-api-tests.xml").getroot().find("testsuite")
    assert suite is not None and int(suite.attrib["failures"]) == int(suite.attrib["errors"]) == 0
    assert live["passed"] and ui["passed"]
    assert len(live["process_restart_verification"]) == 3
    assert all(check["listener_closed_after_termination"] for check in live["process_restart_verification"])
    assert npm["metadata"]["vulnerabilities"]["total"] == 0
    assert not any(dependency.get("vulns") for dependency in python["dependencies"])
    web_log = (artifacts / "production-web-verification.log").read_text(encoding="utf-8-sig")
    assert "2 passed" in web_log and "built in" in web_log
    registry = ROOT / "deployment/releases/source-labels-20260912/registry.json"
    assert sha(registry) == live["registry_sha256"]
    for model in read(registry)["models"]:
        for key in ["model", "config", "known_answer"]:
            assert sha(registry.parent / model[key]["path"]) == model[key]["sha256"]
    wheels = {path.name: sha(path) for path in sorted((ROOT / "deployment/wheelhouse").glob("*.whl"))}
    assert wheels
    (ROOT / "deployment/wheel-hashes.json").write_text(json.dumps(wheels, indent=2)+"\n")
    passed = int(suite.attrib["tests"]) - int(suite.attrib["skipped"])
    burst = {str(code): live["concurrent_request_statuses"].count(code) for code in sorted(set(live["concurrent_request_statuses"]))}
    timings = ", ".join(f"{sample['request_ms']:.0f} ms for {sample['model']}" for sample in live["latency_samples"])
    report = {"status": "SOFTWARE_VERIFIED_FOR_LOCAL_SHADOW_USE", "user_scope": "Windows laptop; software first, candler/images not yet available",
              "automatic_grading_ready": False, "api_core_tests_passed": passed, "optional_training_tests_skipped": int(suite.attrib["skipped"]),
              "web_tests_passed": 2, "web_typecheck_and_build": True, "live_verification": live, "browser_verification": ui,
              "known_dependency_vulnerabilities": {"python": 0, "npm": 0}, "dependency_wheel_count": len(wheels),
              "registry_sha256": sha(registry), "remaining": ["Assembled candler and physical transport", "Identified, timestamped duck-egg data",
              "Prospective egg/session validation and optical quality gates", "ESP32 int8 conversion and device acceptance if required",
              "Separate Android/cloud/multi-reviewer project surfaces", "Windows boot startup registration is not installed"]}
    (artifacts / "production-readiness.json").write_text(json.dumps(report, indent=2)+"\n")
    lines = ["# Windows software readiness — 2026-09-12", "",
             "Status: **SOFTWARE VERIFIED FOR LOCAL SHADOW USE**. The user requested the Windows laptop and confirmed software first because the assembled candler and timestamped own-egg images are not yet available. Automatic grading remains disabled.", "",
             "The implemented service loads the three verified ONNX models, requires a local operator login, accepts bounded JPEG uploads through the browser/API, preserves image and prediction evidence, handles retries idempotently, and provides backup/restore and supervised startup scripts.", "",
             "| Verification | Measured result |", "|---|---|",
             f"| API/core tests | {passed} passed; {suite.attrib['skipped']} optional training entries skipped in the serving environment |",
             "| Web checks | 2 tests passed; TypeScript and production build passed |",
             "| Live model inference | 3 real models match their known answers |",
             "| Browser flow | JPEG upload, saved result, and review outcome passed at 1440×1000 and 390×844; no horizontal overflow or browser errors |",
             "| Restart recovery | Saved prediction retained after abrupt test-process termination and restart |",
             "| Backup/restore | Database integrity, evidence hashes, saved responses, and replay verified after restoring and restarting |",
             f"| Concurrent requests | Eight-request burst returned HTTP status counts {burst}; no guessed success |",
             "| Dependency audit | 0 known findings in the pinned Python environment and npm lockfile at scan time |",
             f"| Offline dependencies | {len(wheels)} Windows x64/Python 3.12 wheels included, with SHA-256 inventory |", "",
             f"Single measured HTTP prediction samples on this laptop were {timings}. These are functional smoke-test timings, not percentile latency, sustained-load, thermal, or availability guarantees.", "",
             "Windows restart verification recorded three distinct listening processes and confirmed the test port closed after every process-tree termination. Backup verification includes a live WAL database, a standalone snapshot, all referenced images, and rejection of incomplete inventories.", "",
             f"Pinned source-label registry SHA-256: `{sha(registry)}`.", "",
             "The final Python suite reports two upstream TestClient/AnyIO deprecation warnings. They did not fail the software checks. The four skips concern optional training dependencies; serving and release-verification tests ran. The earlier feature/public training suite separately passed 21 tests.", "",
             "The runtime uses a single local operator credential and a separate device credential. The browser and data API are loopback-only, and credentials are generated per installation. Version-2 device signatures bind route and replay key; real firmware must implement that protocol before connection. The application does not claim independent reviewer accounts, working cloud delivery, or physical hardware control.", "",
             "The package is suitable for installing and exercising the local source-label review software. It is not a validated automatic-grading, food-safety, Android, ESP32, or cloud release. Age-source accuracy is 82.9% on 35 historical images, and Pat still misses 14/137 Reject-labelled images. The physical study and candler acceptance criteria remain in the existing validation ledger.", "",
             "[Operating and recovery guide](WINDOWS_MODEL_SERVICE.md) · [Accuracy report](ACCURACY_RESULTS_2026-09-12.md) · [Real-data collection guide](REAL_CANDLING_DATA_COLLECTION.md)", ""]
    (ROOT / "docs/SOFTWARE_READINESS_2026-09-12.md").write_text("\n".join(lines), encoding="utf-8")
    files = {}
    for folder in ["apps/edge_api/balut_api", "apps/web/dist", "deployment/releases/source-labels-20260912", "deployment/wheelhouse"]:
        for path in (ROOT / folder).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                files[path.relative_to(ROOT).as_posix()] = path
    for name in ["Install-Balut.ps1", "Initialize-Serving.ps1", "Start-Balut.ps1", "Copy-Balut-Login.ps1", "backup_serving.py"]:
        files["scripts/"+name] = ROOT / "scripts" / name
    for name in ["requirements-serving.txt", "requirements-serving.lock.txt", "wheel-hashes.json"]:
        files["deployment/"+name] = ROOT / "deployment" / name
    for name in ["WINDOWS_MODEL_SERVICE.md", "SOFTWARE_READINESS_2026-09-12.md", "ACCURACY_RESULTS_2026-09-12.md", "REAL_CANDLING_DATA_COLLECTION.md", "VALIDATION_LEDGER.md"]:
        files["docs/"+name] = ROOT / "docs" / name
    files["data/templates/real-candling-capture-log.csv"] = ROOT / "data/templates/real-candling-capture-log.csv"
    for name in ["production-readiness.json", "production-api-tests.xml", "production-live-verification.json", "production-ui-verification.json", "production-python-audit.json", "production-npm-audit.json"]:
        files["verification/"+name] = artifacts / name
    archive = artifacts / "balut-windows-software-20260912.zip"
    if archive.exists():
        raise FileExistsError("Preserve previous package")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        bundle.writestr("README.md", "# Balut Windows model-serving software\n\nScope: local source-label review. Automatic grading is disabled. Read docs/WINDOWS_MODEL_SERVICE.md and docs/SOFTWARE_READINESS_2026-09-12.md.\n\nRequires 64-bit Python 3.12. In PowerShell run scripts/Install-Balut.ps1 (use -PythonExecutable for your Python path), scripts/Copy-Balut-Login.ps1, then scripts/Start-Balut.ps1 -Supervise. Leave that window running. Open http://127.0.0.1:8765 in the browser, username operator, and paste the copied password. Clear the clipboard after signing in.\n\nThe archive contains exact offline dependency wheels, built dashboard, three ONNX models, checksums, software source, and license notices. It contains no operator/device credentials or operating database. Each laptop creates its own private profile. Keep backups on separate storage; start the launcher after reboot.\n")
        inventory = {}
        for name, path in files.items():
            assert not any(part in {"private", "runtime", "logs", "backups"} for part in Path(name).parts)
            bundle.write(path, name)
            inventory[name] = sha(path)
        bundle.writestr("file-hashes.json", json.dumps(inventory, indent=2)+"\n")
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
    result = {"package": str(archive), "bytes": archive.stat().st_size, "sha256": sha(archive), "inventory_files": len(files)}
    (artifacts / "production-package.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
