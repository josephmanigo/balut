from __future__ import annotations

import sqlite3
import hashlib
import shutil
import logging
import os
import re
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.staticfiles import StaticFiles

from .aggregation import aggregate_inspection
from .config import Settings
from .database import Database, canonical_sha256
from .domain import (
    BatchCreate,
    EggCreate,
    HumanReviewCreate,
    InspectionIngest,
    SimulatorRunRequest,
    StartScanRequest,
)
from .security import (
    require_idempotency_key,
    require_local_operator,
    verify_device_signature,
)
from .simulator import build_simulated_ingest
from .evidence import EvidenceStore
from .http_guard import HttpGuard
from .browser_auth import BrowserSessions, browser_auth_router
from .model_service import ModelService, ModelBusyError, MULTIVIEW_POLICY
from .automatic_box import AutomaticBox, box_router
from .supabase_store import CloudStorageError, Supabase, SupabaseDatabase, SupabaseEvidence


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_env()
    resolved_settings.validate()
    database = Database(resolved_settings.database_path)
    evidence_store = EvidenceStore(resolved_settings.evidence_path)
    cloud = None
    if resolved_settings.supabase_url:
        cloud = Supabase(resolved_settings.supabase_url, resolved_settings.supabase_secret_key)
        database = SupabaseDatabase(resolved_settings.database_path, cloud)
        evidence_store = SupabaseEvidence(resolved_settings.evidence_path, cloud)
    models = ModelService()

    def persist_prediction(model_id, body, actor, key, source=None):
        multiview = isinstance(body, list)
        bodies = body if multiview else [body]
        hashes = [hashlib.sha256(view).hexdigest() for view in bodies]
        image_hash = hashes[0]
        identity = {"modelId": model_id, "registrySha256": models.registry_sha256, "imageSha256": image_hash}
        if multiview:
            identity.update(imageHashes=hashes, multiViewPolicy=MULTIVIEW_POLICY)
        request_hash = canonical_sha256(identity)
        replay = database.prediction_replay(actor, key, request_hash)
        if replay is not None:
            if not all(evidence_store.contains(digest) for digest in hashes):
                raise OSError("Evidence for the earlier result is unavailable")
            return replay
        if shutil.disk_usage(resolved_settings.evidence_path).free < 100 * 1024 * 1024:
            raise OSError("Insufficient evidence storage")
        result = models.predict_views(model_id, bodies) if multiview else models.predict(model_id, body)
        if source:
            result = {**result, "captureSource": source}
        if source == "iot_box" and key.startswith("box-still-"):
            result["captureProtocol"] = "local-motor-hold-v1"
        if source == "iot_box" and key.startswith("box-views-"):
            result["captureProtocol"] = "local-motor-three-views-v1"
            result["multiView"] = {**result["multiView"], "capture": "paused_motor_step_spacing", "anglesVerified": False}
        for view, digest in zip(bodies, hashes, strict=True):
            evidence_store.store_jpeg(view, digest)
        return database.record_prediction(result, image_hash, actor, key, request_hash)

    def predict_box(body, key):
        if models.analysis_model_id is None:
            raise ValueError("Egg analysis model is unavailable")
        return persist_prediction(models.analysis_model_id, body, "automatic-box", key, "iot_box")

    box = AutomaticBox(database, evidence_store, predict_box)
    if resolved_settings.serverless:
        from .serverless_box import ServerlessBox, serverless_box_router
        from .remote_camera import remote_camera_router
        box = ServerlessBox(database, evidence_store, predict_box, cloud)
        remote_camera = box
    elif resolved_settings.cloud_origin:
        from .remote_camera import RemoteCamera, USB_ORIGIN, remote_camera_router
        remote_camera = RemoteCamera(box)
        box.fetch = remote_camera.fetch

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.initialize()
        if resolved_settings.serverless and database.get_operator_account() is None:
            raise RuntimeError("Migrate the existing account to Supabase before deployment")
        if resolved_settings.cloud_origin and not resolved_settings.serverless and database.get_operator_account() is None:
            username = os.getenv("BALUT_OPERATOR_USERNAME", "")
            password_hash = os.getenv("BALUT_OPERATOR_PASSWORD_HASH", "")
            if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,31}", username) or not re.fullmatch(r"scrypt\$131072\$8\$1\$[0-9a-f]{32}\$[0-9a-f]{64}", password_hash):
                raise RuntimeError("Prepare the protected Render account settings before deployment")
            database.create_operator_account(username, password_hash)
        if resolved_settings.model_registry_path:
            models.load(resolved_settings.model_registry_path, resolved_settings.model_registry_sha256)
        if resolved_settings.cloud_origin and not resolved_settings.serverless:
            config = database.box_config()
            config.update(cameraUrl=USB_ORIGIN, enabled=False)
            config.pop("reference", None)
            database.save_box_config(config)
        if not resolved_settings.serverless:
            await box.start()
        if resolved_settings.cloud_origin and not resolved_settings.serverless and box.config.get("pending"):
            # Recover durable evidence once before requiring a fresh empty view.
            async with box.lock:
                await box.finish_pending()
        try:
            yield
        finally:
            if not resolved_settings.serverless:
                await box.close()
            models.close()

    application = FastAPI(
        title="EggGrade IoT local edge API",
        version="0.1.0",
        description=(
            "Fail-closed research prototype API. Simulator data is synthetic and "
            "does not represent a trained CNN or physical device."
        ),
        lifespan=lifespan,
        docs_url=None if resolved_settings.environment == "production" else "/docs",
        redoc_url=None if resolved_settings.environment == "production" else "/redoc",
        openapi_url=None if resolved_settings.environment == "production" else "/openapi.json",
    )
    application.state.settings = resolved_settings
    application.state.database = database
    application.state.model_service = models
    application.state.box = box
    application.state.browser_sessions = BrowserSessions()
    if resolved_settings.serverless:
        from .cloud_sessions import CloudSessions
        application.state.browser_sessions = CloudSessions(cloud)
    application.include_router(browser_auth_router(database, application.state.browser_sessions))
    application.include_router((serverless_box_router if resolved_settings.serverless else box_router)(box, resolved_settings))
    if resolved_settings.cloud_origin:
        application.state.remote_camera = remote_camera
        application.include_router(remote_camera_router(remote_camera, resolved_settings))
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-Actor-Id",
            "X-Balut-Origin",
            "X-Device-Id",
            "X-Device-Signature",
            "X-Device-Timestamp",
            "X-Device-Signature-Version",
            "X-Image-SHA256",
        ],
    )
    application.add_middleware(HttpGuard, settings=resolved_settings)

    @application.exception_handler(sqlite3.OperationalError)
    @application.exception_handler(CloudStorageError)
    async def storage_unavailable(request: Request, exc: sqlite3.OperationalError):
        logging.getLogger("balut.storage").error("Database unavailable: %s", type(exc).__name__)
        return JSONResponse({"detail": "Storage unavailable; no result accepted"}, status_code=503)

    @application.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "mode": "SOURCE_LABEL_SHADOW_ONLY" if resolved_settings.environment == "production" else "SIMULATOR / SHADOW ONLY",
            "hardwareConnected": False,
            "trainedModelLoaded": bool(models.models),
            "operationalModelValidated": False,
            "modelScope": "SOURCE_LABEL_SHADOW_ONLY" if models.models else None,
        }

    @application.get("/ready")
    def readiness():
        try:
            with database.connect() as connection:
                connection.execute("SELECT count(*) FROM model_predictions").fetchone()
            if cloud:
                cloud.check()
            storage_ready = shutil.disk_usage(resolved_settings.evidence_path).free >= 100 * 1024 * 1024
            model_ready = not resolved_settings.model_registry_path or bool(models.models)
            ready = storage_ready and model_ready
        except (sqlite3.Error, OSError, CloudStorageError):
            ready = False
        return JSONResponse({"serviceReady": ready, "automaticGradingReady": False,
                             "mode": "SOURCE_LABEL_SHADOW_ONLY", "loadedModels": len(models.models)}, status_code=200 if ready else 503)

    @application.get("/api/v1/models")
    def model_catalog():
        return models.describe()

    @application.get("/api/v1/model-predictions/records/{prediction_id}")
    def prediction_record(prediction_id: str):
        result = database.get_prediction(prediction_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Prediction not found")
        return result

    @application.get("/api/v1/model-predictions")
    def prediction_history(limit: Annotated[int, Query(ge=1, le=100)] = 50):
        return {"items": database.list_predictions(limit)}

    @application.post("/api/v1/model-predictions/{model_id}")
    async def predict_source_image(model_id: str, request: Request):
        actor = require_local_operator(request, resolved_settings)
        key = require_idempotency_key(request)
        if model_id not in models.models:
            raise HTTPException(status_code=404, detail="Model is not loaded")
        if request.headers.get("Content-Type", "").split(";", 1)[0] != "image/jpeg":
            raise HTTPException(status_code=415, detail="Submit a single-egg JPEG as the request body")
        body = await request.body()
        try:
            return await run_in_threadpool(persist_prediction, model_id, body, actor, key)
        except ModelBusyError as exc:
            raise HTTPException(status_code=429, detail="Inference busy; retry with the same key", headers={"Retry-After": "1"}) from exc
        except ValueError as exc:
            code = 409 if "idempotency" in str(exc) else 422
            raise HTTPException(status_code=code, detail=str(exc)) from exc
        except (OSError, RuntimeError) as exc:
            logging.getLogger("balut.prediction").error("Prediction rejected: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail="Prediction or evidence unavailable; no result accepted") from exc

    @application.post("/api/v1/egg-analysis")
    async def analyze_egg(request: Request):
        # The pinned release selects the one three-class model, not the operator.
        require_local_operator(request, resolved_settings)
        if models.analysis_model_id is None:
            raise HTTPException(status_code=503, detail="The three-class egg analysis model is unavailable")
        return await predict_source_image(models.analysis_model_id, request)

    @application.get("/api/v1/dashboard")
    def dashboard() -> dict:
        return database.dashboard()

    @application.get("/api/v1/inspections")
    def list_inspections(
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
    ) -> dict:
        return {"items": database.list_inspections(limit=limit)}

    @application.get("/api/v1/inspections/{inspection_id}")
    def get_inspection(inspection_id: str) -> dict:
        detail = database.get_inspection(inspection_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Inspection not found")
        return detail

    @application.post("/api/v1/inspections/{inspection_id}/reviews")
    def append_review(
        inspection_id: str,
        review: HumanReviewCreate,
        request: Request,
    ) -> dict:
        actor_id = require_local_operator(request, resolved_settings)
        idempotency_key = require_idempotency_key(request)
        try:
            return database.append_review(
                inspection_id,
                review,
                idempotency_key=idempotency_key,
                actor_id=actor_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Inspection not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @application.post("/api/v1/device/inspections")
    async def ingest_device_inspection(
        ingest: InspectionIngest,
        request: Request,
    ) -> dict:
        authenticated_device = await verify_device_signature(request, resolved_settings)
        if authenticated_device != ingest.device_id:
            raise HTTPException(status_code=401, detail="Device identity mismatch")
        if ingest.authority != "SHADOW_ONLY":
            raise HTTPException(status_code=403, detail="No validated operational model release is installed")
        if ingest.is_simulated and not resolved_settings.allow_simulator:
            raise HTTPException(status_code=403, detail="Simulated device submissions are disabled")
        idempotency_key = require_idempotency_key(request)
        if not ingest.is_simulated:
            missing_files = [
                view.view_index
                for view in ingest.views
                if view.quality_valid
                and (
                    view.image_sha256 is None
                    or not evidence_store.contains(view.image_sha256)
                )
            ]
            if missing_files:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "EVIDENCE_NOT_DURABLE",
                        "missingViewIndexes": missing_files,
                    },
                )
        decision = aggregate_inspection(ingest)
        try:
            return database.create_inspection(
                ingest,
                decision,
                idempotency_key=idempotency_key,
                endpoint="device-inspection-ingest",
                actor_id=f"device:{authenticated_device}",
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Inspection identity conflict") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @application.post("/api/v1/device/evidence/{inspection_id}/{view_index}")
    async def stage_device_evidence(
        inspection_id: str,
        view_index: int,
        request: Request,
    ) -> dict:
        if view_index < 0 or view_index > 7:
            raise HTTPException(status_code=422, detail="view_index must be between 0 and 7")
        authenticated_device = await verify_device_signature(request, resolved_settings)
        idempotency_key = require_idempotency_key(request)
        if request.headers.get("Content-Type", "").split(";", 1)[0] != "image/jpeg":
            raise HTTPException(status_code=415, detail="Only image/jpeg evidence is accepted")
        declared_sha256 = request.headers.get("X-Image-SHA256", "")
        if len(declared_sha256) != 64:
            raise HTTPException(status_code=400, detail="X-Image-SHA256 is required")
        try:
            stored = evidence_store.store_jpeg(await request.body(), declared_sha256)
            response = database.stage_evidence(
                inspection_id=inspection_id,
                view_index=view_index,
                device_id=authenticated_device,
                image_sha256=stored.sha256,
                byte_size=stored.byte_size,
                idempotency_key=idempotency_key,
            )
            return {**response, "contentRepeated": stored.repeated}
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @application.post("/api/v1/scans")
    def start_physical_scan(scan: StartScanRequest, request: Request) -> dict:
        actor_id = require_local_operator(request, resolved_settings)
        require_idempotency_key(request)
        raise HTTPException(
            status_code=409,
            detail={
                "code": "HARDWARE_NOT_CONNECTED",
                "message": (
                    "No physical ESP32-S3 transport is connected. Use the explicitly "
                    "labeled simulator endpoint or connect validated hardware."
                ),
                "actorId": actor_id,
                "deviceId": scan.device_id,
            },
        )

    @application.post("/api/v1/simulator/run")
    def run_simulator(payload: SimulatorRunRequest, request: Request) -> dict:
        if not resolved_settings.allow_simulator:
            raise HTTPException(status_code=404, detail="Simulator disabled")
        actor_id = require_local_operator(request, resolved_settings)
        idempotency_key = require_idempotency_key(request)
        ingest = build_simulated_ingest(payload)
        database.ensure_simulated_context(ingest.batch_id or "SIM-BATCH-001", ingest.egg_id or "SIM-EGG")
        decision = aggregate_inspection(ingest)
        try:
            return database.create_inspection(
                ingest,
                decision,
                idempotency_key=idempotency_key,
                endpoint="simulator-run",
                actor_id=f"{actor_id}:simulator",
                idempotency_payload=payload.model_dump(mode="json"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @application.get("/api/v1/batches")
    def list_batches() -> dict:
        return {"items": database.list_batches()}

    @application.post("/api/v1/batches")
    def create_batch(batch: BatchCreate, request: Request) -> dict:
        actor_id = require_local_operator(request, resolved_settings)
        idempotency_key = require_idempotency_key(request)
        try:
            return database.create_batch(
                batch,
                idempotency_key=idempotency_key,
                actor_id=actor_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Batch ID already exists") from exc

    @application.get("/api/v1/eggs")
    def list_eggs(batch_id: str | None = None) -> dict:
        return {"items": database.list_eggs(batch_id=batch_id)}

    @application.post("/api/v1/eggs")
    def create_egg(egg: EggCreate, request: Request) -> dict:
        actor_id = require_local_operator(request, resolved_settings)
        idempotency_key = require_idempotency_key(request)
        try:
            return database.create_egg(
                egg,
                idempotency_key=idempotency_key,
                actor_id=actor_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except sqlite3.IntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail="Egg ID exists or its batch does not exist",
            ) from exc

    @application.get("/api/v1/audit")
    def audit(limit: Annotated[int, Query(ge=1, le=500)] = 100) -> dict:
        return {"items": database.list_audit(limit=limit)}

    @application.get("/api/v1/sync/status")
    def sync_status() -> dict:
        return database.sync_status()

    @application.get("/api/v1/export/manifest")
    def export_manifest() -> dict:
        return database.manifest_export()

    if resolved_settings.web_dist_path:
        web_root = resolved_settings.web_dist_path.resolve()
        if not (web_root / "index.html").is_file():
            raise RuntimeError("Built web frontend is missing")
        application.mount("/assets", StaticFiles(directory=web_root / "assets"), name="assets")

        @application.get("/")
        def web_index():
            return FileResponse(web_root / "index.html")

    return application


app = create_app()
