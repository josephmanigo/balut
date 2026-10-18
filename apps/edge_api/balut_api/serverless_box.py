"""Run the existing capture state machine per upload, under a shared database lease."""
import asyncio
import hashlib
import re
import time
from copy import deepcopy
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .automatic_box import AutomaticBox, CameraConnection, EmptyReference, BoxEnabled, empty_view_matches, CAMERA_FRAMING_VERSION
from .model_service import decode_jpeg
from .remote_camera import USB_ORIGIN
from .security import require_box_operator, require_idempotency_key
from .supabase_store import CloudStorageError


class SavedBox(AutomaticBox):
    def __init__(self, database, evidence, predict, cloud, snapshot, token=None):
        super().__init__(database, evidence, predict)
        self.cloud, self.token = cloud, token
        self.config = snapshot.get("config", {"cameraUrl": USB_ORIGIN, "enabled": False})
        for name in ("state", "error", "preview", "result", "previous", "occupied_frames", "empty_frames"):
            if name in snapshot:
                setattr(self, name, snapshot[name])
        self.received = snapshot.get("received", 0)
        self.frames = snapshot.get("frames", [])
        self.seen = snapshot.get("seen", [])
        self.connected = bool(self.received and time.time() - self.received <= 12)
        self.body = None
        self.stationary_frame = False
        self.committed = deepcopy(self.snapshot())

    def snapshot(self):
        return {name: getattr(self, name) for name in (
            "config", "state", "error", "preview", "result", "previous", "occupied_frames", "empty_frames",
            "received", "frames", "seen")}

    def save(self, release=False):
        saved = self.cloud.request("POST", "/rest/v1/rpc/balut_save_camera", json={
            "p_token": self.token, "p_value": self.snapshot(), "p_release": release}).json()
        if not saved:
            raise CloudStorageError("Camera lease expired; retry the saved capture")
        self.committed = deepcopy(self.snapshot())

    async def fetch(self, origin):
        if origin != USB_ORIGIN or self.body is None:
            raise ValueError("Start the USB cloud connector first.")
        return self.body

    async def read_frame(self, origin):
        body, samples = await super().read_frame(origin)
        self.frames = (self.frames + [samples])[-3:]
        return body, samples

    def reference_ready(self):
        return self.config.get("framingVersion") == CAMERA_FRAMING_VERSION and self.connected and len(self.frames) == 3 and all(
            empty_view_matches(samples, self.frames[0]) for samples in self.frames[1:])

    def require_new_reference(self):
        self.config.pop("referenceDeadline", None)
        self.error = None
        super().require_new_reference()

    def request_reference(self):
        if self.config.get("pending"):
            raise ValueError("Finish the pending analysis before resetting the empty view.")
        if not self.connected:
            raise ValueError("Reconnect the camera before saving the empty view.")
        self.require_new_reference()
        # Cached frames can still contain the egg removed just before confirmation.
        self.config["referenceDeadline"] = time.time() + 20
        self.config["framingVersion"] = CAMERA_FRAMING_VERSION
        self.frames = []
        self.state, self.result = "calibrating", None

    async def tick(self):
        previous_error = self.error
        await super().tick()
        deadline = self.config.get("referenceDeadline")
        if deadline:
            if time.time() > deadline:
                self.config.pop("referenceDeadline")
                self.state, self.error = "needs_reference", "No steady empty view was saved. Keep the box empty, steady the camera and lighting, then save again."
            elif self.reference_ready():
                self.calibrate_saved()
            else:
                self.state = "calibrating"
        elif not self.config.get("enabled"):
            self.error = previous_error
        if self.state != "settling":
            self.config.pop("stationaryRequested", None)

    async def capture_frame(self, body):
        if self.config.get("stationaryCapture") and not self.stationary_frame:
            self.config["stationaryRequested"] = True
            return
        self.config.pop("stationaryRequested", None)
        await super().capture_frame(body, stationary=self.stationary_frame)

    def status(self):
        result = super().status()
        result["cloudCapture"] = True
        if not self.connected:
            result.update(state="offline", error="Start the USB cloud connector to receive fresh camera frames.", preview=None)
        return result

    async def finish_pending(self):
        self.state, self.error = "analyzing", None
        self.save()
        try:
            await super().finish_pending()
        except (OSError, RuntimeError, ValueError):
            self.state, self.error = "error", "Capture saved. The next camera upload will retry analysis."
            self.save()
            raise

    def calibrate_saved(self):
        if self.config.get("pending"):
            raise ValueError("Finish the pending analysis before resetting the empty view.")
        if not self.connected or len(self.frames) != 3:
            raise ValueError("Wait for three fresh camera frames before saving the empty view.")
        if not self.reference_ready():
            raise ValueError("The view is moving. Leave the box empty and try again.")
        self.config.update(reference=self.frames[-1], enabled=True, latched=False, framingVersion=CAMERA_FRAMING_VERSION)
        self.config.pop("collection", None)
        self.config.pop("awaitingEmpty", None)
        self.config.pop("referenceDeadline", None)
        self.config.pop("resultId", None)
        self.result, self.previous, self.error = None, None, None
        self.occupied_frames = self.empty_frames = 0
        self.state = "waiting"


