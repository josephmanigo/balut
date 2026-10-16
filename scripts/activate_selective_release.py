"""Activate the verified local recapture release while preserving operating records."""
from contextlib import closing
from pathlib import Path
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / "apps/edge_api"))
from balut_api.model_service import ModelService, sha256_file


def main():
    profile_path = ROOT / "deployment/private/windows.json"
    old_bytes = profile_path.read_bytes()
    profile = json.loads(old_bytes.decode("utf-8-sig"))
    registry_path = ROOT / "deployment/releases/automatic-recapture-20260912/registry.json"
    registry_hash = sha256_file(registry_path)
    live = json.loads((ROOT / "artifacts/selective-live-verification.json").read_text())
    ui = json.loads((ROOT / "artifacts/selective-ui-verification.json").read_text())
    assert live["passed"] and live["automatic_recapture_verified"] and ui["passed"]
    assert live["registry_sha256"] == registry_hash and profile["port"] == 8765
    service = ModelService()
    service.load(registry_path,registry_hash)
    service.close()
    env = {key:value for key,value in os.environ.items() if key.lower() != "psmodulepath"}
    env["PYTHONPATH"] = str(ROOT / "apps/edge_api")

    def owner():
        command = "Get-NetTCPConnection -State Listen -LocalPort 8765 | ForEach-Object { Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $_.OwningProcess) } | Select-Object ProcessId,ParentProcessId,CommandLine,CreationDate | ConvertTo-Json -Compress"
        result = json.loads(subprocess.run(["powershell.exe","-NoProfile","-Command",command],capture_output=True,text=True,check=True,env=env,timeout=15).stdout)
        assert isinstance(result,dict)
        assert "balut_api.service_runner" in result["CommandLine"] and str(profile_path) in result["CommandLine"]
        return result

    def record_digest():
        digest = hashlib.sha256()
        with closing(sqlite3.connect(profile["database_path"])) as connection:
            rows = connection.execute("SELECT response_json FROM model_predictions ORDER BY id").fetchall()
        for row in rows: digest.update(row[0].encode())
        return {"records":len(rows),"sha256":digest.hexdigest()}

    previous_owner = owner()
    assert owner() == previous_owner
    before = record_digest()
    backup_path = profile_path.with_name(time.strftime("windows-before-recapture-%Y%m%d-%H%M%S.json"))
    assert not backup_path.exists()
    backup_path.write_bytes(old_bytes)
    profile.update(model_registry_path=str(registry_path),model_registry_sha256=registry_hash)
    staged = profile_path.with_suffix(".next.json")
    staged.write_text(json.dumps(profile,indent=2)+"\n")
    subprocess.run(["taskkill.exe","/PID",str(previous_owner["ProcessId"]),"/T","/F"],check=True,capture_output=True,timeout=15)
    with socket.socket() as sock:
        sock.settimeout(1)
        assert sock.connect_ex(("127.0.0.1",8765)) != 0,"Old listener survived"
    os.replace(staged,profile_path)
    process = subprocess.Popen([sys.executable,"-m","balut_api.service_runner","--profile",str(profile_path)],cwd=ROOT,env=env,
                               stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    deadline = time.monotonic()+40
    with httpx.Client(base_url="http://127.0.0.1:8765",timeout=10,trust_env=False,auth=("operator",profile["local_admin_token"])) as client:
        while time.monotonic()<deadline:
            assert process.poll() is None,"New service exited; preserve private backup for recovery"
            try:
                ready = client.get("/ready")
                if ready.status_code == 200: break
            except httpx.TransportError: pass
            time.sleep(0.2)
        else: raise RuntimeError("New service did not become ready")
        catalog = client.get("/api/v1/models").json()
        assert catalog["registrySha256"] == registry_hash and catalog["analysisModelId"] == "egg-grade"
        assert client.get("/").status_code == 200
        assert ready.json()["automaticGradingReady"] is False
    current_owner = owner()
    assert process.pid in [current_owner["ProcessId"],current_owner["ParentProcessId"]]
    after = record_digest()
    assert before == after,"Operating records changed during model switch"
    runtime = {"pid":current_owner["ProcessId"],"launcher_pid":process.pid,"port":8765,"profile_path":str(profile_path)}
    (ROOT / "deployment/runtime/service-process.json").write_text(json.dumps(runtime,indent=2)+"\n")
    report = {"passed":True,"registry_sha256":registry_hash,"release":registry_path.parent.name,
              "operating_records_unchanged":before==after,"operating_record_count":after["records"],
              "previous_listener_pid":previous_owner["ProcessId"],"listener_pid":current_owner["ProcessId"],"launcher_pid":process.pid,
              "ready":True,"url":"http://127.0.0.1:8765","physical_grading_authorized":False}
    (ROOT / "artifacts/selective-active-service.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2))


if __name__ == "__main__":
    main()
