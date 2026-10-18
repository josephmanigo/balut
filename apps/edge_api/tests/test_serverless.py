import copy
import base64
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


def camera_frame(occupied=False, size=(640, 480), brightness=40):
    image = Image.new("RGB", size, (brightness,) * 3)
    if occupied:
        ImageDraw.Draw(image).ellipse((210, 70, 430, 410), fill=(210, 190, 120))
    output = io.BytesIO()
    image.save(output, "JPEG")
    return output.getvalue()


def test_motion_preview_requests_a_separate_held_frame_before_inference(tmp_path, shared, monkeypatch):
    local, predictions = make_box(tmp_path)
    cloud = Supabase(URL, SECRET)
    now, sequence = [time.time()], [0]
    monkeypatch.setattr("balut_api.serverless_box.time.time", lambda: now[0])
    def worker(): return ServerlessBox(local.database, local.evidence, local.predict, cloud)
    def send(occupied=False, mode="preview"):
        sequence[0] += 1
        now[0] += 2
        return worker().receive_frame(camera_frame(occupied), f'usb-motor-{mode}-{"a" * 32}-{sequence[0]}')
    for _ in range(3): send()
    worker().mutate(lambda box: box.calibrate_saved())
    for _ in range(3): response = send(True)
    assert response["captureRequested"] is True
    assert predictions == [] and local.database.list_predictions() == []
    send(True, "still")
    assert len(local.database.list_predictions()) == 1 and predictions[0].startswith("box-still-")
    for _ in range(3): send(True)
    assert len(predictions) == 1
    for _ in range(3): response = send()
    assert not response["captureRequested"] and worker().status()["state"] == "waiting"


def test_browser_cannot_claim_the_signed_motor_capture_protocol(tmp_path, shared):
    local, _ = make_box(tmp_path)
    worker = ServerlessBox(local.database, local.evidence, local.predict, Supabase(URL, SECRET))
    with pytest.raises(HTTPException) as error:
        worker.receive_frame(camera_frame(), "usb-motor-still-" + "a" * 32 + "-1", "browser-session")
    assert error.value.status_code == 400


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
        now[0] += 2
        sequence[0] += 1
        return new().receive_frame(camera_frame(occupied), f"frame-{sequence[0]:03}")
    for _ in range(3): send()
    new().mutate(lambda box: box.calibrate_saved())
    send(True)
    with pytest.raises(OSError, match="interruption"): send(True)
    assert shared["camera"]["config"]["pending"]
    assert "imageHashes" not in shared["camera"]["config"]["pending"]
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
    assert new().status()["calibrated"] and new().status()["enabled"]
    assert new().status()["state"] == "checking_empty"
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


@pytest.mark.parametrize("interruption", ["frame", "session", "gap", "pause"])
def test_old_partial_multiview_is_discarded_before_single_capture(tmp_path, shared, monkeypatch, interruption):
    local, predictions = make_box(tmp_path)
    cloud = Supabase(URL, SECRET)
    now = [time.time()]
    monkeypatch.setattr("balut_api.serverless_box.time.time", lambda: now[0])
    sequence = 0
    def new(): return ServerlessBox(local.database, local.evidence, local.predict, cloud)
    def send(occupied=False, seconds=2, session="first"):
        nonlocal sequence
        sequence += 1
        now[0] += seconds
        return new().receive_frame(camera_frame(occupied), f"views-{sequence}", session)
    for _ in range(3): send()
    new().mutate(lambda box: box.calibrate_saved())
    shared["camera"]["config"]["collection"] = {"key": "legacy-partial", "startedAt": now[0],
        "lastViewAt": now[0], "imageHashes": ["old-view"]}
    if interruption == "frame": send(True)
    elif interruption == "session": send(True, session="second")
    elif interruption == "gap": send(True, seconds=13)
    elif interruption == "pause": new().mutate(lambda box: box.enable(False))
    assert not shared["camera"]["config"].get("collection")
    assert shared["camera"]["config"]["awaitingEmpty"]
    assert not predictions and not local.database.list_predictions()
    if interruption == "pause": new().mutate(lambda box: box.enable(True))
    for _ in range(2): send()
    send(True)
    assert not predictions
    send(True)
    assert len(predictions) == len(local.database.list_predictions()) == 1
    assert new().status()["targetViews"] == 1


