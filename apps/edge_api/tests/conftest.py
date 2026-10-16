from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from balut_api.config import Settings
from balut_api.main import create_app


@pytest.fixture()
def client(tmp_path: Path):
    settings = Settings(
        environment="test",
        database_path=tmp_path / "balut-test.db",
        evidence_path=tmp_path / "evidence",
        local_admin_token="test-local-token",
        device_shared_secret="test-device-secret",
        allow_simulator=True,
        cors_origins=("http://localhost:5173",),
    )
    application = create_app(settings)
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture()
def local_headers():
    return {
        "Authorization": "Bearer test-local-token",
        "X-Balut-Origin": "local",
        "X-Actor-Id": "operator-test",
    }

