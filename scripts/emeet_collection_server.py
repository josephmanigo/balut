"""Loopback-only guided collection; never changes the deployed model or cloud data."""
import argparse
import base64
import binascii
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.capture_emeet_egg import finish, sha, write
from balut_api.model_service import decode_jpeg


def create_app(dataset):
    dataset = dataset.resolve()
    plan_path = dataset / "collection-plan.json"
    plan_hash = sha(plan_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def local_only(request, call_next):
        from fastapi.responses import JSONResponse
        if request.url.hostname not in {"127.0.0.1", "localhost", "testserver"}:
            return JSONResponse({"detail": "Loopback collection only"}, status_code=403)
        if request.method != "GET" and request.headers.get("origin") != str(request.base_url).rstrip("/"):
            return JSONResponse({"detail": "Use the local collection page"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=()"
        return response

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (Path(__file__).with_name("emeet_collection.html")).read_text(encoding="utf-8")

    @app.get("/status")
    def status():
        completed = {json.loads(p.read_text(encoding="utf-8-sig"))["egg_id"]
                     for p in (dataset / "captures").glob("*/*/record.json")
                     if json.loads(p.read_text(encoding="utf-8-sig")).get("status") == "complete"}
        eggs = [dict(id=key, **value, complete=key in completed) for key, value in plan["eggs"].items()
                if value["partition"] != "test"]
        eggs.sort(key=lambda egg: (egg["partition"] == "validation", int(egg["id"].split("-")[1]), egg["id"]))
        return {"eggs": eggs, "completed": sum(e["complete"] for e in eggs), "total": len(eggs),
                "reserved_test_eggs": sum(e["partition"] == "test" for e in plan["eggs"].values()),
                "camera": plan["camera"]}

    @app.post("/capture/{egg_id}")
    async def save_capture(egg_id: str, request: Request):
        if sha(plan_path) != plan_hash or (dataset / "candidate-lock.json").exists():
            raise HTTPException(409, "Collection plan changed or candidate is locked")
        assignment = plan["eggs"].get(egg_id)
        if not assignment or assignment["partition"] == "test":
            raise HTTPException(400, "Use a planned development egg; keep test eggs reserved")
        if any(json.loads(p.read_text(encoding="utf-8-sig")).get("status") == "complete"
               for p in (dataset / "captures" / egg_id).glob("*/record.json")):
            raise HTTPException(409, "This egg is already saved; use a different egg")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 9 * 1024 * 1024:
                raise HTTPException(413, "Video sample exceeds 9 MB")
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict) or payload.get("newEggConfirmed") is not True:
                raise ValueError("Confirm a new egg and record twelve frames")
            if not isinstance(payload.get("frames"), list) or len(payload["frames"]) != 12:
                raise ValueError("Confirm a new egg and record twelve frames")
            frames = [base64.b64decode(frame, validate=True) for frame in payload["frames"]]
            for frame in frames:
                if len(frame) > 512 * 1024:
                    raise ValueError("Frame exceeds 512 KB")
                with decode_jpeg(frame) as image:
                    if list(image.size) != plan["capture_size"]:
                        raise ValueError("Select the EMEET camera at 1920 by 1080")
            if len(set(frames[2:])) < 3:
                raise ValueError("Video is frozen; reconnect the camera")
        except (ValueError, KeyError, TypeError, binascii.Error) as exc:
            raise HTTPException(400, str(exc)) from exc
        # Uploads can overlap; recheck after the last await before writing evidence.
        if sha(plan_path) != plan_hash or (dataset / "candidate-lock.json").exists():
            raise HTTPException(409, "Collection plan changed or candidate is locked")
        if any(json.loads(p.read_text(encoding="utf-8-sig")).get("status") == "complete"
               for p in (dataset / "captures" / egg_id).glob("*/record.json")):
            raise HTTPException(409, "This egg is already saved; use a different egg")
        started = datetime.now(timezone.utc)
        folder = dataset / "captures" / egg_id / started.strftime("%Y%m%dT%H%M%S%fZ")
        folder.mkdir(parents=True)
        record_path = folder / "record.json"
        write(record_path, {"egg_id": egg_id, "source_label": assignment["label"],
              "partition": assignment["partition"], "camera": plan["camera"], "started_at": started.isoformat(),
              "status": "capturing", "plan_sha256": plan_hash, "model_used_for_label": False})
        for i, frame in enumerate(frames, 1):
            (folder / f"frame-{i:03d}.jpg").write_bytes(frame)
        try:
            record = finish(dataset, folder)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"saved": True, "egg": egg_id, "frames": len(record["views"])}

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args()
    uvicorn.run(create_app(args.dataset), host="127.0.0.1", port=8775, log_level="warning")
