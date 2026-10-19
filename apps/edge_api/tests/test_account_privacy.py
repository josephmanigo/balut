import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from balut_api.browser_auth import COOKIE_NAME
from balut_api.database import Database
from balut_api.main import create_app
from balut_api.automatic_box import claim_camera
from balut_api.serverless_box import ServerlessBox
from balut_api.supabase_store import Supabase
from test_automatic_box import make_box, frame
from test_browser_auth import LOCAL, LOGIN, register
from test_production import settings_for
from test_supabase_store import provider, shared_settings
from test_supabase_store import URL, SECRET
from test_serverless import shared


@pytest.mark.parametrize("cloud", [False, True])
def test_signup_keeps_accounts_sessions_and_history_separate(tmp_path, provider, cloud):
    settings = shared_settings(tmp_path) if cloud else settings_for(tmp_path)
    app = create_app(settings)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert register(client).status_code == 201
        first_token = client.cookies.get(COOKIE_NAME)
        database = app.state.database
        first = database.record_prediction({"modelId": "fixture", "modelReleaseId": "fixture"}, "a" * 64, "operator", "first-user-key", "b" * 64)
        assert register(client, username="second").status_code == 201
        second_token = client.cookies.get(COOKIE_NAME)
        assert client.get("/api/v1/model-predictions").json() == {"items": []}
        assert client.get("/api/v1/model-predictions/records/" + first["predictionId"]).status_code == 404
        second = database.record_prediction({"modelId": "fixture", "modelReleaseId": "fixture"}, "c" * 64, "second", "second-user-key", "d" * 64)
        assert client.get("/api/v1/model-predictions", headers={"X-Actor-Id": "operator"}, params={"owner": "operator"}).json() == {"items": [second]}
        assert client.get("/api/v1/audit", headers=LOCAL).status_code == 403
        duplicate = register(client, username="OPERATOR", password="replacement-passphrase")
        assert duplicate.status_code == 409
        assert client.get("/api/v1/auth/session").json()["username"] == "second"
        client.cookies.clear()
        client.cookies.set(COOKIE_NAME, first_token, domain="127.0.0.1", path="/")
        assert client.get("/api/v1/auth/session").json()["authenticated"] is True
        assert client.get("/api/v1/model-predictions").json() == {"items": [first]}
        assert client.get("/api/v1/model-predictions/records/" + second["predictionId"]).status_code == 404
        app.state.box.config["owner"] = "operator"
        app.state.box.preview, app.state.box.result = "private-image", first
        client.cookies.clear()
        client.cookies.set(COOKIE_NAME, second_token, domain="127.0.0.1", path="/")
        status = client.get("/api/v1/box/status", headers=LOCAL).json()
        assert status["result"] is None and status["preview"] is None
        client.post("/api/v1/auth/logout", headers=LOCAL)
        assert client.post("/api/v1/auth/login", json={**LOGIN, "username": "second"}, headers=LOCAL).status_code == 200
        assert client.get("/api/v1/model-predictions").json() == {"items": [second]}
        client.post("/api/v1/auth/logout", headers=LOCAL)
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        assert client.post("/api/v1/auth/login", json=LOGIN, headers=LOCAL).status_code == 200
        assert client.get("/api/v1/model-predictions").json() == {"items": [first]}


def test_legacy_single_account_and_records_upgrade_without_changing_credentials(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE operator_account (id INTEGER PRIMARY KEY CHECK (id = 1), username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, created_at TEXT NOT NULL);
            INSERT INTO operator_account VALUES (1, 'original', 'unchanged-password-hash', 'old-date');
            CREATE TABLE model_predictions (id TEXT PRIMARY KEY, model_id TEXT NOT NULL, release_id TEXT NOT NULL, image_sha256 TEXT NOT NULL, response_json TEXT NOT NULL, created_at TEXT NOT NULL);
        """)
        connection.execute("INSERT INTO model_predictions VALUES (?, ?, ?, ?, ?, ?)", ("old-record", "fixture", "fixture", "a" * 64, json.dumps({"saved": True}), "old-date"))
    database = Database(path)
    database.initialize()
    assert database.get_operator_account() == {"username": "original", "password_hash": "unchanged-password-hash"}
    assert database.list_predictions(owner="original") == [{"saved": True}]
    assert database.create_operator_account("second", "second-hash")
    assert not database.create_operator_account("original", "replacement")
    assert database.get_prediction("old-record", "second") is None
    database.initialize()
    assert database.get_operator_account("second")["password_hash"] == "second-hash"
    assert database.list_predictions(owner="original") == [{"saved": True}]


def test_shared_camera_hides_old_result_and_saves_new_captures_to_current_account(tmp_path, shared):
    box, _ = make_box(tmp_path)
    box.database.create_operator_account("first", "hash-one")
    box.database.create_operator_account("second", "hash-two")
    worker = ServerlessBox(box.database, box.evidence, box.predict, Supabase(URL, SECRET))
    shared["camera"] = {"config": {"owner": "first"}, "received": time.time(), "preview": "private-preview", "result": {"private": True}}
    status = worker.status(owner="second")
    assert status["preview"] is None and status["result"] is None
    assert worker.status(owner="first")["preview"] == "private-preview"
    worker.mutate(lambda saved: claim_camera(saved, "second"))
    saved = worker.box(shared["camera"])
    result = saved.predict(frame(), "new-owner-capture")
    assert box.database.get_prediction(result["predictionId"], "second") == result
    assert box.database.get_prediction(result["predictionId"], "first") is None
