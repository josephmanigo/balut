import httpx
import pytest
from fastapi.testclient import TestClient

from balut_api.cloud_gateway import create_gateway

KEY = "test-key-" + "a" * 40


@pytest.fixture
def gateway():
    calls = []
    def upstream(request):
        calls.append(request)
        return httpx.Response(200, json={"connected": True}, headers={"Set-Cookie": "balut_session=" + "b" * 43 + "; Path=/; HttpOnly; SameSite=strict"})
    with TestClient(create_gateway(KEY, httpx.MockTransport(upstream)), headers={"X-Balut-Box-Key": KEY}) as client:
        yield client, calls


def test_gateway_forwards_only_session_and_fixed_local_headers(gateway):
    client, calls = gateway
    response = client.post("/api/v1/auth/login", json={"username": "operator", "password": "test"},
                           headers={"Cookie": "other=private; balut_session=" + "c" * 43,
                                    "Authorization": "Bearer do-not-forward", "Origin": "https://web.example",
                                    "Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "; Secure" in response.headers["set-cookie"]
    request = calls[0]
    assert str(request.url) == "http://127.0.0.1:8765/api/v1/auth/login"
    assert request.headers["cookie"] == "balut_session=" + "c" * 43
    assert request.headers["X-Balut-Origin"] == "local"
    for name in ("Authorization", "Origin", "Sec-Fetch-Site", "X-Balut-Box-Key"):
        assert name not in request.headers


@pytest.mark.parametrize("method,path,body,status", [
    ("POST", "/api/v1/auth/register", {}, 404), ("GET", "/health", None, 404),
    ("POST", "/api/v1/box/status", {}, 405), ("GET", "/api/v1/box/status?url=http://evil", None, 400),
    ("GET", "/api/v1/model-predictions?limit=101", None, 400),
    ("GET", "/api/v1/model-predictions?limit=1&limit=2", None, 400),
    ("POST", "/api/v1/box/connect", {"cameraUrl": "http://192.168.1.1"}, 400),
    ("POST", "/api/v1/auth/login", [], 400), ("POST", "/api/v1/auth/login", {"x": "a" * 17000}, 413),
])
def test_gateway_denies_routes_queries_and_non_usb_destinations(gateway, method, path, body, status):
    client, calls = gateway
    assert client.request(method, path, json=body).status_code == status
    assert not calls


def test_gateway_rejects_missing_key_and_non_json(gateway):
    client, calls = gateway
    assert client.get("/api/v1/auth/session", headers={"X-Balut-Box-Key": "bad"}).status_code == 403
    assert client.post("/api/v1/auth/login", content="{}").status_code == 415
    assert not calls


def test_gateway_allows_usb_and_bounded_history(gateway):
    client, calls = gateway
    assert client.post("/api/v1/box/connect", json={"cameraUrl": "http://127.0.0.1:8767"}).status_code == 200
    assert client.get("/api/v1/model-predictions?limit=50").status_code == 200
    assert calls[-1].url.query == b"limit=50"
    assert calls[-1].headers["cookie"] == ""
    assert client.post("/api/v1/auth/logout", headers={"Content-Type": "application/json"}).status_code == 200


@pytest.mark.parametrize("kind", ["redirect", "html", "large", "offline"])
def test_gateway_never_follows_redirects_or_returns_unbounded_errors(kind):
    calls = []
    def upstream(request):
        calls.append(request)
        if kind == "offline":
            raise httpx.ConnectError("private path", request=request)
        if kind == "redirect":
            return httpx.Response(302, headers={"Location": "http://evil"})
        if kind == "html":
            return httpx.Response(200, text="private error")
        return httpx.Response(200, content=b"a" * (2 * 1024 * 1024 + 1), headers={"Content-Type": "application/json"})
    with TestClient(create_gateway(KEY, httpx.MockTransport(upstream))) as client:
        response = client.get("/api/v1/box/status", headers={"X-Balut-Box-Key": KEY})
        assert response.status_code == (503 if kind == "offline" else 502)
        assert "private" not in response.text
    assert len(calls) == 1