@pytest.mark.parametrize("cached_occupied", [False, True])
def test_empty_reference_waits_for_fresh_stable_frames_across_instances(tmp_path, shared, monkeypatch, cached_occupied):
    local, predictions = make_box(tmp_path)
    cloud = Supabase(URL, SECRET)
    now = [time.time()]
    monkeypatch.setattr("balut_api.serverless_box.time.time", lambda: now[0])
    def new(): return ServerlessBox(local.database, local.evidence, local.predict, cloud)
    sequence = [0]
    def send(occupied=False, session="signed-usb"):
        now[0] += 2
        sequence[0] += 1
        new().receive_frame(camera_frame(occupied), f"reference-{sequence[0]:03}", session)

    for _ in range(3): send(cached_occupied)
    new().mutate(lambda box: box.request_reference())
    assert new().status()["state"] == "calibrating"
    assert not new().status()["enabled"]
    send()
    send()
    assert not new().status()["calibrated"]
    send()
    status = new().status()
    assert status["state"] == "waiting" and status["enabled"] and status["calibrated"]
    assert not predictions and not local.database.list_predictions()
    assert "referenceDeadline" not in shared["camera"]["config"]


def test_wider_camera_frames_reset_reference_and_keep_full_preview_detail(tmp_path, shared, monkeypatch):
    local, predictions = make_box(tmp_path)
    cloud = Supabase(URL, SECRET)
    now = [time.time()]
    monkeypatch.setattr("balut_api.serverless_box.time.time", lambda: now[0])
    def new(): return ServerlessBox(local.database, local.evidence, local.predict, cloud)
    for index in range(3):
        now[0] += 2
        new().receive_frame(camera_frame(), f"vga-{index}")
    new().mutate(lambda box: box.calibrate_saved())
    assert new().status()["calibrated"]
    now[0] += 2
    new().receive_frame(camera_frame(size=(800, 600)), "wide-first")
    assert not new().status()["calibrated"] and not new().status()["enabled"]
    for index in range(2):
        now[0] += 2
        new().receive_frame(camera_frame(size=(800, 600)), f"wide-{index}")
    new().mutate(lambda box: box.calibrate_saved())
    assert new().status()["calibrated"] and not predictions
    with Image.open(io.BytesIO(base64.b64decode(new().status()["preview"]))) as image:
        assert image.size == (600, 800)
    # A deployment that removes cropping also invalidates the old reference at the same source size.
    shared["camera"]["config"].pop("framingVersion")
    now[0] += 2
    new().receive_frame(camera_frame(size=(800, 600)), "uncropped-first")
    assert not new().status()["calibrated"] and not new().status()["enabled"]
    assert len(shared["camera"]["frames"]) == 1 and not predictions
    now[0] += 2
    with pytest.raises(HTTPException) as error:
        new().receive_frame(camera_frame(size=(1280, 960)), "unsupported-size")
    assert error.value.status_code == 422


def test_calibration_after_deployment_waits_for_uncropped_frames(tmp_path, shared, monkeypatch):
    local, predictions = make_box(tmp_path)
    cloud = Supabase(URL, SECRET)
    now = [time.time()]
    monkeypatch.setattr("balut_api.serverless_box.time.time", lambda: now[0])
    worker = ServerlessBox(local.database, local.evidence, local.predict, cloud)
    for index in range(3):
        now[0] += 2
        worker.receive_frame(camera_frame(), f"before-framing-{index}")
    shared["camera"]["config"].pop("framingVersion")
    worker.mutate(lambda box: box.request_reference())
    assert worker.status()["state"] == "calibrating" and not worker.status()["calibrated"]
    for index in range(3):
        now[0] += 2
        worker.receive_frame(camera_frame(), f"after-framing-{index}")
        assert worker.status()["calibrated"] == (index == 2)
    assert worker.status()["state"] == "waiting" and not predictions


