"""Receive signed USB frames; never opens a camera URL on the cloud server."""
import asyncio
import hashlib
import time
from collections import OrderedDict

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .model_service import decode_jpeg
from .security import require_idempotency_key, verify_device_signature

USB_ORIGIN = "http://127.0.0.1:8767"


class RemoteCamera:
    def __init__(self, box, timeout=12):
        self.box, self.timeout = box, timeout
        self.condition = asyncio.Condition()
        self.upload_lock = asyncio.Lock()
        self.body = None
        self.received = self.delivered = 0
        self.sequence = self.consumed = 0
        self.seen = OrderedDict()

    async def receive(self, body, key):
        async with self.upload_lock:
            return await self._receive(body, key)

    async def _receive(self, body, key):
        digest = hashlib.sha256(body).hexdigest()
        if key in self.seen:
            if self.seen[key] != digest:
                raise HTTPException(409, "Frame key already used for different bytes")
            return {"accepted": True, "repeated": True}
        now = time.monotonic()
        if self.received and now - self.received < .2:
            raise HTTPException(429, "Send at most five frames per second")
        if not 4 < len(body) <= 128 * 1024:
            raise HTTPException(413, "USB frame exceeds 128 KB")
        def check():
            with decode_jpeg(body) as image:
                if image.size not in {(640, 480), (800, 600)}:
                    raise ValueError("Expected a 640 by 480 or 800 by 600 box camera frame")
        try:
            await run_in_threadpool(check)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        async with self.condition:
            self.body, self.received = body, time.monotonic()
            self.sequence += 1
            self.seen[key] = digest
            if len(self.seen) > 2048:
                self.seen.popitem(last=False)
            self.condition.notify_all()
        return {"accepted": True, "repeated": False}

    async def fetch(self, origin):
        if origin != USB_ORIGIN:
            raise ValueError("Use the USB box connector address")
        async with self.condition:
            try:
                await asyncio.wait_for(self.condition.wait_for(lambda: self.sequence > self.consumed), self.timeout)
            except TimeoutError as exc:
                raise ValueError("USB connector offline") from exc
            now = time.monotonic()
            if now - self.received > self.timeout:
                raise ValueError("Camera frame is stale")
            self.consumed = self.sequence
            interrupted = self.delivered and self.received - self.delivered > self.timeout
            self.delivered = self.received
            if interrupted and self.box.config.get("reference"):
                self.box.require_new_reference()
                raise ValueError("Connector reconnected; save a new empty view")
            return self.body


def remote_camera_router(camera, settings):
    router = APIRouter()

    @router.post("/api/v1/device/box/frame")
    async def upload(request: Request):
        device = await verify_device_signature(request, settings)
        if device != "BOX-USB-1" or request.url.query or request.headers.get("Content-Type") != "image/jpeg":
            raise HTTPException(400, "Invalid USB frame request")
        if abs(int(time.time()) - int(request.headers["X-Device-Timestamp"])) > 30:
            raise HTTPException(401, "Camera clock differs by more than 30 seconds; sync Windows time")
        body = await request.body()
        if request.headers.get("X-Image-SHA256") != hashlib.sha256(body).hexdigest():
            raise HTTPException(400, "Image checksum mismatch")
        return await camera.receive(body, require_idempotency_key(request))

    return router
