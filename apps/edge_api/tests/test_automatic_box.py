import asyncio
import base64
import io

import httpx
import pytest
from PIL import Image, ImageDraw

from balut_api.automatic_box import AutomaticBox, camera_origin, difference, frame_data
from balut_api.database import Database, canonical_sha256
from balut_api.evidence import EvidenceStore


def frame(occupied=False, brightness=40, offset=0):
    image = Image.new("RGB", (160, 120), (brightness,) * 3)
    if occupied:
        ImageDraw.Draw(image).ellipse((55 + offset, 25, 105 + offset, 100), fill=(200, 180, 120))
    output = io.BytesIO()
    image.save(output, "JPEG")
    return output.getvalue()


@pytest.mark.parametrize("address", ["http://127.0.0.1", "http://169.254.169.254", "http://8.8.8.8", "http://localhost", "http://camera.local", "http://user:pass@192.168.1.5", "http://192.168.1.5/anything", "http://192.168.1.5?redirect=1", "file:///camera", "http://[::1]", "http://192.168.1.5:0"])
def test_only_explicit_camera_origins(address):
    with pytest.raises(ValueError):
        camera_origin(address)


def test_camera_origin_and_scene_change_boundaries():
    assert camera_origin("http://127.0.0.1:8767/") == "http://127.0.0.1:8767"
    for url in ("https://127.0.0.1:8767", "http://127.0.0.1:8765", "http://127.0.0.2:8767", "http://localhost:8767", "http://127.0.0.1:8767/private", "http://127.0.0.1:8767?x=1"):
        with pytest.raises(ValueError):
            camera_origin(url)
    assert camera_origin(" http://192.168.1.50:80/ ") == "http://192.168.1.50:80"
    empty, _ = frame_data(frame())
    light, _ = frame_data(frame(brightness=90))
    occupied, _ = frame_data(frame(True))
    assert difference(empty, light) == 0
    assert difference(empty, occupied) > .08
    assert difference(occupied, occupied) == 0
    with pytest.raises((ValueError, OSError)):
        frame_data(b"not an image")


def test_camera_preview_preserves_native_detail_and_bounds_large_images():
    output = io.BytesIO()
    Image.new("RGB", (640, 480), "gray").save(output, "JPEG", quality=90)
    body = output.getvalue()
    samples, preview = frame_data(body)
    assert len(samples) == 2304 and base64.b64decode(preview) == body
    output = io.BytesIO()
    Image.new("RGB", (1600, 1200), "gray").save(output, "JPEG", quality=90)
    _, preview = frame_data(output.getvalue())
    with Image.open(io.BytesIO(base64.b64decode(preview))) as image:
        assert image.size == (800, 600)
    output = io.BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (320, 240), "gray").save(output, "JPEG", exif=exif)
    _, preview = frame_data(output.getvalue())
    with Image.open(io.BytesIO(base64.b64decode(preview))) as image:
        assert image.size == (240, 320) and not image.getexif()


@pytest.fixture
def camera_clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("balut_api.automatic_box.time.time", lambda: now[0])
    return now


def make_box(tmp_path, fail_first=False, prediction_class="DAY_16"):
    database = Database(tmp_path / "box.db")
    database.initialize()
    evidence = EvidenceStore(tmp_path / "evidence")
    predictions = []

    def predict(body, key):
        if fail_first and not predictions:
            predictions.append("interrupted")
            raise OSError("test interruption")
        predictions.append(key)
        body = body[0] if isinstance(body, list) else body
        result = {"modelId": "test-only", "modelReleaseId": "synthetic-software-test", "sourcePrediction": prediction_class,
                  "analysisOutcome": "CLASSIFIED", "recaptureRequested": False, "recaptureReasons": [], "reviewRequired": False,
                  "operationalOutcome": "NOT_AUTHORIZED", "operationalUseAuthorized": False, "captureSource": "iot_box"}
        return database.record_prediction(result, __import__('hashlib').sha256(body).hexdigest(), "automatic-box", key, canonical_sha256({"image": list(body)}))

    return AutomaticBox(database, evidence, predict), predictions


def test_camera_framing_rotates_light_to_bottom_and_preserves_both_edges_for_preview_and_analysis(tmp_path):
    async def scenario():
        box, _ = make_box(tmp_path)
        image = Image.new("RGB", (640, 480), "black")
        ImageDraw.Draw(image).rectangle((0, 0, 79, 479), fill="white")
        ImageDraw.Draw(image).rectangle((0, 0, 639, 19), fill="red")
        ImageDraw.Draw(image).rectangle((0, 460, 639, 479), fill="blue")
        output = io.BytesIO()
        image.save(output, "JPEG", quality=95)
        async def fetch(_): return output.getvalue()
        box.fetch = fetch
        body, samples = await box.read_frame("http://192.168.1.50")
        assert base64.b64decode(box.preview) == body and len(samples) == 2304
        with Image.open(io.BytesIO(body)) as rotated:
            assert rotated.size == (480, 640)
            assert min(rotated.getpixel((240, 600))) > 240
            assert max(rotated.getpixel((240, 40))) < 15
            assert rotated.getpixel((2, 40))[0] > 240
            assert rotated.getpixel((477, 40))[2] > 240
    asyncio.run(scenario())