@pytest.mark.parametrize("reconnect", ["session", "gap"])
@pytest.mark.parametrize("paused", [False, True])
def test_reconnect_recognizes_saved_empty_view_without_calibrating_an_egg(tmp_path, shared, monkeypatch, reconnect, paused):
    local, predictions = make_box(tmp_path)
    cloud = Supabase(URL, SECRET)
    now = [time.time()]
    monkeypatch.setattr("balut_api.serverless_box.time.time", lambda: now[0])
    def new(): return ServerlessBox(local.database, local.evidence, local.predict, cloud)
    sequence = 0
    session = "first-browser"
    def send(occupied=False, brightness=40):
        nonlocal sequence
        sequence += 1
        now[0] += 2
        new().receive_frame(camera_frame(occupied, brightness=brightness), f"auto-empty-{sequence}", session)
    for _ in range(3): send()
    new().mutate(lambda box: box.calibrate_saved())
    reference = copy.deepcopy(shared["camera"]["config"]["reference"])
    if paused: new().mutate(lambda box: box.enable(False))
    if reconnect == "session": session = "second-browser"
    else: now[0] += 20
    for _ in range(5): send(True)
    assert new().status()["state"] == ("paused" if paused else "checking_empty")
    assert new().status()["calibrated"] and not predictions
    assert shared["camera"]["config"]["reference"] == reference
    if paused:
        for _ in range(3): send()
        assert new().status()["state"] == "paused" and not new().status()["enabled"]
        new().mutate(lambda box: box.enable(True))
    for _ in range(3): send(brightness=255)
    assert new().status()["state"] == "checking_empty" and not predictions
    send()
    assert new().status()["state"] == "checking_empty"
    send(True)  # One empty frame must not rearm the box.
    for _ in range(2): send()
    assert new().status()["state"] == "waiting" and not predictions
    assert shared["camera"]["config"]["reference"] == reference
    for _ in range(4): send(True)
    assert len(predictions) == 1
    for _ in range(2): send()
    assert new().status()["state"] == "waiting"
    assert len(predictions) == len(local.database.list_predictions()) == 1


@pytest.mark.parametrize("interruption", ["timeout", "camera", "disconnect"])
def test_waiting_reference_expires_or_cancels_on_camera_change(tmp_path, shared, monkeypatch, interruption):
    local, predictions = make_box(tmp_path)
    cloud = Supabase(URL, SECRET)
    now = [time.time()]
    monkeypatch.setattr("balut_api.serverless_box.time.time", lambda: now[0])
    def new(): return ServerlessBox(local.database, local.evidence, local.predict, cloud)
    new().receive_frame(camera_frame(), "start-reference")
    new().mutate(lambda box: box.request_reference())
    assert new().status()["state"] == "calibrating"
    if interruption == "timeout":
        for index in range(1, 5):
            now[0] += 6
            new().receive_frame(camera_frame(index % 2 == 0), f"moving-{index}")
        assert new().status()["state"] == "needs_reference"
        assert "steady" in new().status()["error"]
    elif interruption == "disconnect":
        now[0] += 13
        assert not new().status()["connected"]
    session = "new-camera" if interruption == "camera" else "signed-usb"
    for index in range(3):
        now[0] += 2
        new().receive_frame(camera_frame(), f"late-{index}", session)
    assert not new().status()["calibrated"] and not new().status()["enabled"]
    assert "referenceDeadline" not in shared["camera"]["config"]
    assert not predictions


