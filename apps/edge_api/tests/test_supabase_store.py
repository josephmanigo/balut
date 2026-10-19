import hashlib
import io
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from balut_api.database import Database
from balut_api.evidence import EvidenceStore
from balut_api.main import create_app
from balut_api.supabase_store import CloudStorageError, Supabase, SupabaseDatabase, SupabaseEvidence
from scripts.migrate_supabase import migrate, prepare_records
from test_browser_auth import LOCAL, LOGIN, register
from test_production import settings_for

URL = "https://balut-test.supabase.co"
SECRET = "sb_secret_" + "x" * 40


@pytest.fixture
def provider(monkeypatch):
    state = {"account": None, "predictions": {}, "images": {}, "down": False, "public": False}
    upstream = httpx.Client.request

    def request(self, method, url, **kwargs):
        if isinstance(self, TestClient):
            return upstream(self, method, url, **kwargs)
        assert kwargs["headers"]["apikey"] == SECRET
        assert "Authorization" not in kwargs["headers"]
        path = url.removeprefix(URL)
        params, body = kwargs.get("params", {}), kwargs.get("json", {})
        def reply(value, code=200): return httpx.Response(code, json=value)
        if state["down"]:
            raise httpx.ConnectError("private provider diagnostics")
        if path == "/storage/v1/bucket/balut-evidence":
            return reply({"public": state["public"]})
        if path == "/rest/v1/balut_account":
            if method == "POST":
                if state["account"]: return reply([])
                state["account"] = {name: body[name] for name in ("username", "password_hash")}
            return reply([state["account"]] if state["account"] else [])
        if path.startswith("/storage/v1/object/"):
            if method == "GET":
                assert "/object/authenticated/" in path
                path = path.replace("/object/authenticated/", "/object/", 1)
            if method == "POST":
                if path in state["images"]: return reply({"error": "Duplicate"}, 400)
                state["images"][path] = kwargs["content"]
                return reply({})
            return httpx.Response(200, content=state["images"][path]) if path in state["images"] else reply({"error": "NoSuchKey"}, 400)
        if path == "/rest/v1/rpc/balut_record_prediction":
            key = (body["p_actor"], body["p_key"])
            if key in state["predictions"]:
                old = state["predictions"][key]
                return reply(old["response"]) if old["request_hash"] == body["p_hash"] else reply({}, 409)
            row = {"response": body["p_response"], "request_hash": body["p_hash"]}
            state["predictions"][key] = row
            return reply(row["response"])
        if path == "/rest/v1/balut_predictions":
            rows = list(state["predictions"].values())[::-1]
            if "actor_id" in params:
                row = state["predictions"].get((params["actor_id"][3:], params["request_key"][3:]))
                rows = [row] if row else []
            if "id" in params: rows = [row for row in rows if row["response"]["predictionId"] == params["id"][3:]]
            return reply(rows[:int(params.get("limit", 50))])
        raise AssertionError((method, path))
    monkeypatch.setattr(httpx.Client, "request", request)
    return state


def image():
    output = io.BytesIO()
    Image.new("RGB", (64, 64), "orange").save(output, "JPEG")
    body = output.getvalue()
    return body, hashlib.sha256(body).hexdigest()


def shared_settings(path):
    return settings_for(path, supabase_url=URL, supabase_secret_key=SECRET)


def test_account_history_and_images_survive_a_new_backend_and_local_cache_loss(tmp_path, provider):
    first = create_app(shared_settings(tmp_path / "laptop-one"))
    body, digest = image()
    with TestClient(first, base_url="http://127.0.0.1") as client:
        assert register(client).status_code == 201
        assert client.get("/api/v1/auth/session").json()["sharedStorage"] is True
        SupabaseEvidence(tmp_path / "images-one", first.state.database.cloud).store_jpeg(body, digest)
        saved = first.state.database.record_prediction({"modelId": "test", "modelReleaseId": "fixture"}, digest, "operator", "capture-one", "a" * 64)
    second = create_app(shared_settings(tmp_path / "laptop-two"))
    with TestClient(second, base_url="http://127.0.0.1") as client:
        assert client.get("/api/v1/model-predictions").status_code == 401
        assert client.post("/api/v1/auth/login", json=LOGIN, headers=LOCAL).status_code == 200
        assert client.get("/api/v1/model-predictions").json()["items"] == [saved]
        assert client.get("/api/v1/model-predictions/records/" + saved["predictionId"]).json() == saved
        evidence = SupabaseEvidence(tmp_path / "images-two", second.state.database.cloud)
        assert evidence.contains(digest) and evidence.path_for(digest).read_bytes() == body
        assert client.get("/ready").status_code == 200
        provider["down"] = True
        assert client.get("/api/v1/model-predictions").status_code == 503
        assert client.get("/ready").status_code == 503
        assert "private provider" not in client.get("/api/v1/auth/session").text


