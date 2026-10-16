"""Exercise the pinned three-class route, UI, restart, and restore in test storage."""
from pathlib import Path
from contextlib import closing
import argparse
import hashlib
import re
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time

import httpx
import numpy as np
from backup_serving import backup, restore

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-packages", type=Path)
    parser.add_argument("--selective", action="store_true")
    parser.add_argument("--report-prefix", help="Save this verification separately from historical evidence")
    args = parser.parse_args()
    prefix = "selective" if args.selective else "automatic"
    report_prefix = args.report_prefix or prefix
    if not re.fullmatch(r"[A-Za-z0-9_-]+", report_prefix):
        parser.error("Invalid report prefix")
    profile = json.loads((ROOT / "deployment/private/windows.json").read_text(encoding="utf-8-sig"))
    registry_path = ROOT / "deployment/releases" / ("automatic-recapture-20260912" if args.selective else "automatic-three-class-20260912") / "registry.json"
    registry = json.loads(registry_path.read_text())
    run = ROOT / "deployment/runtime" / time.strftime(prefix+"-check-%Y%m%d-%H%M%S")
    run.mkdir(parents=True, exist_ok=False)
    profile.update(model_registry_path=str(registry_path), model_registry_sha256=(registry_path.parent / "registry.sha256").read_text().strip(),
                   database_path=str(run / "balut.db"), evidence_path=str(run / "evidence"), port=8766)
    profile_path = ROOT / "deployment/private" / (run.name + ".json")
    profile_path.write_text(json.dumps(profile,indent=2)+"\n")
    environment = {**os.environ,"PYTHONPATH":str(ROOT / "apps/edge_api")}
    process = None
    checks = []
    client = httpx.Client(base_url="http://127.0.0.1:8766", timeout=15, trust_env=False)
    headers = {"Authorization":"Bearer " + profile["local_admin_token"],"X-Balut-Origin":"local","X-Actor-Id":"automatic-verification","Content-Type":"image/jpeg"}

    def port_open():
        with socket.socket() as sock:
            sock.settimeout(0.5)
            return sock.connect_ex(("127.0.0.1",8766)) == 0

    def start():
        nonlocal process
        assert not port_open(), "Test port is already occupied"
        process = subprocess.Popen([sys.executable,"-m","balut_api.service_runner","--profile",str(profile_path)],cwd=ROOT,env=environment,
                                   stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic()+40
        while time.monotonic()<deadline:
            assert process.poll() is None,"Test server exited during startup"
            try:
                if client.get("/ready").status_code == 200:
                    command = "$p = Get-NetTCPConnection -State Listen -LocalPort 8766; Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $p.OwningProcess) | Select-Object ProcessId,ParentProcessId | ConvertTo-Json -Compress"
                    owner = json.loads(subprocess.run(["powershell.exe","-NoProfile","-Command",command],check=True,capture_output=True,text=True,timeout=15).stdout)
                    assert process.pid in [owner["ProcessId"],owner["ParentProcessId"]]
                    checks.append({"launcher_pid":process.pid,"listener_pid":owner["ProcessId"],"database":profile["database_path"]})
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.2)
        raise RuntimeError("Test server startup timed out")

    def stop():
        nonlocal process
        if process and process.poll() is None:
            subprocess.run(["taskkill.exe","/PID",str(process.pid),"/T","/F"],check=True,capture_output=True,timeout=15)
            process.wait(timeout=15)
            assert not port_open(),"Test listener survived termination"
            checks[-1]["listener_closed_after_termination"] = True
        process = None

    try:
        start()
        assert client.post("/api/v1/egg-analysis",content=b"").status_code == 401
        catalog = client.get("/api/v1/models",headers=headers).json()
        assert catalog["analysisModelId"] == "egg-grade" and len(catalog["models"]) == 1
        results = []
        for example in registry["software_test_examples"]:
            body = (registry_path.parent / example["file"]["path"]).read_bytes()
            request_headers = {**headers,"Idempotency-Key":prefix+"-"+Path(example["file"]["path"]).stem}
            response = client.post("/api/v1/egg-analysis",headers=request_headers,content=body)
            assert response.status_code == 200
            result = response.json()
            assert result["sourcePrediction"] == example["expected_prediction"]
            assert result["reviewRequired"] is (not args.selective) and result["operationalUseAuthorized"] is False
            if args.selective:
                assert result["analysisOutcome"] == example["expected_analysis_outcome"]
                assert result["recaptureRequested"] is (example["expected_prediction"] is None)
                assert result["recaptureReasons"] == example["expected_recapture_reasons"]
            np.testing.assert_allclose(list(result["sourceClassDecisionScores"].values()),example["expected_scores"],atol=1e-4,rtol=1e-4)
            assert client.post("/api/v1/egg-analysis",headers=request_headers,content=body).json() == result
            results.append(result)
        assert client.post("/api/v1/egg-analysis",headers={**headers,"Idempotency-Key":"invalid-jpeg-001"},content=b"not an image").status_code == 422
        if args.node_packages:
            subprocess.run(["node",str(ROOT / "scripts/verify_automatic_ui.cjs"),str(args.node_packages),str(profile_path),prefix,report_prefix],cwd=ROOT,check=True,timeout=90)
        before = results[0]
        stop()
        start()
        assert client.get("/api/v1/model-predictions/records/"+before["predictionId"],headers=headers).json() == before
        backup_report = backup(profile_path,run / "backup")
        restore(run / "backup",run / "restored")
        with closing(sqlite3.connect(run / "balut.db")) as original, closing(sqlite3.connect(run / "restored/balut.db")) as recovered:
            original_rows = original.execute("SELECT response_json FROM model_predictions ORDER BY id").fetchall()
            assert original_rows == recovered.execute("SELECT response_json FROM model_predictions ORDER BY id").fetchall()
        stop()
        profile.update(database_path=str(run / "restored/balut.db"),evidence_path=str(run / "restored/evidence"))
        profile_path.write_text(json.dumps(profile,indent=2)+"\n")
        start()
        assert client.get("/api/v1/model-predictions/records/"+before["predictionId"],headers=headers).json() == before
        stop()
        assert len({check["listener_pid"] for check in checks}) == 3
        report = {"passed":True,"automatic_route":"/api/v1/egg-analysis","registry_sha256":profile["model_registry_sha256"],
                  "predictions":[r["sourcePrediction"] for r in results],"latency_ms":[r["inferenceMs"] for r in results],
                  "authentication":True,"invalid_image_rejected":True,"idempotency":True,"review_required":not args.selective,
                  "automatic_recapture_verified":args.selective and all(r["sourcePrediction"] is None and r["recaptureRequested"] for r in results[-2:]),
                  "restart_and_restore":True,"process_checks":checks,"backup_images":backup_report["evidence_files"],
                  "preserved_prediction_records":len(original_rows),"browser_test_ran":bool(args.node_packages),"run_path":str(run),
                  "source_files_sha256":{path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest()
                                         for folder in ["apps/edge_api/balut_api", "apps/web/dist"]
                                         for path in sorted((ROOT / folder).rglob("*"))
                                         if path.is_file() and "__pycache__" not in path.parts}}
        (ROOT / f"artifacts/{report_prefix}-live-verification.json").write_text(json.dumps(report,indent=2)+"\n")
        print(json.dumps(report,indent=2))
    finally:
        stop()
        client.close()


if __name__ == "__main__":
    main()
