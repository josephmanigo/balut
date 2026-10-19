from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from .domain import (
    AggregateDecision,
    BatchCreate,
    EggCreate,
    HumanReviewCreate,
    InspectionIngest,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


SCHEMA = """
CREATE TABLE IF NOT EXISTS box_workspace (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    config_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS operator_account (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    hardware_validated INTEGER NOT NULL DEFAULT 0,
    status_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS incubation_batches (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    incubator_entry_at TEXT,
    supplier TEXT,
    is_simulated INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS physical_eggs (
    id TEXT PRIMARY KEY,
    batch_id TEXT,
    source_label TEXT,
    is_simulated INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(batch_id) REFERENCES incubation_batches(id)
);

CREATE TABLE IF NOT EXISTS inspections (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    batch_id TEXT,
    egg_id TEXT,
    state TEXT NOT NULL,
    recorded_elapsed_hours REAL,
    captured_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    firmware_version TEXT NOT NULL,
    model_release_id TEXT NOT NULL,
    threshold_profile_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    authority TEXT NOT NULL,
    is_simulated INTEGER NOT NULL,
    canonical_hash TEXT NOT NULL,
    FOREIGN KEY(device_id) REFERENCES devices(id),
    FOREIGN KEY(batch_id) REFERENCES incubation_batches(id),
    FOREIGN KEY(egg_id) REFERENCES physical_eggs(id)
);

CREATE TABLE IF NOT EXISTS view_frames (
    inspection_id TEXT NOT NULL,
    view_index INTEGER NOT NULL,
    angle_degrees REAL NOT NULL,
    quality_valid INTEGER NOT NULL,
    probabilities_json TEXT NOT NULL,
    flags_json TEXT NOT NULL,
    image_sha256 TEXT,
    capture_ms INTEGER NOT NULL,
    inference_ms INTEGER NOT NULL,
    PRIMARY KEY(inspection_id, view_index),
    FOREIGN KEY(inspection_id) REFERENCES inspections(id)
);

CREATE TABLE IF NOT EXISTS staged_evidence (
    inspection_id TEXT NOT NULL,
    view_index INTEGER NOT NULL,
    device_id TEXT NOT NULL,
    image_sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    received_at TEXT NOT NULL,
    PRIMARY KEY(inspection_id, view_index)
);

CREATE TABLE IF NOT EXISTS machine_results (
    inspection_id TEXT PRIMARY KEY,
    outcome TEXT NOT NULL,
    confidence REAL NOT NULL,
    margin REAL NOT NULL,
    agreement REAL NOT NULL,
    valid_views INTEGER NOT NULL,
    expected_views INTEGER NOT NULL,
    mean_probabilities_json TEXT NOT NULL,
    flags_json TEXT NOT NULL,
    explanation TEXT NOT NULL,
    authority TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(inspection_id) REFERENCES inspections(id)
);

CREATE TABLE IF NOT EXISTS human_reviews (
    id TEXT PRIMARY KEY,
    inspection_id TEXT NOT NULL,
    reviewer_id TEXT NOT NULL,
    disposition TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    notes TEXT NOT NULL,
    blinded_to_machine_result INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(inspection_id) REFERENCES inspections(id)
);

CREATE TABLE IF NOT EXISTS audit_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    inspection_id TEXT,
    event_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    context_json TEXT NOT NULL,
    previous_hash TEXT,
    event_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_outbox (
    event_id TEXT PRIMARY KEY,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    available_at TEXT NOT NULL,
    delivered_at TEXT
);

CREATE TABLE IF NOT EXISTS idempotency_records (
    idempotency_key TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(idempotency_key, endpoint)
);

CREATE INDEX IF NOT EXISTS inspections_captured_idx ON inspections(captured_at DESC);
CREATE INDEX IF NOT EXISTS results_outcome_idx ON machine_results(outcome);
CREATE INDEX IF NOT EXISTS reviews_inspection_idx ON human_reviews(inspection_id, created_at);
CREATE INDEX IF NOT EXISTS outbox_pending_idx ON sync_outbox(delivered_at, available_at);
CREATE INDEX IF NOT EXISTS staged_evidence_hash_idx ON staged_evidence(image_sha256);

CREATE TABLE IF NOT EXISTS model_predictions (
    id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    release_id TEXT NOT NULL,
    image_sha256 TEXT NOT NULL,
    response_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    def box_config(self):
        with self.connect() as connection:
            row = connection.execute("SELECT config_json FROM box_workspace WHERE id = 1").fetchone()
        return json.loads(row[0]) if row else {}

    def save_box_config(self, value):
        with self.connect() as connection:
            connection.execute("INSERT INTO box_workspace VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET config_json = excluded.config_json", (canonical_json(value),))
            connection.commit()

    def get_operator_account(self, username=None):
        with self.connect() as connection:
            row = connection.execute("SELECT username, password_hash FROM operator_account" +
                (" WHERE username = ?" if username is not None else " ORDER BY id LIMIT 1"),
                (username,) if username is not None else ()).fetchone()
        return dict(row) if row else None

    def create_operator_account(self, username: str, password_hash: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO operator_account(username, password_hash, created_at) VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                (username, password_hash, utc_now()),
            )
            connection.execute("UPDATE model_predictions SET owner_username = (SELECT username FROM operator_account ORDER BY id LIMIT 1) WHERE owner_username IS NULL")
            connection.commit()
            return cursor.rowcount == 1

    def prediction_replay(self, actor_id, key, request_hash):
        with self.connect() as connection:
            return self._get_idempotent(connection, key, "model-prediction:" + actor_id, request_hash)

    def record_prediction(self, result, image_sha256, actor_id, key, request_hash):
        endpoint = "model-prediction:" + actor_id
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._get_idempotent(connection, key, endpoint, request_hash)
            if replay is not None:
                return replay
            now, prediction_id = utc_now(), str(uuid4())
            response = {**result, "predictionId": prediction_id, "imageSha256": image_sha256, "createdAt": now}
            payload = canonical_json(response)
            owner = connection.execute("SELECT username FROM operator_account ORDER BY username = ? DESC, id LIMIT 1", (actor_id,)).fetchone()
            connection.execute("INSERT INTO model_predictions VALUES (?, ?, ?, ?, ?, ?, ?)",
                               (prediction_id, result["modelId"], result["modelReleaseId"], image_sha256, payload, now, owner[0] if owner else actor_id))
            event_id, _ = self._append_audit(connection, inspection_id=None, event_type="SOURCE_MODEL_PREDICTION_RECORDED",
                                             actor_id=actor_id, context=response, created_at=now)
            connection.execute("INSERT INTO sync_outbox(event_id, aggregate_type, aggregate_id, payload_json, available_at) VALUES (?, ?, ?, ?, ?)",
                               (event_id, "source_model_prediction", prediction_id, payload, now))
            connection.execute("INSERT INTO idempotency_records VALUES (?, ?, ?, ?, ?)", (key, endpoint, request_hash, payload, now))
            connection.commit()
            return response

    def get_prediction(self, prediction_id, owner=None):
        with self.connect() as connection:
            row = connection.execute("SELECT response_json FROM model_predictions WHERE id = ?" +
                (" AND owner_username = ?" if owner is not None else ""),
                (prediction_id, owner) if owner is not None else (prediction_id,)).fetchone()
            return json.loads(row["response_json"]) if row else None

    def list_predictions(self, limit: int = 50, owner=None):
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT response_json FROM model_predictions" + (" WHERE owner_username = ?" if owner is not None else "") +
                " ORDER BY created_at DESC, rowid DESC LIMIT ?", (owner, limit) if owner is not None else (limit,)
            ).fetchall()
        return [json.loads(row["response_json"]) for row in rows]

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            connection.execute("BEGIN IMMEDIATE")
            account_schema = connection.execute("SELECT sql FROM sqlite_master WHERE name = 'operator_account'").fetchone()[0]
            if "CHECK (id = 1)" in account_schema:
                connection.execute("ALTER TABLE operator_account RENAME TO operator_account_single")
                connection.execute("CREATE TABLE operator_account (id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, created_at TEXT NOT NULL)")
                connection.execute("INSERT INTO operator_account SELECT * FROM operator_account_single")
                connection.execute("DROP TABLE operator_account_single")
            if "owner_username" not in {row[1] for row in connection.execute("PRAGMA table_info(model_predictions)")}:
                connection.execute("ALTER TABLE model_predictions ADD COLUMN owner_username TEXT")
            connection.execute("UPDATE model_predictions SET owner_username = (SELECT username FROM operator_account ORDER BY id LIMIT 1) WHERE owner_username IS NULL")
            connection.execute("CREATE INDEX IF NOT EXISTS predictions_owner_created ON model_predictions(owner_username, created_at DESC)")
            now = utc_now()
            connection.execute(
                """
                INSERT INTO devices(id, display_name, hardware_validated, status_json, created_at, updated_at)
                VALUES (?, ?, 0, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (
                    "SIM-ESP32-S3-01",
                    "Bench simulator",
                    canonical_json(
                        {
                            "state": "SIMULATOR_READY",
                            "lidClosed": True,
                            "eggPresent": True,
                            "emergencyStopReleased": True,
                            "lightEnabled": False,
                            "motorEnabled": False,
                            "firmwareVersion": "simulator-0.1.0",
                            "modelReleaseId": "SIMULATOR_NO_CNN",
                            "notice": "Synthetic device; no physical hardware is connected.",
                        }
                    ),
                    now,
                    now,
                ),
            )
            connection.commit()

    def ensure_simulated_context(self, batch_id: str, egg_id: str) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO incubation_batches(id, name, incubator_entry_at, supplier, is_simulated, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (
                    batch_id,
                    "Synthetic demonstration batch",
                    "2026-08-13T00:00:00Z",
                    "SIMULATED — NOT A REAL SUPPLIER",
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO physical_eggs(id, batch_id, source_label, is_simulated, created_at)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (egg_id, batch_id, "SYNTHETIC", now),
            )
            connection.commit()

    def stage_evidence(
        self,
        *,
        inspection_id: str,
        view_index: int,
        device_id: str,
        image_sha256: str,
        byte_size: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        endpoint = f"evidence-stage:{inspection_id}:{view_index}"
        request = {
            "inspectionId": inspection_id,
            "viewIndex": view_index,
            "deviceId": device_id,
            "imageSha256": image_sha256,
            "byteSize": byte_size,
        }
        request_hash = canonical_sha256(request)
        received_at = utc_now()
        response = {**request, "receivedAt": received_at}
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._get_idempotent(
                connection, idempotency_key, endpoint, request_hash
            )
            if existing is not None:
                connection.rollback()
                return existing
            staged = connection.execute(
                """
                SELECT device_id, image_sha256, byte_size
                FROM staged_evidence
                WHERE inspection_id = ? AND view_index = ?
                """,
                (inspection_id, view_index),
            ).fetchone()
            if staged is not None:
                if (
                    staged["device_id"] != device_id
                    or staged["image_sha256"] != image_sha256
                    or staged["byte_size"] != byte_size
                ):
                    connection.rollback()
                    raise ValueError("view position already contains different staged evidence")
            else:
                connection.execute(
                    """
                    INSERT INTO staged_evidence(
                        inspection_id, view_index, device_id, image_sha256,
                        byte_size, received_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        inspection_id,
                        view_index,
                        device_id,
                        image_sha256,
                        byte_size,
                        received_at,
                    ),
                )
            self._append_audit(
                connection,
                inspection_id=inspection_id,
                event_type="EVIDENCE_FRAME_STAGED",
                actor_id=f"device:{device_id}",
                context=request,
                created_at=received_at,
            )
            connection.execute(
                """
                INSERT INTO idempotency_records(
                    idempotency_key, endpoint, request_hash, response_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    idempotency_key,
                    endpoint,
                    request_hash,
                    canonical_json(response),
                    received_at,
                ),
            )
            connection.commit()
        return response

    def create_batch(
        self,
        batch: BatchCreate,
        *,
        idempotency_key: str,
        actor_id: str,
    ) -> dict[str, Any]:
        created_at = utc_now()
        endpoint = "batch-create"
        request_hash = canonical_sha256(batch.model_dump(mode="json"))
        response = {
            "batchId": batch.batch_id,
            "name": batch.name,
            "incubatorEntryAt": batch.incubator_entry_at.isoformat().replace("+00:00", "Z"),
            "supplier": batch.supplier,
            "isSimulated": False,
            "createdAt": created_at,
        }
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._get_idempotent(
                connection, idempotency_key, endpoint, request_hash
            )
            if existing is not None:
                connection.rollback()
                return existing

            connection.execute(
                """
                INSERT INTO incubation_batches(
                    id, name, incubator_entry_at, supplier, is_simulated, created_at
                ) VALUES (?, ?, ?, ?, 0, ?)
                """,
                (
                    batch.batch_id,
                    batch.name,
                    response["incubatorEntryAt"],
                    batch.supplier,
                    created_at,
                ),
            )
            event_id, _ = self._append_audit(
                connection,
                inspection_id=None,
                event_type="INCUBATION_BATCH_REGISTERED",
                actor_id=actor_id,
                context=response,
                created_at=created_at,
            )
            connection.execute(
                """
                INSERT INTO sync_outbox(
                    event_id, aggregate_type, aggregate_id, payload_json, available_at
                ) VALUES (?, 'incubation_batch', ?, ?, ?)
                """,
                (event_id, batch.batch_id, canonical_json(response), created_at),
            )
            connection.execute(
                """
                INSERT INTO idempotency_records(
                    idempotency_key, endpoint, request_hash, response_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    idempotency_key,
                    endpoint,
                    request_hash,
                    canonical_json(response),
                    created_at,
                ),
            )
            connection.commit()
        return response

    def list_batches(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM incubation_batches ORDER BY created_at DESC"
            ).fetchall()
        return [
            {
                "batchId": row["id"],
                "name": row["name"],
                "incubatorEntryAt": row["incubator_entry_at"],
                "supplier": row["supplier"],
                "isSimulated": bool(row["is_simulated"]),
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    def create_egg(
        self,
        egg: EggCreate,
        *,
        idempotency_key: str,
        actor_id: str,
    ) -> dict[str, Any]:
        created_at = utc_now()
        endpoint = "egg-create"
        request_hash = canonical_sha256(egg.model_dump(mode="json"))
        response = {
            "eggId": egg.egg_id,
            "batchId": egg.batch_id,
            "sourceLabel": egg.source_label,
            "isSimulated": False,
            "createdAt": created_at,
        }
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._get_idempotent(
                connection, idempotency_key, endpoint, request_hash
            )
            if existing is not None:
                connection.rollback()
                return existing
            connection.execute(
                """
                INSERT INTO physical_eggs(
                    id, batch_id, source_label, is_simulated, created_at
                ) VALUES (?, ?, ?, 0, ?)
                """,
                (egg.egg_id, egg.batch_id, egg.source_label, created_at),
            )
            event_id, _ = self._append_audit(
                connection,
                inspection_id=None,
                event_type="PHYSICAL_EGG_REGISTERED",
                actor_id=actor_id,
                context=response,
                created_at=created_at,
            )
            connection.execute(
                """
                INSERT INTO sync_outbox(
                    event_id, aggregate_type, aggregate_id, payload_json, available_at
                ) VALUES (?, 'physical_egg', ?, ?, ?)
                """,
                (event_id, egg.egg_id, canonical_json(response), created_at),
            )
            connection.execute(
                """
                INSERT INTO idempotency_records(
                    idempotency_key, endpoint, request_hash, response_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    idempotency_key,
                    endpoint,
                    request_hash,
                    canonical_json(response),
                    created_at,
                ),
            )
            connection.commit()
        return response

    def list_eggs(self, batch_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM physical_eggs"
        params: tuple[Any, ...] = ()
        if batch_id:
            query += " WHERE batch_id = ?"
            params = (batch_id,)
        query += " ORDER BY created_at DESC"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            {
                "eggId": row["id"],
                "batchId": row["batch_id"],
                "sourceLabel": row["source_label"],
                "isSimulated": bool(row["is_simulated"]),
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    @staticmethod
    def _get_idempotent(
        connection: sqlite3.Connection,
        key: str,
        endpoint: str,
        request_hash: str,
    ) -> dict[str, Any] | None:
        row = connection.execute(
            """
            SELECT request_hash, response_json
            FROM idempotency_records
            WHERE idempotency_key = ? AND endpoint = ?
            """,
            (key, endpoint),
        ).fetchone()
        if row is None:
            return None
        if row["request_hash"] != request_hash:
            raise ValueError("idempotency key was reused with a different request")
        return json.loads(row["response_json"])

    @staticmethod
    def _append_audit(
        connection: sqlite3.Connection,
        *,
        inspection_id: str | None,
        event_type: str,
        actor_id: str,
        context: dict[str, Any],
        created_at: str,
    ) -> tuple[str, str]:
        previous = connection.execute(
            "SELECT event_hash FROM audit_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        previous_hash = previous["event_hash"] if previous else None
        event_id = str(uuid4())
        event_hash = canonical_sha256(
            {
                "eventId": event_id,
                "inspectionId": inspection_id,
                "eventType": event_type,
                "actorId": actor_id,
                "context": context,
                "previousHash": previous_hash,
                "createdAt": created_at,
            }
        )
        connection.execute(
            """
            INSERT INTO audit_events(
                event_id, inspection_id, event_type, actor_id, context_json,
                previous_hash, event_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                inspection_id,
                event_type,
                actor_id,
                canonical_json(context),
                previous_hash,
                event_hash,
                created_at,
            ),
        )
        return event_id, event_hash

    def create_inspection(
        self,
        ingest: InspectionIngest,
        decision: AggregateDecision,
        *,
        idempotency_key: str,
        endpoint: str,
        actor_id: str,
        idempotency_payload: Any | None = None,
    ) -> dict[str, Any]:
        request_payload = (
            idempotency_payload
            if idempotency_payload is not None
            else ingest.model_dump(mode="json")
        )
        request_hash = canonical_sha256(request_payload)
        received_at = utc_now()
        inspection_hash = canonical_sha256(
            {
                "schemaVersion": ingest.schema_version,
                "firmwareVersion": ingest.firmware_version,
                "modelReleaseId": ingest.model_release_id,
                "thresholdProfileId": ingest.threshold_profile_id,
                "deviceId": ingest.device_id,
                "inspectionId": ingest.inspection_id,
                "batchId": ingest.batch_id,
                "eggId": ingest.egg_id,
                "capturedAt": ingest.captured_at.isoformat(),
                "views": [view.model_dump(mode="json") for view in ingest.views],
                "decision": decision.model_dump(mode="json"),
            }
        )
        response = {
            "inspectionId": ingest.inspection_id,
            "state": decision.state.value,
            "outcome": decision.outcome.value,
            "confidence": round(decision.confidence, 4),
            "margin": round(decision.margin, 4),
            "agreement": round(decision.agreement, 4),
            "validViews": decision.valid_views,
            "expectedViews": decision.expected_views,
            "flags": [flag.value for flag in decision.flags],
            "explanation": decision.explanation,
            "authority": decision.authority.value,
            "isSimulated": ingest.is_simulated,
            "canonicalHash": inspection_hash,
            "modelReleaseId": ingest.model_release_id,
            "thresholdProfileId": ingest.threshold_profile_id,
            "capturedAt": ingest.captured_at.isoformat().replace("+00:00", "Z"),
        }

        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._get_idempotent(
                connection, idempotency_key, endpoint, request_hash
            )
            if existing is not None:
                connection.rollback()
                return existing

            if not ingest.is_simulated:
                staged_rows = connection.execute(
                    """
                    SELECT view_index, device_id, image_sha256
                    FROM staged_evidence WHERE inspection_id = ?
                    """,
                    (ingest.inspection_id,),
                ).fetchall()
                staged = {
                    row["view_index"]: (row["device_id"], row["image_sha256"])
                    for row in staged_rows
                }
                missing = [
                    view.view_index
                    for view in ingest.views
                    if view.quality_valid
                    and (
                        view.image_sha256 is None
                        or staged.get(view.view_index)
                        != (ingest.device_id, view.image_sha256)
                    )
                ]
                if missing:
                    connection.rollback()
                    raise ValueError(
                        f"valid physical views lack matching durable evidence: {missing}"
                    )

            connection.execute(
                """
                INSERT INTO inspections(
                    id, device_id, batch_id, egg_id, state, recorded_elapsed_hours,
                    captured_at, received_at, firmware_version, model_release_id,
                    threshold_profile_id, schema_version, authority, is_simulated,
                    canonical_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ingest.inspection_id,
                    ingest.device_id,
                    ingest.batch_id,
                    ingest.egg_id,
                    decision.state.value,
                    ingest.recorded_elapsed_hours,
                    ingest.captured_at.isoformat().replace("+00:00", "Z"),
                    received_at,
                    ingest.firmware_version,
                    ingest.model_release_id,
                    ingest.threshold_profile_id,
                    ingest.schema_version,
                    ingest.authority.value,
                    int(ingest.is_simulated),
                    inspection_hash,
                ),
            )
            for view in ingest.views:
                connection.execute(
                    """
                    INSERT INTO view_frames(
                        inspection_id, view_index, angle_degrees, quality_valid,
                        probabilities_json, flags_json, image_sha256, capture_ms,
                        inference_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ingest.inspection_id,
                        view.view_index,
                        view.angle_degrees,
                        int(view.quality_valid),
                        canonical_json(view.probabilities.model_dump(mode="json")),
                        canonical_json([flag.value for flag in view.flags]),
                        view.image_sha256,
                        view.capture_ms,
                        view.inference_ms,
                    ),
                )
            connection.execute(
                """
                INSERT INTO machine_results(
                    inspection_id, outcome, confidence, margin, agreement,
                    valid_views, expected_views, mean_probabilities_json,
                    flags_json, explanation, authority, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ingest.inspection_id,
                    decision.outcome.value,
                    decision.confidence,
                    decision.margin,
                    decision.agreement,
                    decision.valid_views,
                    decision.expected_views,
                    canonical_json(decision.mean_probabilities.model_dump(mode="json")),
                    canonical_json([flag.value for flag in decision.flags]),
                    decision.explanation,
                    decision.authority.value,
                    received_at,
                ),
            )
            event_id, _ = self._append_audit(
                connection,
                inspection_id=ingest.inspection_id,
                event_type="INSPECTION_RECORDED",
                actor_id=actor_id,
                context={
                    "schemaVersion": ingest.schema_version,
                    "deviceId": ingest.device_id,
                    "firmwareVersion": ingest.firmware_version,
                    "modelReleaseId": ingest.model_release_id,
                    "thresholdProfileId": ingest.threshold_profile_id,
                    "canonicalHash": inspection_hash,
                    "outcome": decision.outcome.value,
                    "authority": ingest.authority.value,
                    "isSimulated": ingest.is_simulated,
                },
                created_at=received_at,
            )
            connection.execute(
                """
                INSERT INTO sync_outbox(
                    event_id, aggregate_type, aggregate_id, payload_json, available_at
                ) VALUES (?, 'inspection', ?, ?, ?)
                """,
                (event_id, ingest.inspection_id, canonical_json(response), received_at),
            )
            connection.execute(
                """
                INSERT INTO idempotency_records(
                    idempotency_key, endpoint, request_hash, response_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    idempotency_key,
                    endpoint,
                    request_hash,
                    canonical_json(response),
                    received_at,
                ),
            )
            connection.commit()
        return response

    def append_review(
        self,
        inspection_id: str,
        review: HumanReviewCreate,
        *,
        idempotency_key: str,
        actor_id: str,
    ) -> dict[str, Any]:
        endpoint = f"reviews:{inspection_id}"
        request_hash = canonical_sha256(review.model_dump(mode="json"))
        created_at = utc_now()
        review_id = str(uuid4())
        response = {
            "reviewId": review_id,
            "inspectionId": inspection_id,
            "reviewerId": review.reviewer_id,
            "disposition": review.disposition.value,
            "reasonCodes": review.reason_codes,
            "notes": review.notes,
            "blindedToMachineResult": review.blinded_to_machine_result,
            "createdAt": created_at,
        }
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._get_idempotent(
                connection, idempotency_key, endpoint, request_hash
            )
            if existing is not None:
                connection.rollback()
                return existing
            exists = connection.execute(
                "SELECT 1 FROM inspections WHERE id = ?", (inspection_id,)
            ).fetchone()
            if not exists:
                connection.rollback()
                raise KeyError(inspection_id)
            connection.execute(
                """
                INSERT INTO human_reviews(
                    id, inspection_id, reviewer_id, disposition, reason_codes_json,
                    notes, blinded_to_machine_result, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    inspection_id,
                    review.reviewer_id,
                    review.disposition.value,
                    canonical_json(review.reason_codes),
                    review.notes,
                    int(review.blinded_to_machine_result),
                    created_at,
                ),
            )
            event_id, _ = self._append_audit(
                connection,
                inspection_id=inspection_id,
                event_type="HUMAN_DISPOSITION_APPENDED",
                actor_id=actor_id,
                context=response,
                created_at=created_at,
            )
            connection.execute(
                """
                INSERT INTO sync_outbox(
                    event_id, aggregate_type, aggregate_id, payload_json, available_at
                ) VALUES (?, 'human_review', ?, ?, ?)
                """,
                (event_id, review_id, canonical_json(response), created_at),
            )
            connection.execute(
                """
                INSERT INTO idempotency_records(
                    idempotency_key, endpoint, request_hash, response_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    idempotency_key,
                    endpoint,
                    request_hash,
                    canonical_json(response),
                    created_at,
                ),
            )
            connection.commit()
        return response

    def list_inspections(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT i.id, i.device_id, i.batch_id, i.egg_id, i.state,
                       i.recorded_elapsed_hours, i.captured_at, i.model_release_id,
                       i.authority, i.is_simulated, i.canonical_hash,
                       r.outcome, r.confidence, r.valid_views, r.expected_views,
                       r.flags_json,
                       (SELECT COUNT(*) FROM human_reviews h WHERE h.inspection_id = i.id) AS review_count
                FROM inspections i
                JOIN machine_results r ON r.inspection_id = i.id
                ORDER BY i.captured_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "inspectionId": row["id"],
                "deviceId": row["device_id"],
                "batchId": row["batch_id"],
                "eggId": row["egg_id"],
                "state": row["state"],
                "recordedElapsedHours": row["recorded_elapsed_hours"],
                "capturedAt": row["captured_at"],
                "modelReleaseId": row["model_release_id"],
                "authority": row["authority"],
                "isSimulated": bool(row["is_simulated"]),
                "canonicalHash": row["canonical_hash"],
                "outcome": row["outcome"],
                "confidence": row["confidence"],
                "validViews": row["valid_views"],
                "expectedViews": row["expected_views"],
                "flags": json.loads(row["flags_json"]),
                "reviewCount": row["review_count"],
            }
            for row in rows
        ]

    def get_inspection(self, inspection_id: str) -> dict[str, Any] | None:
        summaries = [
            item
            for item in self.list_inspections(limit=500)
            if item["inspectionId"] == inspection_id
        ]
        if not summaries:
            return None
        with self.connect() as connection:
            view_rows = connection.execute(
                """
                SELECT * FROM view_frames
                WHERE inspection_id = ? ORDER BY view_index
                """,
                (inspection_id,),
            ).fetchall()
            result = connection.execute(
                "SELECT * FROM machine_results WHERE inspection_id = ?",
                (inspection_id,),
            ).fetchone()
            review_rows = connection.execute(
                """
                SELECT * FROM human_reviews
                WHERE inspection_id = ? ORDER BY created_at
                """,
                (inspection_id,),
            ).fetchall()
            audit_rows = connection.execute(
                """
                SELECT sequence, event_id, event_type, actor_id, context_json,
                       previous_hash, event_hash, created_at
                FROM audit_events
                WHERE inspection_id = ? ORDER BY sequence
                """,
                (inspection_id,),
            ).fetchall()
        detail = summaries[0]
        detail["meanProbabilities"] = json.loads(result["mean_probabilities_json"])
        detail["margin"] = result["margin"]
        detail["agreement"] = result["agreement"]
        detail["explanation"] = result["explanation"]
        detail["views"] = [
            {
                "viewIndex": row["view_index"],
                "angleDegrees": row["angle_degrees"],
                "qualityValid": bool(row["quality_valid"]),
                "probabilities": json.loads(row["probabilities_json"]),
                "flags": json.loads(row["flags_json"]),
                "imageSha256": row["image_sha256"],
                "captureMs": row["capture_ms"],
                "inferenceMs": row["inference_ms"],
            }
            for row in view_rows
        ]
        detail["reviews"] = [
            {
                "reviewId": row["id"],
                "reviewerId": row["reviewer_id"],
                "disposition": row["disposition"],
                "reasonCodes": json.loads(row["reason_codes_json"]),
                "notes": row["notes"],
                "blindedToMachineResult": bool(row["blinded_to_machine_result"]),
                "createdAt": row["created_at"],
            }
            for row in review_rows
        ]
        detail["auditEvents"] = [
            {
                "sequence": row["sequence"],
                "eventId": row["event_id"],
                "eventType": row["event_type"],
                "actorId": row["actor_id"],
                "context": json.loads(row["context_json"]),
                "previousHash": row["previous_hash"],
                "eventHash": row["event_hash"],
                "createdAt": row["created_at"],
            }
            for row in audit_rows
        ]
        return detail

    def dashboard(self) -> dict[str, Any]:
        with self.connect() as connection:
            outcome_rows = connection.execute(
                """
                SELECT outcome, COUNT(*) AS count
                FROM machine_results GROUP BY outcome
                """
            ).fetchall()
            pending_review = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM machine_results r
                WHERE r.outcome = 'REVIEW_RECAPTURE'
                  AND NOT EXISTS (
                    SELECT 1 FROM human_reviews h WHERE h.inspection_id = r.inspection_id
                  )
                """
            ).fetchone()["count"]
            pending_sync = connection.execute(
                "SELECT COUNT(*) AS count FROM sync_outbox WHERE delivered_at IS NULL"
            ).fetchone()["count"]
            device_rows = connection.execute(
                "SELECT * FROM devices ORDER BY display_name"
            ).fetchall()
        counts = {row["outcome"]: row["count"] for row in outcome_rows}
        total = sum(counts.values())
        return {
            "prototypeStatus": "SIMULATOR / SHADOW ONLY",
            "isSimulated": True,
            "totalInspections": total,
            "outcomeCounts": counts,
            "pendingReview": pending_review,
            "pendingSync": pending_sync,
            "devices": [
                {
                    "deviceId": row["id"],
                    "displayName": row["display_name"],
                    "hardwareValidated": bool(row["hardware_validated"]),
                    **json.loads(row["status_json"]),
                    "updatedAt": row["updated_at"],
                }
                for row in device_rows
            ],
            "recentInspections": self.list_inspections(limit=8),
            "gates": [
                {"name": "Software vertical slice", "state": "LOCAL TEST REQUIRED"},
                {"name": "Physical safety", "state": "BLOCKED — NO HARDWARE"},
                {"name": "CNN validation", "state": "BLOCKED — NO TRAINED MODEL"},
                {"name": "300-egg study", "state": "BLOCKED — NO DATASET"},
                {"name": "Production authority", "state": "BLOCKED"},
            ],
        }

    def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT sequence, event_id, inspection_id, event_type, actor_id,
                       context_json, previous_hash, event_hash, created_at
                FROM audit_events ORDER BY sequence DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "sequence": row["sequence"],
                "eventId": row["event_id"],
                "inspectionId": row["inspection_id"],
                "eventType": row["event_type"],
                "actorId": row["actor_id"],
                "context": json.loads(row["context_json"]),
                "previousHash": row["previous_hash"],
                "eventHash": row["event_hash"],
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    def sync_status(self) -> dict[str, Any]:
        with self.connect() as connection:
            pending = connection.execute(
                "SELECT COUNT(*) AS count FROM sync_outbox WHERE delivered_at IS NULL"
            ).fetchone()["count"]
            delivered = connection.execute(
                "SELECT COUNT(*) AS count FROM sync_outbox WHERE delivered_at IS NOT NULL"
            ).fetchone()["count"]
        return {
            "mode": "STORE_AND_FORWARD",
            "cloudConfigured": False,
            "pendingEvents": pending,
            "deliveredEvents": delivered,
            "notice": "Supabase synchronization is schema-complete but not provisioned in this workspace.",
        }

    def manifest_export(self) -> dict[str, Any]:
        inspections = self.list_inspections(limit=10000)
        return {
            "schemaVersion": "1.0.0",
            "generatedAt": utc_now(),
            "physicalEggCount": len(
                {row["eggId"] for row in inspections if row["eggId"]}
            ),
            "sessionCount": len(inspections),
            "containsSimulatedRecords": any(row["isSimulated"] for row in inspections),
            "records": inspections,
        }
