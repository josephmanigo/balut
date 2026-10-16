"""Create a consistent SQLite/evidence backup or restore it into a fresh directory."""
from pathlib import Path
from contextlib import closing
import argparse
import hashlib
import json
import shutil
import sqlite3
import re


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024*1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_database(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Backup database integrity check failed")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"model_predictions", "audit_events", "idempotency_records", "staged_evidence", "view_frames"}.issubset(tables):
            raise ValueError("Backup database schema is incomplete")


def evidence_files(database):
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        hashes = {row[0] for row in connection.execute("SELECT image_sha256 FROM staged_evidence UNION SELECT image_sha256 FROM view_frames UNION SELECT image_sha256 FROM model_predictions") if row[0]}
    if any(len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest) for digest in hashes):
        raise ValueError("Invalid evidence reference in snapshot")
    return {f"evidence/{digest[:2]}/{digest}.jpg": digest for digest in hashes}


def backup(profile, output):
    settings = json.loads(profile.read_text(encoding="utf-8-sig"))
    source_path = Path(settings["database_path"])
    if not source_path.is_file():
        raise ValueError("Source database is missing")
    output.mkdir(parents=True, exist_ok=False)
    snapshot = output / "balut.db"
    with closing(sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True)) as source, closing(sqlite3.connect(snapshot)) as target:
        source.backup(target)
        # Seal the copied database as a standalone file. The live database may
        # use WAL, but a completed backup must never depend on its sidecars.
        if target.execute("PRAGMA journal_mode=DELETE").fetchone()[0] != "delete":
            raise ValueError("Could not seal standalone backup database")
    check_database(snapshot)
    with closing(sqlite3.connect(snapshot)) as account_db:
        has_account_table = account_db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='operator_account'").fetchone()
        has_account = bool(has_account_table and account_db.execute("SELECT 1 FROM operator_account LIMIT 1").fetchone())
    required = evidence_files(snapshot)
    for name, digest in sorted(required.items()):
        relative = Path(name)
        source = Path(settings["evidence_path"]) / digest[:2] / (digest + ".jpg")
        if not source.is_file() or sha(source) != digest:
            raise ValueError("Referenced evidence is missing or corrupt; backup is incomplete")
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    inventory = {name: sha(output / name) for name in ["balut.db", *required]}
    manifest = {"schema_version": 1, "complete": True, "evidence_files": len(required), "files": inventory,
                "registry_sha256": settings["model_registry_sha256"], "credentials_included": has_account,
                "account_password_hash_included": has_account, "profile_credentials_included": False}
    (output / "backup.json").write_text(json.dumps(manifest, indent=2)+"\n")
    return manifest


def restore(source, output):
    manifest = json.loads((source / "backup.json").read_text())
    if manifest.get("schema_version") != 1 or not manifest.get("complete"):
        raise ValueError("Backup is incomplete")
    if "balut.db" not in manifest.get("files", {}):
        raise ValueError("Backup does not inventory its database")
    root = source.resolve()
    for name, digest in manifest["files"].items():
        if name != "balut.db" and not re.fullmatch(r"evidence/[0-9a-f]{2}/[0-9a-f]{64}\.jpg", name):
            raise ValueError("Unexpected backup file path")
        path = (source / name).resolve()
        if not path.is_relative_to(root) or not path.is_file() or sha(path) != digest:
            raise ValueError("Backup path or checksum failed")
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid backup destination path")
    check_database(source / "balut.db")
    required = evidence_files(source / "balut.db")
    if set(manifest["files"]) != {"balut.db", *required}:
        raise ValueError("Backup inventory does not match database evidence references")
    if any(manifest["files"][name] != digest for name, digest in required.items()):
        raise ValueError("Backup evidence does not match database references")
    output.mkdir(parents=True, exist_ok=False)
    for name in manifest["files"]:
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, destination)
    (output / "evidence").mkdir(exist_ok=True)
    check_database(output / "balut.db")
    return {"restored": True, "files": len(manifest["files"]), "destination": str(output.resolve())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--profile", type=Path)
    group.add_argument("--restore", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Choose a fresh output directory; existing data is never replaced")
    report = backup(args.profile, args.output) if args.profile else restore(args.restore, args.output)
    print(json.dumps({"output": str(args.output.resolve()), "result": report}, indent=2))


if __name__ == "__main__":
    main()
