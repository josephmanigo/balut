import importlib.util
import json
import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from balut_api.database import Database
from balut_api.browser_auth import hash_password, verify_password

spec = importlib.util.spec_from_file_location("backup_serving", Path(__file__).resolve().parents[3] / "scripts/backup_serving.py")
backup_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup_module)


def test_missing_evidence_cannot_create_completed_backup(tmp_path):
    db = Database(tmp_path / "source.db")
    db.initialize()
    with db.connect() as connection:
        connection.execute("INSERT INTO model_predictions VALUES (?, ?, ?, ?, ?, ?)", ("p", "model", "release", "a"*64, "{}", "now"))
        connection.commit()
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"database_path": str(db.path), "evidence_path": str(tmp_path / "evidence"), "model_registry_sha256": "a"*64}))
    output = tmp_path / "backup"
    with pytest.raises(ValueError, match="missing or corrupt"):
        backup_module.backup(profile, output)
    assert not (output / "backup.json").exists()


@pytest.mark.parametrize("files", [{}, {"balut.db": "a"*64, "../escape": "b"*64}])
def test_invalid_backup_never_creates_restore_target(tmp_path, files):
    source = tmp_path / "source"
    source.mkdir()
    (source / "backup.json").write_text(json.dumps({"schema_version": 1, "complete": True, "files": files}))
    output = tmp_path / "restored"
    with pytest.raises(ValueError):
        backup_module.restore(source, output)
    assert not output.exists()


def create_live_backup(tmp_path):
    db = Database(tmp_path / "source.db")
    db.initialize()
    image = b"test evidence bytes"
    digest = hashlib.sha256(image).hexdigest()
    evidence = tmp_path / "evidence" / digest[:2] / (digest + ".jpg")
    evidence.parent.mkdir(parents=True)
    evidence.write_bytes(image)
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"database_path": str(db.path), "evidence_path": str(tmp_path / "evidence"), "model_registry_sha256": "a"*64}))
    output = tmp_path / "backup"
    with closing(sqlite3.connect(db.path)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO model_predictions VALUES (?, ?, ?, ?, ?, ?)", ("p", "model", "release", digest, '{"saved":true}', "now"))
        writer.commit()
        assert Path(str(db.path) + "-wal").is_file()
        manifest = backup_module.backup(profile, output)
    return output, manifest, digest, image


def test_live_wal_backup_restores_standalone_database_and_all_evidence(tmp_path):
    source, manifest, digest, image = create_live_backup(tmp_path)
    name = f"evidence/{digest[:2]}/{digest}.jpg"
    assert set(manifest["files"]) == {"balut.db", name}
    assert not (source / "balut.db-wal").exists()
    assert not (source / "balut.db-shm").exists()
    output = tmp_path / "restored"
    assert backup_module.restore(source, output)["restored"]
    with closing(sqlite3.connect(output / "balut.db")) as db:
        assert db.execute("SELECT response_json FROM model_predictions WHERE id='p'").fetchone() == ('{"saved":true}',)
    assert (output / name).read_bytes() == image


def test_restore_rejects_manifest_that_omits_required_evidence(tmp_path):
    source, manifest, digest, _ = create_live_backup(tmp_path)
    del manifest["files"][f"evidence/{digest[:2]}/{digest}.jpg"]
    (source / "backup.json").write_text(json.dumps(manifest))
    output = tmp_path / "restored"
    with pytest.raises(ValueError, match="inventory does not match"):
        backup_module.restore(source, output)
    assert not output.exists()


def test_backup_restores_local_account_and_marks_hash_as_sensitive(tmp_path):
    db = Database(tmp_path / "source.db")
    db.initialize()
    db.create_operator_account("myaccount", hash_password("my chosen passphrase"))
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"database_path": str(db.path), "evidence_path": str(tmp_path / "evidence"), "model_registry_sha256": "a" * 64}))
    output = tmp_path / "backup"
    manifest = backup_module.backup(profile, output)
    assert manifest["credentials_included"] is True
    assert manifest["account_password_hash_included"] is True
    assert manifest["profile_credentials_included"] is False
    restored = tmp_path / "restored"
    backup_module.restore(output, restored)
    account = Database(restored / "balut.db").get_operator_account()
    assert account["username"] == "myaccount"
    assert verify_password("my chosen passphrase", account["password_hash"])