def test_idempotency_retries_conflicts_and_failed_uploads(tmp_path, provider):
    cloud = Supabase(URL, SECRET)
    database = SupabaseDatabase(tmp_path / "local.db", cloud)
    body, digest = image()
    evidence = SupabaseEvidence(tmp_path / "images", cloud)
    evidence.store_jpeg(body, digest)
    evidence.store_jpeg(body, digest)
    saved = database.record_prediction({"modelId": "test", "modelReleaseId": "fixture"}, digest, "actor", "same", "b" * 64)
    assert database.record_prediction({"modelId": "test", "modelReleaseId": "fixture"}, digest, "actor", "same", "b" * 64) == saved
    assert database.prediction_replay("actor", "same", "b" * 64) == saved
    with pytest.raises(ValueError, match="idempotency"):
        database.prediction_replay("actor", "same", "c" * 64)
    with pytest.raises(ValueError, match="idempotency"):
        database.record_prediction({}, digest, "actor", "same", "c" * 64)
    provider["down"] = True
    with pytest.raises(CloudStorageError): evidence.store_jpeg(body, digest)
    assert len(provider["predictions"]) == 1


def test_private_bucket_and_complete_configuration_required(tmp_path, provider):
    settings = shared_settings(tmp_path)
    with pytest.raises(RuntimeError, match="both"):
        replace(settings, supabase_secret_key=None).validate()
    with pytest.raises(RuntimeError, match="HTTPS"):
        replace(settings, supabase_url="https://evil.example").validate()
    assert SECRET not in repr(settings)
    provider["public"] = True
    with pytest.raises(CloudStorageError, match="private"):
        Supabase(URL, SECRET).check()


def test_cloud_failure_never_accepts_a_prediction_from_the_local_cache(tmp_path, provider):
    app = create_app(shared_settings(tmp_path))
    body, digest = image()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert register(client).status_code == 201
        model = app.state.model_service
        model.models["fixture"] = object()
        model.registry_sha256 = "e" * 64
        model.predict = lambda *_: {"modelId": "fixture", "modelReleaseId": "test-only"}
        provider["down"] = True
        response = client.post("/api/v1/model-predictions/fixture", content=body,
                               headers={**LOCAL, "Content-Type": "image/jpeg", "Idempotency-Key": "capture-test-001"})
        assert response.status_code == 503
        assert not provider["predictions"]
        with app.state.database.connect() as connection:
            assert connection.execute("SELECT count(*) FROM model_predictions").fetchone()[0] == 0
        model.models.clear()


def test_existing_local_account_and_history_migrate_without_replacement(tmp_path, provider):
    local = Database(tmp_path / "source.db")
    local.initialize()
    local.create_operator_account("original", "existing-password-hash")
    evidence = EvidenceStore(tmp_path / "source-images")
    body, digest = image()
    evidence.store_jpeg(body, digest)
    saved = local.record_prediction({"modelId": "test", "modelReleaseId": "fixture"}, digest, "original", "original-key", "d" * 64)
    cloud = Supabase(URL, SECRET)
    remote = SupabaseDatabase(tmp_path / "new.db", cloud)
    remote_evidence = SupabaseEvidence(tmp_path / "new-images", cloud)
    assert migrate(local, evidence, remote, remote_evidence)["predictionsVerified"] == 1
    assert migrate(local, evidence, remote, remote_evidence)["predictionsVerified"] == 1
    assert remote.get_prediction(saved["predictionId"]) == saved
    assert local.list_predictions() == [saved]
    provider["account"] = {"username": "another", "password_hash": "another"}
    with pytest.raises(RuntimeError, match="different account"):
        migrate(local, evidence, remote, remote_evidence)
    evidence.path_for(digest).unlink()
    with pytest.raises(RuntimeError, match="missing or damaged"):
        prepare_records(local, evidence)
