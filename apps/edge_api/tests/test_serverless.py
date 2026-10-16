import copy
import hashlib
import io
import time
import json
import runpy
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from balut_api.browser_auth import COOKIE_NAME, hash_password
from balut_api.main import create_app
from balut_api.serverless_box import ServerlessBox
from balut_api.supabase_store import Supabase, CloudStorageError
from test_automatic_box import make_box
from test_production import settings_for
from test_supabase_store import provider, URL, SECRET
from scripts.upload_box_frames import frame_headers, render_origin

ORIGIN = "https://balut-test.vercel.app"


@pytest.fixture
def shared(provider, monkeypatch):
    state = {"camera": {}, "lease": None, "sessions": {}, "attempts": []}
    upstream = httpx.request
    def request(method, url, **kwargs):
        if provider["down"]:
            raise httpx.ConnectError("private diagnostics")
        name = url.split("/")[-1]
        body, params = kwargs.get("json", {}), kwargs.get("params", {})
        value = None
        if name == "balut_camera": value = [{"value": state["camera"]}]
        elif name == "balut_claim_camera":
            if not state["lease"]:
                state["lease"] = body["p_token"]
                value = copy.deepcopy(state["camera"])
        elif name == "balut_save_camera":
            value = state["lease"] == body["p_token"]
            if value:
                state["camera"] = copy.deepcopy(body["p_value"])
                if body["p_release"]: state["lease"] = None
        elif name == "balut_create_session":
            state["sessions"][body["p_hash"]] = (time.time() + 28800, body["p_username"])
        elif name == "balut_sessions":
            digest = params["token_hash"][3:]
            if method == "DELETE": state["sessions"].pop(digest, None)
            else:
                expiry, username = state["sessions"].get(digest, (0, None))
                value = [{"username": username}] if expiry > time.time() else []
        elif name == "balut_login_attempt":
            state["attempts"] = [t for t in state["attempts"] if t > time.time() - 60]
            value = len(state["attempts"]) < 10
            if value: state["attempts"].append(time.time())
        else: return upstream(method, url, **kwargs)
        return httpx.Response(200, content=b"null") if value is None else httpx.Response(200, json=value)
    monkeypatch.setattr(httpx, "request", request)
    return state


def camera_frame(occupied=False):
    image = Image.new("RGB", (640, 480), (40, 40, 40))
    if occupied:
        ImageDraw.Draw(image).ellipse((210, 70, 430, 410), fill=(210, 190, 120))
    output = io.BytesIO()
    image.save(output, "JPEG")
    return output.getvalue()


def test_sessions_cross_instances_logout_expiry_rate_limit_and_fail_closed(tmp_path, shared, provider, monkeypatch):
    provider["account"] = {"username": "classroom", "password_hash": hash_password("shared-test-password")}
    def app(name):
        return create_app(settings_for(tmp_path / name, cloud_origin=ORIGIN, serverless=True,
                                       supabase_url=URL, supabase_secret_key=SECRET))
    first, second = app("one"), app("two")
    headers = {"Origin": ORIGIN, "X-Balut-Origin": "local"}
    with TestClient(first, base_url=ORIGIN) as left, TestClient(second, base_url=ORIGIN) as right:
        assert left.post("/api/v1/auth/login", headers=headers, json={"username": "classroom", "password": "shared-test-password"}).status_code == 200
        token = left.cookies.get(COOKIE_NAME)
        assert token not in str(shared["sessions"])
        right.cookies.set(COOKIE_NAME, token)
        assert right.get("/api/v1/models").status_code == 200
        assert right.get("/api/v1/auth/session").json()["authenticated"]
        assert right.post("/api/v1/auth/logout", headers=headers).status_code == 200
        assert left.get("/api/v1/models").status_code == 401
        token = first.state.browser_sessions.issue("classroom")
        left.cookies.clear()
        left.cookies.set(COOKIE_NAME, token)
        digest = hashlib.sha256(token.encode()).hexdigest()
        shared["sessions"][digest] = (time.time() - 1, "classroom")
        assert left.get("/api/v1/models").status_code == 401
        monkeypatch.setattr("balut_api.browser_auth.verify_password", lambda *_: False)
        for index in range(9):
            client = left if index % 2 else right
            assert client.post("/api/v1/auth/login", headers=headers, json={"username": "classroom", "password": "bad"}).status_code == 401
        assert right.post("/api/v1/auth/login", headers=headers, json={"username": "classroom", "password": "bad"}).status_code == 429
        provider["down"] = True
        assert left.get("/api/v1/models").status_code == 503
        assert left.get("/api/v1/auth/session").status_code == 503