@pytest.mark.parametrize("prediction_class", ["DAY_16", "DAY_18", "REJECT"])
def test_stable_capture_once_removal_rearms_and_restart_does_not_duplicate(tmp_path, prediction_class, camera_clock):
    async def scenario():
        box, calls = make_box(tmp_path, prediction_class=prediction_class)
        body = frame()
        async def fetch(_):
            camera_clock[0] += 2
            return body
        box.fetch = fetch
        await box.connect("http://192.168.1.50")
        await box.calibrate()
        for _ in range(4): await box.tick()
        assert not calls and box.state == "waiting"
        body = frame(True)
        for _ in range(8): await box.tick()
        assert len(calls) == 1 and box.state == "remove_egg"
        assert box.result["sourcePrediction"] == prediction_class
        assert len(box.database.list_predictions()) == 1

        restored = AutomaticBox(box.database, box.evidence, box.predict)
        restored.fetch = fetch
        await restored.start()
        await restored.close()
        for _ in range(5): await restored.tick()
        assert len(calls) == 1
        body = frame()
        for _ in range(3): await restored.tick()
        assert restored.state == "waiting"
        body = frame(True)
        for _ in range(4): await restored.tick()
        assert len(calls) == 2 and len(box.database.list_predictions()) == 2
    asyncio.run(scenario())


def test_preview_refreshes_before_calibration_and_while_paused_without_analysis(tmp_path, camera_clock):
    async def scenario():
        box, calls = make_box(tmp_path)
        body = frame()
        async def fetch(_):
            camera_clock[0] += 2
            return body
        box.fetch = fetch
        await box.connect("http://192.168.1.50")
        first = box.preview
        body = frame(True)
        await box.tick()
        assert box.preview != first and box.state == "needs_reference"
        assert not calls and not box.database.list_predictions()
        body = frame()
        await box.calibrate()
        box.enable(False)
        first = box.preview
        body = frame(True)
        for _ in range(5): await box.tick()
        assert box.preview != first and box.connected and box.state == "paused"
        assert not calls and not box.database.list_predictions()
    asyncio.run(scenario())


@pytest.mark.parametrize("moving", [False, True])
def test_capture_has_bounded_wait_for_rotation_but_ignores_brief_scene_changes(tmp_path, moving, camera_clock):
    async def scenario():
        box, calls = make_box(tmp_path)
        body = frame()
        async def fetch(_):
            camera_clock[0] += 2
            return body
        box.fetch = fetch
        await box.connect("http://192.168.1.50")
        await box.calibrate()
        body = frame(True)
        await box.tick()
        assert not calls
        body = frame()
        await box.tick()
        assert not calls and box.state == "waiting"
        for index in range(3 if moving else 2):
            body = frame(True, offset=12 if moving and index % 2 else -12 if moving else 0)
            await box.tick()
            if index == 0:
                assert not calls
        assert not calls and box.state == "capturing_views"
        for _ in range(2): await box.tick()
        assert len(calls) == 1 and box.state == "remove_egg"
        for _ in range(5): await box.tick()
        assert len(calls) == 1
    asyncio.run(scenario())


def test_saved_capture_recovers_after_interruption_and_pause_preserves_latch(tmp_path, camera_clock):
    async def scenario():
        box, calls = make_box(tmp_path, fail_first=True)
        body = frame()
        async def fetch(_):
            camera_clock[0] += 2
            return body
        box.fetch = fetch
        await box.connect("http://192.168.1.50")
        await box.calibrate()
        body = frame(True)
        with pytest.raises(OSError):
            for _ in range(4): await box.tick()
        pending = box.database.box_config()["pending"]
        assert box.evidence.contains(pending["imageHash"])
        box.config.pop("framingVersion")
        box.enable(False)
        await box.tick()
        assert len(calls) == 1
        with pytest.raises(ValueError, match="pending"):
            await box.connect("http://192.168.1.51")
        box.enable(True)
        await box.tick()
        assert calls[-1] == pending["key"]
        assert len(box.database.list_predictions()) == 1
        assert "pending" not in box.database.box_config()
        for _ in range(6): await box.tick()
        assert len(box.database.list_predictions()) == 1
        assert not box.config.get("reference") and not box.config["enabled"]
    asyncio.run(scenario())


def test_network_adapter_rejects_redirects_and_non_images(tmp_path):
    async def scenario():
        box, _ = make_box(tmp_path)
        for response in [httpx.Response(302, headers={"location": "http://127.0.0.1/"}), httpx.Response(200, headers={"content-type": "text/html"}, content=b"hello")]:
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response), follow_redirects=False) as client:
                box.http = client
                with pytest.raises(ValueError):
                    await box.fetch("http://192.168.1.50")
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, headers={"content-type": "image/jpeg"}, content=frame()))) as client:
            box.http = client
            body, samples = await box.read_frame("http://192.168.1.50")
            assert base64.b64decode(box.preview) == body and len(samples) == 2304
            with Image.open(io.BytesIO(body)) as image:
                assert image.size == (120, 160)
    asyncio.run(scenario())


def test_box_setup_requires_operator_and_empty_confirmation(client, local_headers):
    assert client.get("/api/v1/box/status").status_code == 403
    assert client.get("/api/v1/box/status", headers=local_headers).json()["state"] == "not_connected"
    assert client.post("/api/v1/box/connect", headers=local_headers, json={"cameraUrl": "http://127.0.0.1"}).status_code == 400
    assert client.post("/api/v1/box/reference", headers=local_headers, json={"emptyConfirmed": False}).status_code == 400
    assert client.post("/api/v1/box/enabled", headers=local_headers, json={"enabled": True}).status_code == 400
