"""Local Render-mode acceptance harness. No public service or user's cloud account is created."""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time

import httpx
from PIL import Image

from scripts.upload_box_frames import frame_headers
from balut_api.browser_auth import hash_password

project = Path(__file__).resolve().parents[1]
root = project / "output/render-kit-check-20261017/BalutRender"
out = project / "artifacts/school-defense-20261017"
python = project / "output/school-kit-check-20261017/BalutSchoolBox/runtime/python/python.exe"
data = root / f"test-runtime-{int(time.time())}"
assert not data.exists(), "Preserve previous verification; choose a fresh fixture directory"
stop_file = out / "stop-render-preview.txt"
stop_file.unlink(missing_ok=True)
secret = secrets.token_urlsafe(48)
origin = "https://classroom.onrender.com"
env = {**os.environ, "PYTHONPATH": str(root / "apps/edge_api"), "RENDER_EXTERNAL_URL": origin,
       "BALUT_RENDER_DATA": str(data), "BALUT_LOCAL_ADMIN_TOKEN": secrets.token_urlsafe(48),
       "BALUT_DEVICE_SHARED_SECRET": secret, "BALUT_OPERATOR_USERNAME": "rendercheck",
       "BALUT_OPERATOR_PASSWORD_HASH": hash_password("verification-render-only-20261017")}

with (out / "render-local-server.log").open("w") as log:
    process = subprocess.Popen([str(python), "-m", "uvicorn", "balut_api.render_app:app", "--host", "127.0.0.1", "--port", "8785", "--no-proxy-headers", "--no-access-log"],
                               cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
    preview = None
    try:
        with httpx.Client(base_url="http://127.0.0.1:8785", trust_env=False, timeout=20,
                          headers={"Host": "classroom.onrender.com", "Origin": origin, "X-Balut-Origin": "local"}) as client:
            for _ in range(90):
                try:
                    ready = client.get("/ready")
                    if ready.status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                assert process.poll() is None, "Render-mode server exited; inspect its log"
                time.sleep(1)
            else:
                raise AssertionError("Render-mode startup exceeded 90 seconds")
            assert ready.json()["serviceReady"] and not ready.json()["automaticGradingReady"]
            assert client.get("/api/v1/models").status_code == 401
            login = client.post("/api/v1/auth/login", json={"username": "rendercheck", "password": "verification-render-only-20261017"})
            assert login.status_code == 200 and "Secure" in login.headers["set-cookie"]
            cookie = login.headers["set-cookie"].split(";")[0]
            client.headers["Cookie"] = cookie
            assert client.get("/api/v1/auth/session").json()["cloudDemo"] is True
            assert client.get("/api/v1/models").json()["analysisModelId"] == "egg-grade"
            body = None
            with httpx.Client(trust_env=False, timeout=12) as camera:
                for _ in range(4):
                    response = camera.get("http://192.168.2.2:8767/capture")
                    if response.status_code == 200:
                        body = response.content
                        break
            assert body is not None, "Operating USB bridge unavailable"
            headers = frame_headers(body, secret, "render-live-camera-0001", int(time.time()))
            upload = client.post("/api/v1/device/box/frame", content=body, headers={**headers, "Cookie": ""})
            assert upload.status_code == 200, upload.text
            for _ in range(25):
                status = client.get("/api/v1/box/status").json()
                if status["connected"]:
                    break
                time.sleep(.2)
            assert status["connected"] and not status["enabled"] and not status["calibrated"]
            with Image.open(io.BytesIO(base64.b64decode(status["preview"]))) as image:
                assert image.size == (456, 640)
            assert client.get("/api/v1/model-predictions").json()["items"] == []
            # This fixture proxy lets the browser inspect the real cloud UI without changing DNS or TLS settings.
            class Preview(BaseHTTPRequestHandler):
                def do_GET(self):
                    with httpx.Client(trust_env=False, timeout=20) as forward:
                        response = forward.get("http://127.0.0.1:8785" + self.path,
                                               headers={"Host": "classroom.onrender.com", "Cookie": cookie, "X-Balut-Origin": "local"})
                    self.send_response(response.status_code)
                    self.send_header("Content-Type", response.headers.get("content-type", "application/octet-stream"))
                    self.send_header("Content-Length", str(len(response.content)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(response.content)
                def log_message(self, *_): pass
            preview = ThreadingHTTPServer(("127.0.0.1", 8786), Preview)
            worker = threading.Thread(target=preview.serve_forever, daemon=True)
            worker.start()
            report = {"localRenderMode": True, "sealedModelLoaded": True, "secureCookieSignIn": True,
                      "actualUSBFrameSignedAndAccepted": True, "preparedPreviewDimensions": [456, 640],
                      "analysisPaused": True, "physicalEggValidation": False, "publicRenderVerified": False,
                      "linuxDockerVerified": False, "freeMemoryLimitVerified": False,
                      "previewFixture": "http://127.0.0.1:8786/"}
            (out / "render-local-integration.json").write_text(json.dumps(report, indent=2) + "\n")
            print(json.dumps(report), flush=True)
            print("Local preview ready for browser check; creating stop-render-preview.txt closes it.", flush=True)
            deadline = time.monotonic() + 180
            count = 1
            while not stop_file.exists() and time.monotonic() < deadline:
                raw = httpx.get("http://192.168.2.2:8767/capture", trust_env=False, timeout=12)
                if raw.status_code != 200:
                    time.sleep(1)
                    continue
                body = raw.content
                count += 1
                headers = frame_headers(body, secret, f"render-live-camera-{count:04}", int(time.time()))
                client.post("/api/v1/device/box/frame", content=body, headers={**headers, "Cookie": ""})
                time.sleep(1)
    finally:
        if preview:
            preview.shutdown()
            preview.server_close()
        process.terminate()
        process.wait(timeout=10)
