"""Preview or copy the existing account/history/images into an empty shared workspace.

Run with the backend stopped for the final migration. This never changes the source DB.
Credentials are read from the protected deployment/private/supabase.json file, not arguments.
"""
import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/edge_api"))

from balut_api.config import Settings
from balut_api.database import Database
from balut_api.evidence import EvidenceStore
from balut_api.supabase_store import Supabase, SupabaseDatabase, SupabaseEvidence


def prepare_records(database, evidence):
    with database.connect() as connection:
        predictions = connection.execute("SELECT response_json, image_sha256 FROM model_predictions ORDER BY created_at, rowid").fetchall()
        requests = connection.execute("SELECT * FROM idempotency_records WHERE endpoint LIKE 'model-prediction:%'").fetchall()
    by_id = {json.loads(row["response_json"])["predictionId"]: row for row in requests}
    records = []
    for prediction in predictions:
        response = json.loads(prediction["response_json"])
        request = by_id.get(response["predictionId"])
        if request is None or json.loads(request["response_json"]) != response:
            raise RuntimeError("A saved prediction has no matching idempotency record; migration stopped")
        digest = prediction["image_sha256"]
        if response["imageSha256"] != digest or not evidence.contains(digest):
            raise RuntimeError("A saved image is missing or damaged; migration stopped")
        records.append((response, request["endpoint"].removeprefix("model-prediction:"),
                        request["idempotency_key"], request["request_hash"]))
    return records


def migrate(database, evidence, remote, remote_evidence):
    records = prepare_records(database, evidence)
    account = database.get_operator_account()
    if account is None:
        raise RuntimeError("Create the local account before migrating")
    existing = remote.get_operator_account()
    if existing is not None and existing != account:
        raise RuntimeError("Supabase already has a different account; nothing overwritten")
    if existing is None:
        remote.create_operator_account(account["username"], account["password_hash"])
    if remote.get_operator_account() != account:
        raise RuntimeError("Shared account verification failed")
    for response, actor, key, request_hash in records:
        digest = response["imageSha256"]
        body = evidence.path_for(digest).read_bytes()
        remote_evidence.store_jpeg(body, digest)
        if remote.import_prediction(response, actor, key, request_hash) != response:
            raise RuntimeError("Existing prediction conflicts with the migration; nothing overwritten")
        if remote.get_prediction(response["predictionId"]) != response:
            raise RuntimeError("Migrated prediction verification failed")
        downloaded = remote.cloud.request("GET", remote_evidence.download_path(digest)).content
        if hashlib.sha256(downloaded).hexdigest() != digest:
            raise RuntimeError("Migrated image verification failed")
    return {"accountVerified": True, "predictionsVerified": len(records), "imagesVerified": len(records)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=ROOT / "deployment/private/windows.json")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text(encoding="utf-8-sig"))
    source_path = Path(profile["database_path"])
    if not source_path.is_file():
        raise RuntimeError("Source database does not exist")
    # A consistent SQLite backup includes committed WAL data without editing the original.
    backup = args.profile.parent / ("supabase-backup-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    backup.mkdir()
    snapshot = backup / "balut.db"
    with sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True) as source:
        with sqlite3.connect(snapshot) as destination:
            source.backup(destination)
    database, evidence = Database(snapshot), EvidenceStore(Path(profile["evidence_path"]))
    records = prepare_records(database, evidence)
    if not args.apply:
        print(json.dumps({"apply": False, "accountPresent": database.get_operator_account() is not None,
                          "predictions": len(records), "backup": str(snapshot)}))
        return
    shared = json.loads((args.profile.parent / "supabase.json").read_text(encoding="utf-8-sig"))
    settings = Settings(environment="test", database_path=snapshot, evidence_path=evidence.root,
                        local_admin_token="migration", device_shared_secret="migration-device",
                        allow_simulator=False, cors_origins=(), supabase_url=shared["url"],
                        supabase_secret_key=shared["secret_key"])
    settings.validate()
    cloud = Supabase(settings.supabase_url, settings.supabase_secret_key)
    cloud.check()
    report = migrate(database, evidence, SupabaseDatabase(snapshot, cloud), SupabaseEvidence(backup / "verified-images", cloud))
    (backup / "migration-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**report, "backup": str(snapshot)}))


if __name__ == "__main__":
    main()
