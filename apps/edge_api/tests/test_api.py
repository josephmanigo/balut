import hashlib
import hmac
import json
import time
from uuid import uuid4


def with_idempotency(headers: dict[str, str], key: str) -> dict[str, str]:
    return {**headers, "Idempotency-Key": key}


def signed_device_headers(body: bytes, *, idempotency_key: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    device_id = "SIM-ESP32-S3-01"
    message = timestamp.encode() + b"." + device_id.encode() + b"." + body
    signature = hmac.new(b"test-device-secret", message, hashlib.sha256).hexdigest()
    return {
        "X-Device-Id": device_id,
        "X-Device-Timestamp": timestamp,
        "X-Device-Signature": signature,
        "Idempotency-Key": idempotency_key,
    }


def test_health_discloses_unvalidated_mode(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["hardwareConnected"] is False
    assert response.json()["trainedModelLoaded"] is False


def test_simulator_is_idempotent_and_visibly_synthetic(client, local_headers):
    headers = with_idempotency(local_headers, "same-simulation-001")
    first = client.post(
        "/api/v1/simulator/run",
        headers=headers,
        json={"scenario": "day16", "recorded_elapsed_hours": 384},
    )
    second = client.post(
        "/api/v1/simulator/run",
        headers=headers,
        json={"scenario": "day16", "recorded_elapsed_hours": 384},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["isSimulated"] is True
    assert first.json()["authority"] == "SHADOW_ONLY"
    assert first.json()["modelReleaseId"] == "SIMULATOR_NO_CNN"


def test_idempotency_key_cannot_be_reused_for_a_different_request(
    client, local_headers
):
    headers = with_idempotency(local_headers, "conflicting-simulation-001")
    first = client.post(
        "/api/v1/simulator/run",
        headers=headers,
        json={"scenario": "day16", "recorded_elapsed_hours": 384},
    )
    conflict = client.post(
        "/api/v1/simulator/run",
        headers=headers,
        json={"scenario": "reject", "recorded_elapsed_hours": 384},
    )
    assert first.status_code == 200
    assert conflict.status_code == 409


def test_low_confidence_scenario_abstains_for_the_named_reason(client, local_headers):
    response = client.post(
        "/api/v1/simulator/run",
        headers=with_idempotency(local_headers, "low-confidence-only-001"),
        json={"scenario": "low_confidence", "recorded_elapsed_hours": 384},
    )
    assert response.status_code == 200
    assert response.json()["outcome"] == "REVIEW_RECAPTURE"
    assert response.json()["flags"] == ["LOW_CONFIDENCE"]
    assert "age conflicts" not in response.json()["explanation"]


def test_physical_start_requires_local_authority_and_connected_hardware(
    client, local_headers
):
    unauthenticated = client.post(
        "/api/v1/scans",
        headers={"Idempotency-Key": "physical-start-unauth"},
        json={"device_id": "SIM-ESP32-S3-01"},
    )
    assert unauthenticated.status_code == 403

    authorized = client.post(
        "/api/v1/scans",
        headers=with_idempotency(local_headers, "physical-start-local"),
        json={"device_id": "SIM-ESP32-S3-01"},
    )
    assert authorized.status_code == 409
    assert authorized.json()["detail"]["code"] == "HARDWARE_NOT_CONNECTED"


def test_human_reviews_append_without_mutating_machine_result(client, local_headers):
    simulation = client.post(
        "/api/v1/simulator/run",
        headers=with_idempotency(local_headers, "review-target-sim"),
        json={"scenario": "low_confidence", "recorded_elapsed_hours": 384},
    ).json()
    inspection_id = simulation["inspectionId"]
    before = client.get(f"/api/v1/inspections/{inspection_id}").json()
    review_headers = with_idempotency(local_headers, "review-append-001")
    review = client.post(
        f"/api/v1/inspections/{inspection_id}/reviews",
        headers=review_headers,
        json={
            "reviewer_id": "reviewer-a",
            "disposition": "RECAPTURE_REQUIRED",
            "reason_codes": ["IMAGE_QUALITY"],
            "notes": "Synthetic review used to verify append-only persistence.",
            "blinded_to_machine_result": True,
        },
    )
    after = client.get(f"/api/v1/inspections/{inspection_id}").json()
    assert review.status_code == 200
    assert before["outcome"] == after["outcome"]
    assert before["canonicalHash"] == after["canonicalHash"]
    assert len(after["reviews"]) == 1
    assert after["reviews"][0]["blindedToMachineResult"] is True


def test_device_jpeg_is_hash_verified_and_durably_staged(client):
    import io
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "gray").save(buffer, "JPEG")
    body = buffer.getvalue()
    image_hash = hashlib.sha256(body).hexdigest()
    headers = {
        **signed_device_headers(body, idempotency_key="evidence-upload-001"),
        "Content-Type": "image/jpeg",
        "X-Image-SHA256": image_hash,
    }
    response = client.post(
        "/api/v1/device/evidence/PHYSICAL-INSPECTION-001/0",
        headers=headers,
        content=body,
    )
    assert response.status_code == 200
    assert response.json()["imageSha256"] == image_hash
    assert response.json()["byteSize"] == len(body)


def test_physical_manifest_cannot_precede_durable_evidence(client):
    payload = {
        "inspection_id": "PHYSICAL-INSPECTION-002",
        "device_id": "SIM-ESP32-S3-01",
        "batch_id": None,
        "egg_id": None,
        "recorded_elapsed_hours": 384,
        "model_release_id": "UNVALIDATED-TEST-MODEL",
        "threshold_profile_id": "test-thresholds",
        "firmware_version": "test-firmware",
        "schema_version": "1.0.0",
        "views": [{
            "view_index": 0,
            "angle_degrees": 0,
            "quality_valid": True,
            "probabilities": {
                "day_16_like": 0.9,
                "day_18_like": 0.06,
                "reject_suspect": 0.04,
            },
            "flags": [],
            "image_sha256": "a" * 64,
            "capture_ms": 100,
            "inference_ms": 400,
        }],
        "device_flags": [],
        "captured_at": "2026-08-29T00:00:00Z",
        "is_simulated": False,
        "authority": "SHADOW_ONLY",
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = {
        **signed_device_headers(body, idempotency_key="physical-manifest-002"),
        "Content-Type": "application/json",
    }
    response = client.post("/api/v1/device/inspections", headers=headers, content=body)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "EVIDENCE_NOT_DURABLE"


def test_batch_and_physical_egg_registry(client, local_headers):
    suffix = uuid4().hex[:8]
    batch_id = f"BATCH-{suffix}"
    egg_id = f"EGG-{suffix}"
    batch = client.post(
        "/api/v1/batches",
        headers=with_idempotency(local_headers, f"batch-{suffix}"),
        json={
            "batch_id": batch_id,
            "name": "Research batch",
            "incubator_entry_at": "2026-08-01T08:00:00+08:00",
            "supplier": "Documented partner",
        },
    )
    egg = client.post(
        "/api/v1/eggs",
        headers=with_idempotency(local_headers, f"egg-{suffix}"),
        json={
            "egg_id": egg_id,
            "batch_id": batch_id,
            "source_label": "UNREVIEWED",
        },
    )
    assert batch.status_code == 200
    assert egg.status_code == 200
    listed = client.get(f"/api/v1/eggs?batch_id={batch_id}").json()["items"]
    assert listed[0]["eggId"] == egg_id


def test_batch_registration_replay_is_idempotent(client, local_headers):
    suffix = uuid4().hex[:8]
    headers = with_idempotency(local_headers, f"batch-replay-{suffix}")
    payload = {
        "batch_id": f"BATCH-{suffix}",
        "name": "Replay-safe batch",
        "incubator_entry_at": "2026-08-01T08:00:00+08:00",
        "supplier": "Documented partner",
    }
    first = client.post("/api/v1/batches", headers=headers, json=payload)
    second = client.post("/api/v1/batches", headers=headers, json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


def test_audit_chain_and_outbox_are_created_atomically(client, local_headers):
    response = client.post(
        "/api/v1/simulator/run",
        headers=with_idempotency(local_headers, "audit-chain-sim-001"),
        json={"scenario": "reject", "recorded_elapsed_hours": 384},
    )
    assert response.status_code == 200
    audit = client.get("/api/v1/audit").json()["items"]
    assert audit[0]["eventType"] == "INSPECTION_RECORDED"
    assert len(audit[0]["eventHash"]) == 64
    sync = client.get("/api/v1/sync/status").json()
    assert sync["pendingEvents"] == 1