class ServerlessBox:
    def __init__(self, database, evidence, predict, cloud):
        self.database, self.evidence, self.predict, self.cloud = database, evidence, predict, cloud

    def box(self, snapshot, token=None):
        return SavedBox(self.database, self.evidence, self.predict, self.cloud, snapshot, token)

    def status(self):
        rows = self.cloud.request("GET", "/rest/v1/balut_camera", params={"id": "eq.1", "select": "value"}).json()
        if not rows:
            raise CloudStorageError("Shared camera state is missing")
        return self.box(rows[0]["value"]).status()

    def mutate(self, action):
        token = str(uuid4())
        snapshot = self.cloud.request("POST", "/rest/v1/rpc/balut_claim_camera", json={"p_token": token}).json()
        if snapshot is None:
            raise HTTPException(409, "Camera is busy. Try again in a moment.", headers={"Retry-After": "1"})
        box = self.box(snapshot, token)
        try:
            response = action(box)
        except Exception:
            # Preserve any durable pending capture, even when inference or the response fails.
            try:
                self.box(box.committed, token).save(release=True)
            except CloudStorageError:
                pass
            raise
        box.save(release=True)
        return response

    async def receive(self, body, key, camera_session="signed-usb"):
        return await run_in_threadpool(self.receive_frame, body, key, camera_session)

    def receive_frame(self, body, key, camera_session="signed-usb"):
        motor_frame = re.fullmatch(r"usb-motor-(preview|still)-([0-9a-f]{32})-[1-9][0-9]*", key)
        if key.startswith("usb-motor-"):
            if not motor_frame or camera_session != "signed-usb":
                raise HTTPException(400, "Motor capture requires the signed local USB connector")
            camera_session += "-motor-" + motor_frame[2]
        if not 4 < len(body) <= 128 * 1024:
            raise HTTPException(413, "USB frame exceeds 128 KB")
        try:
            with decode_jpeg(body) as image:
                source_size = list(image.size)
                if image.size not in {(640, 480), (800, 600)}:
                    raise ValueError("Expected a 640 by 480 or 800 by 600 box camera frame")
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        digest = hashlib.sha256(body).hexdigest()

        def process(box):
            def response(repeated):
                result = {"accepted": True, "repeated": repeated}
                if motor_frame:
                    result["captureRequested"] = bool(box.config.get("stationaryRequested"))
                return result

            seen = dict(box.seen)
            if key in seen:
                if seen[key] != digest:
                    raise HTTPException(409, "Frame key already used for different bytes")
                if box.config.get("pending"):
                    asyncio.run(box.finish_pending())
                return response(True)
            now = time.time()
            if box.received and now - box.received < .2:
                raise HTTPException(429, "Send at most five frames per second")
            if box.config.get("pending"):
                asyncio.run(box.finish_pending())
            framing_changed = (box.config.get("sourceSize", [640, 480]) != source_size
                               or box.config.get("framingVersion") != CAMERA_FRAMING_VERSION)
            if framing_changed or box.config.get("cameraSession") != camera_session or box.received and now - box.received > 12:
                if not framing_changed and box.config.get("reference"):
                    # Reuse only a confirmed view, and require fresh empty matches before capturing again.
                    box.config["awaitingEmpty"] = True
                    box.enable(bool(box.config.get("enabled")))
                else:
                    box.require_new_reference()
                box.frames = []
            box.config["cameraSession"] = camera_session
            box.config["sourceSize"] = source_size
            box.config["framingVersion"] = CAMERA_FRAMING_VERSION
            box.config["stationaryCapture"] = bool(motor_frame)
            box.stationary_frame = bool(motor_frame and motor_frame[1] == "still")
            box.body, box.received, box.connected = body, now, True
            asyncio.run(box.tick())
            # 256 entries cover the entire 30-second signature window at the maximum frame rate.
            box.seen = (box.seen + [[key, digest]])[-256:]
            return response(False)

        return self.mutate(process)


def serverless_box_router(box, settings):
    router = APIRouter(prefix="/api/v1/box")

    def change(request, action):
        require_box_operator(request, settings)
        def apply(saved):
            action(saved)
            return saved.status()
        try:
            return box.mutate(apply)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/status")
    def status(request: Request):
        require_box_operator(request, settings)
        return box.status()

    @router.post("/frame")
    async def browser_frame(request: Request):
        require_box_operator(request, settings)
        if request.headers.get("Content-Type") != "image/jpeg" or request.url.query:
            raise HTTPException(400, "Send a single USB camera JPEG.")
        try:
            camera_session = str(UUID(request.headers.get("X-Balut-Camera-Session", "")))
        except ValueError as exc:
            raise HTTPException(400, "Reconnect the USB camera from this page.") from exc
        return await box.receive(await request.body(), require_idempotency_key(request), "browser-" + camera_session)

    @router.post("/connect")
    def connect(payload: CameraConnection, request: Request):
        def reset(saved):
            if payload.camera_url != USB_ORIGIN:
                raise ValueError("Use the USB box connector address.")
            if not saved.connected:
                raise ValueError("Start the USB cloud connector first.")
            if saved.config.get("pending"):
                raise ValueError("Finish the pending analysis before changing cameras.")
            saved.require_new_reference()
            saved.state = "needs_reference"
        return change(request, reset)

    @router.post("/reference")
    def reference(payload: EmptyReference, request: Request):
        if not payload.empty_confirmed:
            raise HTTPException(400, "Remove the egg and confirm the box is empty.")
        return change(request, lambda saved: saved.request_reference())

    @router.post("/enabled")
    def enabled(payload: BoxEnabled, request: Request):
        def toggle(saved):
            if payload.enabled and not saved.connected:
                raise ValueError("Reconnect the camera and save a fresh empty view first.")
            saved.enable(payload.enabled)
        return change(request, toggle)

    return router