def test_browser_usb_frames_require_session_origin_valid_images_and_empty_recheck(tmp_path, shared, provider, monkeypatch):
    provider["account"] = {"username": "classroom", "password_hash": "not-used-by-this-test"}
    now = [time.time()]
    monkeypatch.setattr("balut_api.serverless_box.time.time", lambda: now[0])
    application = create_app(settings_for(tmp_path, cloud_origin=ORIGIN, serverless=True, supabase_url=URL, supabase_secret_key=SECRET))
    headers = {"Origin": ORIGIN, "X-Balut-Origin": "local", "Content-Type": "image/jpeg",
               "X-Balut-Camera-Session": "b342cc3c-1654-48bc-97a7-66e413f945a8", "Idempotency-Key": "browser-frame-001"}
    with TestClient(application, base_url=ORIGIN) as client:
        assert client.post("/api/v1/box/frame", headers=headers, content=camera_frame()).status_code == 401
        client.cookies.set(COOKIE_NAME, application.state.browser_sessions.issue("classroom"))
        assert client.post("/api/v1/box/frame", headers={**headers, "Origin": "https://other.example"}, content=camera_frame()).status_code == 403
        assert client.post("/api/v1/box/frame", headers={**headers, "X-Balut-Origin": ""}, content=camera_frame()).status_code == 403
        assert client.post("/api/v1/box/frame", headers={**headers, "X-Balut-Camera-Session": "bad"}, content=camera_frame()).status_code == 400
        assert client.post("/api/v1/box/frame", headers={**headers, "Content-Type": "text/plain"}, content=camera_frame()).status_code == 400
        assert client.post("/api/v1/box/frame?anything=1", headers=headers, content=camera_frame()).status_code == 400
        assert client.post("/api/v1/box/frame", headers=headers, content=b"not-jpeg").status_code == 422
        assert client.post("/api/v1/box/frame", headers=headers, content=b"x" * (128 * 1024 + 1)).status_code == 413
        assert client.post("/api/v1/box/reference", headers={"Origin": ORIGIN, "X-Balut-Origin": "local"}, json={"emptyConfirmed": False}).status_code == 400
        for index in range(3):
            now[0] += 2
            headers["Idempotency-Key"] = f"browser-frame-{index:03}"
            assert client.post("/api/v1/box/frame", headers=headers, content=camera_frame()).json()["accepted"]
        assert client.post("/api/v1/box/frame", headers=headers, content=camera_frame()).json()["repeated"]
        status = client.post("/api/v1/box/reference", headers={"Origin": ORIGIN, "X-Balut-Origin": "local"}, json={"emptyConfirmed": True}).json()
        assert status["connected"] and status["state"] == "calibrating" and not status["calibrated"]
        for index in range(3):
            now[0] += 2
            headers["Idempotency-Key"] = f"fresh-reference-{index:03}"
            assert client.post("/api/v1/box/frame", headers=headers, content=camera_frame()).json()["accepted"]
        assert client.get("/api/v1/box/status", headers={"X-Balut-Origin": "local"}).json()["calibrated"]
        now[0] += 2
        headers.update({"Idempotency-Key": "new-browser-frame", "X-Balut-Camera-Session": "aeae26c7-3d4b-41bd-9db2-2eec3a3fb3a7"})
        assert client.post("/api/v1/box/frame", headers=headers, content=camera_frame()).status_code == 200
        status = client.get("/api/v1/box/status", headers={"X-Balut-Origin": "local"}).json()
        assert status["calibrated"] and status["state"] == "checking_empty"
        assert client.post("/api/v1/device/box/frame", headers=headers, content=camera_frame()).status_code == 401
        client.post("/api/v1/auth/logout", headers={"Origin": ORIGIN, "X-Balut-Origin": "local"})
        assert client.post("/api/v1/box/frame", headers=headers, content=camera_frame()).status_code == 401


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
    assert not config.get("installCommand")  # Custom installation disables Vercel's bundle optimization.
    assert config["buildCommand"].startswith("npm ci && npm run build && ")
    assert "onnxruntime==" in (root / "requirements.txt").read_text()
    assert config["functions"]["app.py"]["maxDuration"] < 150
    assert len(config["functions"]["app.py"]["excludeFiles"]) <= 256
