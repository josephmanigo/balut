import time

from fastapi import Request
from fastapi.testclient import TestClient

from balut_api.browser_auth import COOKIE_NAME, verify_password
from balut_api.main import create_app
from balut_api.security import require_local_operator
from test_production import settings_for

LOCAL = {"X-Balut-Origin": "local", "Origin": "http://127.0.0.1"}
LOGIN = {"username": "operator", "password": "a" * 48}


def register(client, **updates):
    credentials = {**LOGIN, **updates}
    return client.post("/api/v1/auth/register", json={**credentials, "confirmPassword": credentials["password"]}, headers=LOCAL)


def test_browser_login_expiry_and_logout_protect_records(tmp_path):
    app = create_app(settings_for(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/api/v1/auth/session").json() == {"authenticated": False, "username": None, "setupRequired": True}
        denied = client.get("/api/v1/model-predictions")
        assert denied.status_code == 401 and "www-authenticate" not in denied.headers
        assert register(client).status_code == 201
        client.post("/api/v1/auth/logout", headers=LOCAL)
        wrong = client.post("/api/v1/auth/login", json={**LOGIN, "password": "wrong"}, headers=LOCAL)
        assert wrong.status_code == 401 and "set-cookie" not in wrong.headers
        response = client.post("/api/v1/auth/login", json=LOGIN, headers=LOCAL)
        assert response.status_code == 200
        assert "HttpOnly" in response.headers["set-cookie"] and "SameSite=strict" in response.headers["set-cookie"]
        token = client.cookies.get(COOKIE_NAME)
        assert token != LOGIN["password"]
        assert client.get("/api/v1/auth/session").json()["authenticated"] is True
        assert client.get("/api/v1/dashboard").status_code == 200
        # Cookie authentication must reach write handlers too, with local-presence checks intact.
        assert client.post("/api/v1/model-predictions/unknown", headers={**LOCAL, "Idempotency-Key": "browser-test-001"}).status_code == 404
        assert client.post("/api/v1/model-predictions/unknown").status_code == 403
        assert client.post("/api/v1/auth/logout", headers=LOCAL).status_code == 200
        client.cookies.set(COOKIE_NAME, token)
        assert client.get("/api/v1/dashboard").status_code == 401
        client.cookies.clear()
        client.post("/api/v1/auth/login", json=LOGIN, headers=LOCAL)
        app.state.browser_sessions.tokens[client.cookies.get(COOKIE_NAME)] = (time.monotonic() - 1, "operator")
        assert client.get("/api/v1/auth/session").json()["authenticated"] is False
        assert client.get("/api/v1/dashboard").status_code == 401


def test_login_rejects_cross_site_and_throttles_guesses(tmp_path):
    with TestClient(create_app(settings_for(tmp_path)), base_url="http://127.0.0.1") as client:
        assert client.post("/api/v1/auth/login", json=LOGIN).status_code == 403
        for extra in ({"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
            assert client.post("/api/v1/auth/login", json=LOGIN, headers={**LOCAL, **extra}).status_code == 403
            assert client.post("/api/v1/auth/register", json={**LOGIN, "confirmPassword": LOGIN["password"]}, headers={**LOCAL, **extra}).status_code == 403
        assert register(client).status_code == 201
        client.post("/api/v1/auth/logout", headers=LOCAL)
        for _ in range(10):
            assert client.post("/api/v1/auth/login", json={**LOGIN, "username": "wrong"}, headers=LOCAL).status_code == 401
        response = client.post("/api/v1/auth/login", json=LOGIN, headers=LOCAL)
        assert response.status_code == 429 and response.headers["retry-after"] == "60"


def test_only_app_shell_is_public_and_history_reads_saved_predictions(tmp_path):
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<h1>Sign in</h1>")
    (web / "assets" / "main.js").write_text("// public app code")
    app = create_app(settings_for(tmp_path, web_dist_path=web))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/").status_code == 200
        assert client.get("/assets/main.js").status_code == 200
        assert client.get("/api/v1/model-predictions/records/missing").status_code == 401
        assert client.get("/api/v1/auth/unknown").status_code == 401
        assert register(client).status_code == 201
        database = app.state.database
        for key in ("first-record", "second-record"):
            database.record_prediction({"modelId": "fixture-model", "modelReleaseId": "test-only", "sourcePrediction": "DAY_16"}, "a" * 64, "test", key, key)
        saved = database.list_predictions()
        response = client.get("/api/v1/model-predictions?limit=1")
        assert response.status_code == 200 and response.json()["items"] == saved[:1]
        assert len(saved) == 2
        assert client.get("/api/v1/model-predictions?limit=0").status_code == 422


def test_account_persists_and_cannot_be_replaced_or_impersonated(tmp_path):
    settings = settings_for(tmp_path)
    app = create_app(settings)
    @app.get("/api/v1/test-actor")
    def actor(request: Request):
        return {"actor": require_local_operator(request, settings)}
    credentials = {"username": "My.name", "password": "my chosen passphrase"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = register(client, **credentials)
        assert response.status_code == 201 and response.json()["username"] == "my.name"
        stored = app.state.database.get_operator_account()
        assert stored["password_hash"] != credentials["password"]
        assert credentials["password"] not in stored["password_hash"]
        assert stored["password_hash"].startswith("scrypt$131072$8$1$")
        assert verify_password(credentials["password"], stored["password_hash"])
        assert not verify_password("different password", stored["password_hash"])
        assert client.get("/api/v1/test-actor", headers={**LOCAL, "X-Actor-Id": "forged"}).json()["actor"] == "my.name"
        assert register(client, username="my.name", password="replacement passphrase").status_code == 409
        assert app.state.database.get_operator_account() == stored
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        assert client.get("/api/v1/auth/session").json()["setupRequired"] is False
        assert client.get("/api/v1/auth/session").json()["authenticated"] is False
        assert client.post("/api/v1/auth/login", json=credentials, headers=LOCAL).status_code == 200
        assert client.get("/api/v1/dashboard").status_code == 200
        assert client.post("/api/v1/auth/login", json=LOGIN, headers=LOCAL).status_code == 401


def test_account_validation_does_not_save_invalid_credentials(tmp_path):
    app = create_app(settings_for(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert register(client, password="short").status_code == 422
        assert register(client, username="bad name").status_code == 400
        mismatch = client.post("/api/v1/auth/register", headers=LOCAL, json={**LOGIN, "confirmPassword": "different password"})
        assert mismatch.status_code == 400
        assert app.state.database.get_operator_account() is None
