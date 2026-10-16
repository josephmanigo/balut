import asyncio
import hashlib
import io
import time

from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from balut_api.browser_auth import hash_password
from balut_api.main import create_app
from balut_api.remote_camera import RemoteCamera, USB_ORIGIN
from scripts.upload_box_frames import frame_headers, render_origin
from test_production import settings_for

ORIGIN = "https://classroom.onrender.com"
PASSWORD = "render-test-passphrase"


@pytest.fixture(scope="module")
def password_hash():
    return hash_password(PASSWORD)


@pytest.fixture
def cloud(tmp_path, monkeypatch, password_hash):
    monkeypatch.setenv("BALUT_OPERATOR_USERNAME", "classroom")
    monkeypatch.setenv("BALUT_OPERATOR_PASSWORD_HASH", password_hash)
    settings = settings_for(tmp_path, cloud_origin=ORIGIN, max_request_bytes=160 * 1024)
    app = create_app(settings)
    with TestClient(app, base_url=ORIGIN, client=("203.0.113.10", 12345)) as client:
        yield client, app, settings


def jpeg(color="gray"):
    output = io.BytesIO()
    Image.new("RGB", (640, 480), color).save(output, "JPEG")
    return output.getvalue()


def test_cloud_uses_prepared_account_and_secure_cookies_and_blocks_local_admin_routes(cloud):
    client, _, settings = cloud
    assert client.get("/api/v1/auth/session").json() == {"authenticated": False, "username": None, "setupRequired": False, "cloudDemo": True}
    assert client.get("/api/v1/models").status_code == 401
    assert client.get("/api/v1/models", headers={"Authorization": "Bearer " + settings.local_admin_token}).status_code == 401
    headers = {"Origin": ORIGIN, "X-Balut-Origin": "local"}
    assert client.post("/api/v1/auth/register", json={}, headers=headers).status_code == 404
    response = client.post("/api/v1/auth/login", headers=headers, json={"username": "classroom", "password": PASSWORD})
    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"] and "HttpOnly" in response.headers["set-cookie"]
    assert client.get("/api/v1/models").status_code == 200
    assert client.get("/api/v1/box/status", headers=headers).status_code == 200
    assert client.post("/api/v1/box/enabled", headers={**headers, "Origin": "https://evil.example"}, json={"enabled": True}).status_code == 403
    assert client.get("/api/v1/audit").status_code == 404
    assert client.post("/api/v1/egg-analysis", headers=headers).status_code == 404
    assert client.get("/ready", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/ready").json()["automaticGradingReady"] is False
    assert client.get("/ready").headers["strict-transport-security"] == "max-age=31536000"


def test_cloud_frames_require_hmac_fresh_clock_checksum_and_unique_content(cloud):
    client, _, settings = cloud
    body = jpeg()
    path = "/api/v1/device/box/frame"
    headers = frame_headers(body, settings.device_shared_secret, "usb-test-frame-001", int(time.time()))
    assert client.post(path, content=body).status_code == 401
    assert client.post(path, content=body, headers={**headers, "X-Device-Signature": "0" * 64}).status_code == 401
    assert client.post(path, content=body, headers=frame_headers(body, settings.device_shared_secret, "old-frame-001", int(time.time()) - 60)).status_code == 401
    response = client.post(path, content=body, headers=headers)
    assert response.status_code == 200 and response.json()["repeated"] is False
    assert client.post(path, content=body, headers=headers).json()["repeated"] is True
    other = jpeg("red")
    assert client.post(path, content=other, headers=frame_headers(other, settings.device_shared_secret, "usb-test-frame-001", int(time.time()))).status_code == 409
    assert client.post(path, content=body + b"changed", headers=headers).status_code == 401


def test_remote_camera_consumes_new_frames_and_never_reuses_stale_input():
    class Box:
        config = {"reference": [0], "enabled": True}
        def require_new_reference(self): self.config = {"enabled": False}
    async def scenario():
        box = Box()
        camera = RemoteCamera(box, timeout=.02)
        first = jpeg()
        await camera.receive(first, "frame-key-001")
        assert await camera.fetch(USB_ORIGIN) == first
        with pytest.raises(ValueError, match="offline"):
            await camera.fetch(USB_ORIGIN)
        camera.received -= 1
        await camera.receive(first, "frame-key-002")
        camera.delivered -= 1
        with pytest.raises(ValueError, match="reconnected"):
            await camera.fetch(USB_ORIGIN)
        assert not box.config.get("reference") and not box.config["enabled"]
        with pytest.raises(ValueError, match="connector address"):
            await camera.fetch("http://192.168.1.1")
        camera.received -= 1
        with pytest.raises(HTTPException) as error:
            await camera.receive(b"not a JPEG", "bad-frame-003")
        assert error.value.status_code == 422
    asyncio.run(scenario())


def test_cloud_refuses_startup_without_prepared_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("BALUT_OPERATOR_USERNAME", raising=False)
    monkeypatch.delenv("BALUT_OPERATOR_PASSWORD_HASH", raising=False)
    with pytest.raises(RuntimeError, match="protected Render account"):
        with TestClient(create_app(settings_for(tmp_path, cloud_origin=ORIGIN))):
            pass


@pytest.mark.parametrize("origin", ["http://classroom.onrender.com", "https://evil.example", "https://classroom.onrender.com/path", "https://a.onrender.com@evil.example", "https://127.0.0.1"])
def test_render_connector_cannot_send_credentials_to_arbitrary_hosts(origin):
    with pytest.raises(ValueError):
        render_origin(origin)