def test_capture_survives_new_instances_and_failed_prediction_without_duplicate(tmp_path, shared, monkeypatch):
    local, predictions = make_box(tmp_path, fail_first=True)
    cloud = Supabase(URL, SECRET)
    now = [time.time()]
    monkeypatch.setattr("balut_api.serverless_box.time.time", lambda: now[0])
    def new(): return ServerlessBox(local.database, local.evidence, local.predict, cloud)
    sequence = [0]
    def send(occupied=False):
        now[0] += 1
        sequence[0] += 1
        return new().receive_frame(camera_frame(occupied), f"frame-{sequence[0]:03}")
    for _ in range(3): send()
    new().mutate(lambda box: box.calibrate_saved())
    for _ in range(3): send(True)
    with pytest.raises(OSError, match="interruption"): send(True)
    assert shared["camera"]["config"]["pending"]
    send(True)
    assert len(local.database.list_predictions()) == 1
    assert not shared["camera"]["config"].get("pending")
    assert new().status()["result"]["captureSource"] == "iot_box"
    for _ in range(5): send(True)
    assert len(local.database.list_predictions()) == 1
    key = f"frame-{sequence[0]:03}"
    assert new().receive_frame(camera_frame(True), key)["repeated"]
    with pytest.raises(HTTPException) as error: new().receive_frame(camera_frame(), key)
    assert error.value.status_code == 409
    now[0] += 20
    assert not new().status()["connected"]
    send()
    assert not new().status()["calibrated"] and not new().status()["enabled"]
    assert not new().status()["controlsMotion"]


def test_failed_evidence_upload_rolls_back_frame_and_shared_lease_blocks_other_instance(tmp_path, shared):
    local, _ = make_box(tmp_path)
    cloud = Supabase(URL, SECRET)
    worker = ServerlessBox(local.database, local.evidence, local.predict, cloud)
    original = copy.deepcopy(shared["camera"])
    def fail(box):
        box.config["enabled"] = True
        with pytest.raises(HTTPException) as error: worker.mutate(lambda _: None)
        assert error.value.status_code == 409
        raise OSError("upload interrupted before pending capture")
    with pytest.raises(OSError): worker.mutate(fail)
    assert shared["camera"] == worker.box(original).snapshot()
    assert shared["lease"] is None
    shared["lease"] = "other-instance"
    with pytest.raises(HTTPException): worker.receive_frame(camera_frame(), "test-frame")
    assert render_origin(ORIGIN + "/") == ORIGIN
    with pytest.raises(ValueError): render_origin(ORIGIN + ".evil.example")


def test_vercel_entrypoint_uses_the_production_domain_and_backend_secrets(monkeypatch):
    root = Path(__file__).resolve().parents[3]
    for name in ("BALUT_ENV", "BALUT_ALLOW_SIMULATOR", "BALUT_CORS_ORIGINS", "BALUT_DATABASE_PATH", "BALUT_EVIDENCE_PATH"):
        monkeypatch.setenv(name, "test-placeholder")
    monkeypatch.delenv("BALUT_CLOUD_ORIGIN", raising=False)
    monkeypatch.delenv("BALUT_LOCAL_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("VERCEL_PROJECT_PRODUCTION_URL", "balut-test.vercel.app")
    monkeypatch.setenv("VERCEL_URL", "another-preview.vercel.app")
    monkeypatch.setenv("SUPABASE_URL", URL)
    monkeypatch.setenv("SUPABASE_SECRET_KEY", SECRET)
    monkeypatch.setenv("BALUT_DEVICE_SHARED_SECRET", "x" * 48)
    monkeypatch.setattr("balut_api.main.create_app", lambda settings: settings)
    settings = runpy.run_path(str(root / "app.py"))["app"]
    assert settings.cloud_origin == ORIGIN and settings.serverless
    assert settings.supabase_secret_key == SECRET and SECRET not in repr(settings)
    assert len(settings.local_admin_token) >= 32 and settings.local_admin_token != settings.device_shared_secret
    config = json.loads((root / "vercel.json").read_text())
    assert "uv pip install -r deployment/requirements-vercel.txt" in config["installCommand"]
    assert config["functions"]["app.py"]["maxDuration"] < 150
    assert len(config["functions"]["app.py"]["excludeFiles"]) <= 256
