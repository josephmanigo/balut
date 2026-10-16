import pytest
from fastapi.testclient import TestClient

from balut_api.main import create_app
from test_production import settings_for

ORIGIN = "https://192.168.2.2:8765"
LOCAL = {"Origin": ORIGIN, "X-Balut-Origin": "local"}


@pytest.mark.parametrize("origin", ["http://192.168.2.2:8765", "https://0.0.0.0:8765", "https://8.8.8.8:8765", "https://camera.local:8765", "https://192.168.2.2", "https://192.168.2.2:0", "https://user@192.168.2.2:8765", "https://192.168.2.2:8765/", "https://192.168.2.2:8765?x=1"])
def test_https_configuration_rejects_unsafe_origins(tmp_path, origin):
    with pytest.raises(RuntimeError, match="HTTPS origin"):
        settings_for(tmp_path, https_origin=origin).validate()


def test_phone_auth_uses_secure_cookie_and_keeps_origin_protection(tmp_path):
    app = create_app(settings_for(tmp_path, https_origin=ORIGIN))
    with TestClient(app, base_url=ORIGIN, client=("192.168.2.10", 50000)) as client:
        assert client.get("/ready").status_code == 200
        assert client.get("/api/v1/dashboard").status_code == 401
        account = {"username": "phone-owner", "password": "test-local-passphrase"}
        response = client.post("/api/v1/auth/register", json={**account, "confirmPassword": account["password"]}, headers=LOCAL)
        assert response.status_code == 201
        cookie = response.headers["set-cookie"]
        assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
        assert client.get("/api/v1/box/status", headers=LOCAL).status_code == 200
        for headers in ({"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
            assert client.post("/api/v1/box/enabled", json={"enabled": False}, headers={**LOCAL, **headers}).status_code == 403
        assert client.post("/api/v1/box/enabled", json={"enabled": False}, headers=LOCAL).status_code == 200
        assert client.post("/api/v1/auth/logout", headers=LOCAL).status_code == 200
        assert client.get("/api/v1/dashboard").status_code == 401
        assert client.post("/api/v1/auth/login", json=account, headers=LOCAL).status_code == 200


def test_phone_endpoint_rejects_wrong_host_plaintext_and_public_clients(tmp_path):
    app = create_app(settings_for(tmp_path, https_origin=ORIGIN))
    with TestClient(app, base_url=ORIGIN) as client:
        for host in ("evil.example", "127.0.0.1:8765", "192.168.2.2:8766"):
            assert client.get("/ready", headers={"Host": host}).status_code == 400
        assert client.get("http://192.168.2.2:8765/ready").status_code == 400
    with TestClient(app, base_url=ORIGIN, client=("8.8.8.8", 50000)) as client:
        assert client.get("/ready").status_code == 403
