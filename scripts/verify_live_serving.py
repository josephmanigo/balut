"""Exercise actual deployed ONNX models, process restart, and backup recovery."""
from pathlib import Path
import concurrent.futures
import hashlib
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
PRIVATE = ROOT / "deployment/private"
profile = json.loads((PRIVATE / "windows.json").read_text(encoding="utf-8-sig"))
run_id = time.strftime("%Y%m%d-%H%M%S")
run = ROOT / "deployment/runtime" / ("verification-" + run_id)
run.mkdir(parents=True, exist_ok=False)
profile.update(database_path=str(run / "balut.db"), evidence_path=str(run / "evidence"), port=8766,
               log_path=str(ROOT / "deployment/logs" / ("verification-" + run_id + ".log")))
profile_path = PRIVATE / ("verification-" + run_id + ".json")
profile_path.write_text(json.dumps(profile, indent=2)+"\n")
registry_path = Path(profile["model_registry_path"])
registry = json.loads(registry_path.read_text())
headers = {"Authorization": "Bearer " + profile["local_admin_token"], "X-Balut-Origin": "local",
           "X-Actor-Id": "deployment-verification", "Content-Type": "image/jpeg"}
environment = {**os.environ, "PYTHONPATH": str(ROOT / "apps/edge_api")}
process = None
process_checks = []
client = httpx.Client(base_url="http://127.0.0.1:8766", timeout=20, trust_env=False)


def port_open():
    with socket.socket() as connection:
        connection.settimeout(0.5)
        return connection.connect_ex(("127.0.0.1", 8766)) == 0


def listener_identity():
    if os.name != "nt":
        return {"ProcessId": process.pid, "ParentProcessId": os.getpid()}
    command = "$listener = Get-NetTCPConnection -State Listen -LocalPort 8766 -ErrorAction Stop; Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $listener.OwningProcess) | Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command],
                            check=True, capture_output=True, text=True, timeout=15)
    identity = json.loads(result.stdout)
    assert identity["ProcessId"] == process.pid or identity["ParentProcessId"] == process.pid
    assert "balut_api.service_runner" in identity["CommandLine"] and str(profile_path) in identity["CommandLine"]
    return identity


def start():
    global process
    assert not port_open(), "Verification port must be closed before starting a new process"
    process = subprocess.Popen([sys.executable, "-m", "balut_api.service_runner", "--profile", str(profile_path)],
                               cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Verification service exited during startup")
        try:
            response = client.get("/ready")
            if response.status_code == 200:
                assert response.json()["loadedModels"] == 3
                assert response.json()["automaticGradingReady"] is False
                identity = listener_identity()
                process_checks.append({"launcher_pid": process.pid, "listener_pid": identity["ProcessId"],
                                       "listener_belongs_to_launched_process": True,
                                       "database_path": profile["database_path"]})
                return
        except httpx.TransportError:
            pass
        time.sleep(0.2)
    raise RuntimeError("Verification service startup timed out")


def stop():
    global process
    if process and process.poll() is None:
        # Windows venv launchers spawn a child interpreter. Terminate this test's
        # entire process tree and prove the port closed before a restart.
        if os.name == "nt":
            subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                           check=True, capture_output=True, timeout=15)
        else:
            process.terminate()
        process.wait(timeout=15)
        deadline = time.monotonic() + 10
        while port_open() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert not port_open(), "Verification listener survived process-tree termination"
        if process_checks:
            process_checks[-1]["listener_closed_after_termination"] = True
    process = None


try:
    start()
    assert client.get("/api/v1/models").status_code == 401
    assert client.get("/").status_code == 401
    page = client.get("/", auth=("operator", profile["local_admin_token"]))
    assert page.status_code == 200 and "<div id=\"root\"" in page.text
    assert client.get("/health").json()["operationalModelValidated"] is False
    responses, durations = [], []
    for entry in registry["models"]:
        body = (registry_path.parent / entry["known_answer"]["path"]).read_bytes()
        key = "live-verification-" + entry["id"]
        began = time.monotonic()
        response = client.post("/api/v1/model-predictions/" + entry["id"], headers={**headers, "Idempotency-Key": key}, content=body)
        assert response.status_code == 200, response.status_code
        result = response.json()
        durations.append({"model": entry["id"], "request_ms": round((time.monotonic()-began)*1000, 2)})
        actual = np.array(list(result["sourceClassDecisionScores"].values()))
        np.testing.assert_allclose(actual, entry["expected_scores"], atol=1e-4, rtol=1e-4)
        assert result["operationalOutcome"] == "REVIEW_RECAPTURE" and result["operationalUseAuthorized"] is False
        again = client.post("/api/v1/model-predictions/" + entry["id"], headers={**headers, "Idempotency-Key": key}, content=body)
        assert again.json() == result
        responses.append(result)
    before = responses[0]
    stop()  # Controlled abrupt stop of the isolated verification database.
    start()
    after = client.get("/api/v1/model-predictions/records/"+before["predictionId"], headers=headers)
    assert after.json() == before
    entry = registry["models"][0]
    body = (registry_path.parent / entry["known_answer"]["path"]).read_bytes()

    def concurrent_request(index):
        response = client.post("/api/v1/model-predictions/"+entry["id"], headers={**headers, "Idempotency-Key": f"concurrency-test-{index:03}"}, content=body)
        return response.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(concurrent_request, range(8)))
    assert all(status in {200, 429, 503} for status in statuses) and 200 in statuses
    # 503 is Uvicorn's outer connection limit; 429 is the single-inference limit.
    snapshot = ROOT / "deployment/backups" / ("verified-"+run_id)
    backup_report = backup(profile_path, snapshot)
    restored = run / "restored"
    restore_report = restore(snapshot, restored)
    with sqlite3.connect(run / "balut.db") as original, sqlite3.connect(restored / "balut.db") as recovered:
        original_rows = original.execute("SELECT response_json FROM model_predictions ORDER BY id").fetchall()
        recovered_rows = recovered.execute("SELECT response_json FROM model_predictions ORDER BY id").fetchall()
        assert original_rows == recovered_rows
    stop()
    profile.update(database_path=str(restored / "balut.db"), evidence_path=str(restored / "evidence"))
    profile_path.write_text(json.dumps(profile, indent=2)+"\n")
    start()
    assert client.get("/api/v1/model-predictions/records/"+before["predictionId"], headers=headers).json() == before
    assert client.post("/api/v1/model-predictions/"+entry["id"], headers={**headers, "Idempotency-Key": "live-verification-"+entry["id"]}, content=body).json() == before
    stop()
    assert len({check["listener_pid"] for check in process_checks}) == 3
    report = {"passed": True, "models_verified": len(responses), "registry_sha256": profile["model_registry_sha256"],
              "real_onnx_predictions_match_known_answers": True, "authentication_and_web_delivery": True,
              "durable_idempotency": True, "abrupt_process_restart_recovery": True, "backup_and_restore_recovery": True,
              "concurrent_request_statuses": statuses, "latency_samples": durations,
              "backup_evidence_files": backup_report["evidence_files"], "restored_prediction_records": len(recovered_rows),
              "process_restart_verification": process_checks,
              "test_scope": "Software verification with existing public validation images; no new biological or hardware accuracy evidence", "run_path": str(run)}
    (ROOT / "artifacts/production-live-verification.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))
finally:
    stop()
    client.close()
