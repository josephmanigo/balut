"""Exercise only the fresh school test extraction; never touches the operating database."""
import base64
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

import httpx
from PIL import Image

root = Path(sys.argv[1]).resolve()
assert root.name == "BalutSchoolBox" and root.parent.name == "school-kit-check-20261017"
python = root / "runtime/python/python.exe"
env = {**os.environ, "PYTHONPATH": str(root / "apps/edge_api")}
with httpx.Client(base_url="http://127.0.0.1:8765", trust_env=False, timeout=40,
                  headers={"X-Balut-Origin": "local"}) as client:
    setup_required = client.get("/api/v1/auth/session").json()["setupRequired"]
    if setup_required:
        blocked = subprocess.run([str(python), "-m", "balut_api.cloud_gateway"], cwd=root, env=env, capture_output=True, timeout=20)
        assert blocked.returncode != 0 and b"Create your account" in blocked.stderr
    credentials = {"username": "kitcheck", "password": "school-verification-only-20261017", "confirmPassword": "school-verification-only-20261017"}
    if setup_required:
        assert client.post("/api/v1/auth/register", json=credentials).status_code == 201
    else:
        assert client.post("/api/v1/auth/login", json=credentials).status_code == 200
    box = client.get("/api/v1/box/status").json()
    assert box["connected"] and not box["enabled"] and not box["calibrated"]
    with Image.open(io.BytesIO(base64.b64decode(box["preview"]))) as image:
        assert image.size == (456, 640)
    assert client.get("/api/v1/model-predictions").json()["items"] == []
    ready = client.get("/ready").json()
    assert ready["serviceReady"] is True and ready["automaticGradingReady"] is False
    (root / "deployment/private/cloud-key.txt").write_text(secrets.token_urlsafe(48), encoding="utf-8")

with (root / "deployment/logs/gateway-test.log").open("w") as log:
    gateway = subprocess.Popen([str(python), "-m", "balut_api.cloud_gateway"], cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(50):
            try:
                with httpx.Client(trust_env=False) as client:
                    response = client.get("http://127.0.0.1:8768/api/v1/auth/session", timeout=1)
                assert response.status_code == 403
                break
            except (httpx.ConnectError, httpx.ConnectTimeout):
                assert gateway.poll() is None
                time.sleep(.2)
        else:
            raise AssertionError("Gateway startup timed out")
        project = Path(__file__).resolve().parents[1]
        result = subprocess.run(["node", str(project / "scripts/verify_vercel_local.mjs"), str(root)], capture_output=True, text=True, check=True, timeout=60)
        report = json.loads(result.stdout)
        report.update({"unregisteredGateCheckedThisRun": setup_required, "cameraPreviewDimensions": [456, 640],
                       "modelReadiness": ready, "freshAccountAndHistory": True, "actualOtherLaptopVerified": False})
        (project / "artifacts/school-defense-20261017/local-integration-verification.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    finally:
        gateway.terminate()
        gateway.wait(timeout=10)
