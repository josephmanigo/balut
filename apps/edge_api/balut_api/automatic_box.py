"""Camera-only automatic capture. Never commands motors, LEDs, or other outputs."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import ipaddress
import logging
import statistics
import sqlite3
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import APIRouter, HTTPException, Request
from PIL import Image
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .security import require_box_operator
from .model_service import decode_jpeg

MAX_IMAGE = 10 * 1024 * 1024
CAMERA_FRAMING_VERSION = 2
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def camera_origin(value: str) -> str:
    """Explicit LAN origins and the fixed school USB bridge; no DNS or arbitrary paths."""
    try:
        parsed = urlsplit(value.strip())
        address = ipaddress.IPv4Address(parsed.hostname or "")
        port = parsed.port
        school_usb = parsed.scheme == "http" and str(address) == "127.0.0.1" and port == 8767
        if (parsed.scheme not in {"http", "https"} or not (school_usb or any(address in net for net in PRIVATE_NETWORKS))
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment or port == 0):
            raise ValueError()
        return f"{parsed.scheme}://{address}" + (f":{port}" if port else "")
    except ValueError as exc:
        raise ValueError("Enter the camera's local IPv4 address, for example http://192.168.1.50.") from exc


def prepare_camera_frame(body: bytes):
    # Keep the light at the bottom and retain the entire sensor view.
    with decode_jpeg(body) as image:
        output = io.BytesIO()
        rotated = image.transpose(Image.Transpose.ROTATE_90)
        rotated.save(output, "JPEG", quality=95, subsampling=0)
        return output.getvalue()


def frame_data(body: bytes):
    if not body or len(body) > MAX_IMAGE:
        raise ValueError("Camera image exceeds 10 MB.")
    with decode_jpeg(body) as image:
        # Observe the center holder, excluding the enclosure edges.
        w, h = image.size
        center = image.crop((w // 8, h // 8, w * 7 // 8, h * 7 // 8))
        samples = list(center.convert("L").resize((48, 48)).get_flattened_data())
        if max(w, h) <= 800 and len(body) <= 512 * 1024 and not image.info.get("exif"):
            preview = body
        else:
            image.thumbnail((800, 800))
            output = io.BytesIO()
            image.save(output, "JPEG", quality=90)
            preview = output.getvalue()
        return samples, base64.b64encode(preview).decode("ascii")


def difference(left, right):
    # Remove uniform exposure shifts; localized shape changes still count.
    differences = [a - b for a, b in zip(left, right, strict=True)]
    shift = statistics.median(differences)
    return sum(abs(value - shift) > 25 for value in differences) / len(differences)


class AutomaticBox:
    def __init__(self, database, evidence, predict):
        self.database, self.evidence, self.predict = database, evidence, predict
        self.config = {}
        self.state, self.error = "not_connected", None
        self.preview = None
        self.result = None
        self.previous = None
        self.occupied_frames = self.empty_frames = 0
        self.connected = False
        self.lock = asyncio.Lock()
        self.task = None
        self.http = None

    async def start(self):
        self.config = self.database.box_config()
        if self.config.get("cameraUrl"):
            camera_origin(self.config["cameraUrl"])
            self.state = "connecting" if self.config.get("enabled") else "paused"
        if self.config.get("resultId"):
            self.result = self.database.get_prediction(self.config["resultId"])
        if self.config.get("reference"):
            self.config["awaitingEmpty"] = True
            self.save()
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(11), follow_redirects=False, trust_env=False)
        self.task = asyncio.create_task(self.run())

    async def close(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        if self.http:
            await self.http.aclose()

    def save(self):
        self.database.save_box_config(self.config)

    def status(self):
        return {"cameraUrl": self.config.get("cameraUrl", ""), "enabled": bool(self.config.get("enabled")),
                "connected": self.connected, "calibrated": bool(self.config.get("reference")),
                "state": self.state, "error": self.error, "preview": self.preview, "result": self.result,
                "detection": "camera_scene_change", "controlsMotion": False}

    async def fetch(self, origin):
        # The USB bridge may retry one rejected frame, with five seconds per attempt.
        async with asyncio.timeout(12):
            return await self._download(origin)

    async def _download(self, origin):
        async with self.http.stream("GET", origin + "/capture", params={"_balut": uuid4().hex}, headers={"Accept": "image/jpeg", "Cache-Control": "no-cache"}) as response:
            if response.status_code != 200:
                raise ValueError("Camera /capture did not return an image. Check its firmware and address.")
            if response.headers.get("content-type", "").split(";")[0] != "image/jpeg":
                raise ValueError("Camera /capture must return image/jpeg.")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_IMAGE:
                    raise ValueError("Camera image exceeds 10 MB.")
        return bytes(body)

    async def read_frame(self, origin):
        body = await self.fetch(origin)
        body = await run_in_threadpool(prepare_camera_frame, body)
        samples, preview = await run_in_threadpool(frame_data, body)
        self.preview, self.connected = preview, True
        return body, samples

    async def connect(self, address):
        if self.config.get("pending"):
            raise ValueError("Finish the pending analysis before changing cameras.")
        origin = camera_origin(address)
        await self.read_frame(origin)
        self.config = {"cameraUrl": origin, "enabled": False, "latched": False}
        self.result, self.previous, self.error = None, None, None
        self.occupied_frames = self.empty_frames = 0
        self.state = "needs_reference"
        self.save()

    async def calibrate(self):
        if not self.config.get("cameraUrl"):
            raise ValueError("Connect the camera first.")
        if self.config.get("pending"):
            raise ValueError("Finish the pending analysis before resetting the empty view.")
        frames = []
        for _ in range(3):
            _, samples = await self.read_frame(self.config["cameraUrl"])
            frames.append(samples)
            await asyncio.sleep(.25)
        if max(difference(frames[0], sample) for sample in frames[1:]) > .015:
            raise ValueError("The view is moving. Leave the box empty and try again.")
        self.config.update(reference=frames[-1], enabled=True, latched=False, framingVersion=CAMERA_FRAMING_VERSION)
        self.config.pop("awaitingEmpty", None)
        self.config.pop("resultId", None)
        self.result, self.previous, self.error = None, None, None
        self.occupied_frames = self.empty_frames = 0
        self.state = "waiting"
        self.save()

    def enable(self, enabled):
        if enabled and not self.config.get("reference"):
            raise ValueError("Save the empty-box view first.")
        self.config["enabled"] = enabled
        self.previous = None
        self.occupied_frames = self.empty_frames = 0
        self.state, self.error = ("connecting" if enabled else "paused"), None
        self.save()

    def require_new_reference(self):
        self.config.pop("reference", None)
        self.config.pop("awaitingEmpty", None)
        self.config["enabled"] = False
        self.previous = None
        self.occupied_frames = self.empty_frames = 0
        self.save()

    async def finish_pending(self):
        pending = self.config["pending"]
        self.state = "analyzing"
        # The persisted image and event key recover one record after timeouts/restarts.
        if not self.evidence.contains(pending["imageHash"]):
            raise ValueError("Pending capture evidence is unavailable.")
        image_path = self.evidence.path_for(pending["imageHash"])
        body = image_path.read_bytes()
        result = await run_in_threadpool(self.predict, body, pending["key"])
        self.config.update(resultId=result["predictionId"], latched=True)
        self.config.pop("pending", None)
        self.result = result
        self.state = "recapture" if result["recaptureRequested"] else "remove_egg"
        self.save()

    async def tick(self):
        if (self.config.get("reference") and self.config.get("framingVersion") != CAMERA_FRAMING_VERSION
                and not self.config.get("pending")):
            self.require_new_reference()
        if not self.config.get("enabled"):
            if self.config.get("cameraUrl"):
                await self.read_frame(self.config["cameraUrl"])
                self.state = "paused" if self.config.get("reference") else "needs_reference"
                self.error = None
            return
        self.error = None
        if self.config.get("pending"):
            await self.finish_pending()
            return
        body, samples = await self.read_frame(self.config["cameraUrl"])
        changed = difference(samples, self.config["reference"])
        motion = difference(samples, self.previous) if self.previous else 1.0
        self.previous = samples
        # Startup exposure can wash out the scene; brightness must also match the confirmed empty view.
        empty = changed <= .025 and abs(statistics.median(samples) - statistics.median(self.config["reference"])) <= 25
        self.empty_frames = self.empty_frames + 1 if empty else 0
        if self.config.get("latched") or self.config.get("awaitingEmpty"):
            self.state = ("checking_empty" if self.config.get("awaitingEmpty") else
                          "recapture" if self.result and self.result["recaptureRequested"] else "remove_egg")
            if self.empty_frames >= 3:
                self.config["latched"] = False
                self.config.pop("awaitingEmpty", None)
                self.occupied_frames = 0
                self.state = "waiting"
                self.save()
            return
        # shortcut: scene change is not a trained egg detector; replace with a validated presence sensor when wiring is known.
        self.occupied_frames = self.occupied_frames + 1 if changed >= .08 else 0
        self.state = "settling" if changed >= .08 else "waiting" if empty else "checking_empty"
        # A rotating holder may never stop; prefer a steady pair, otherwise capture the third occupied frame.
        if self.occupied_frames >= 2 and (motion <= .015 or self.occupied_frames >= 3):
            image_hash = hashlib.sha256(body).hexdigest()
            await run_in_threadpool(self.evidence.store_jpeg, body, image_hash)
            self.config.update(latched=True, pending={"key": "box-" + uuid4().hex, "imageHash": image_hash})
            self.save()
            await self.finish_pending()

    async def run(self):
        while True:
            try:
                async with self.lock:
                    await self.tick()
            except (httpx.HTTPError, OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
                self.state = "error" if self.config.get("pending") else "offline"
                self.error = ("Analysis interrupted. Retrying the saved capture." if self.config.get("pending")
                              else "Camera unavailable. Check camera power and connection.")
                self.connected = False
                self.previous = None
                self.occupied_frames = self.empty_frames = 0
                logging.getLogger("balut.box").warning("Automatic capture interrupted: %s", type(exc).__name__)
            await asyncio.sleep(3 if self.error else .05)


class CameraConnection(BaseModel):
    camera_url: str = Field(alias="cameraUrl", max_length=180)


class EmptyReference(BaseModel):
    empty_confirmed: bool = Field(alias="emptyConfirmed")


class BoxEnabled(BaseModel):
    enabled: bool


def box_router(box, settings):
    router = APIRouter(prefix="/api/v1/box")

    @router.get("/status")
    def status(request: Request):
        require_box_operator(request, settings)
        return box.status()

    async def mutate(request, action):
        require_box_operator(request, settings)
        try:
            await asyncio.wait_for(box.lock.acquire(), timeout=5)
        except TimeoutError as exc:
            raise HTTPException(status_code=409, detail="Camera is busy. Try again in a moment.")
        try:
            await action()
        except (httpx.HTTPError, OSError, ValueError) as exc:
            detail = str(exc) if isinstance(exc, ValueError) else "Cannot reach the camera. Check its address and connection."
            raise HTTPException(status_code=400, detail=detail) from exc
        finally:
            box.lock.release()
        return box.status()

    @router.post("/connect")
    async def connect(payload: CameraConnection, request: Request):
        return await mutate(request, lambda: box.connect(payload.camera_url))

    @router.post("/reference")
    async def reference(payload: EmptyReference, request: Request):
        if not payload.empty_confirmed:
            raise HTTPException(status_code=400, detail="Remove the egg and confirm the box is empty.")
        return await mutate(request, box.calibrate)

    @router.post("/enabled")
    async def enabled(payload: BoxEnabled, request: Request):
        async def change():
            box.enable(payload.enabled)
        return await mutate(request, change)

    return router
