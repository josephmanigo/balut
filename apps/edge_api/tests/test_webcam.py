import base64
import io
import json
import time
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from balut_api.main import create_app
from balut_api.serverless_box import ServerlessBox
from balut_api.supabase_store import Supabase, SupabaseEvidence
from test_automatic_box import make_box
from test_production import settings_for
from test_serverless import shared
from test_supabase_store import provider, URL, SECRET

SESSION = "12345678-1234-4234-8234-123456789012"


def webcam_frame(occupied=False, variation=0, size=(1920, 1080)):
    image = Image.new("RGB", size, (40, 40, 40))
    if occupied:
        w, h = size
        ImageDraw.Draw(image).ellipse((w * .3 + variation, h * .15, w * .7, h * .9), fill=(210, 190, 120))
    output = io.BytesIO()
    image.save(output, "JPEG", quality=90)
    return output.getvalue()


def test_site_allows_own_webcam_but_not_microphone(tmp_path):
    app = create_app(settings_for(tmp_path))
    with TestClient(app) as client:
        policy = client.get("/health").headers["permissions-policy"]
        assert "camera=(self)" in policy
        assert "microphone=()" in policy
    config = json.loads((Path(__file__).parents[3] / "vercel.json").read_text())
    headers = {h["key"]: h["value"] for h in config["headers"][0]["headers"]}
    assert "camera=(self)" in headers["Permissions-Policy"]


def test_webcam_1080p_keeps_orientation_and_uses_three_fresh_stream_frames(tmp_path, shared, monkeypatch):
    local, predictions = make_box(tmp_path)
    now = [time.time()]
    monkeypatch.setattr("balut_api.serverless_box.time.time", lambda: now[0])
    sequence = 0
    def worker():
        return ServerlessBox(local.database, local.evidence, local.predict, Supabase(URL, SECRET))
    def send(occupied=False, variation=0, session=SESSION):
        nonlocal sequence
        sequence += 1
        now[0] += 1
        return worker().receive_frame(webcam_frame(occupied, variation), f"webcam-{session}-{sequence}", "browser-" + session, owner="operator")
    for _ in range(3):
        send()
    worker().mutate(lambda box: box.calibrate_saved())
    with Image.open(io.BytesIO(base64.b64decode(worker().status()["preview"]))) as preview:
        assert preview.size == (800, 450)
    for _ in range(4):
        send(True)
    assert not predictions  # Repeated identical frames cannot complete a scan.
    assert worker().status()["state"] == "capturing_views"
    send(True, 8)
    send(True, 16)
    assert len(predictions) == 1 and predictions[0].startswith("box-webcam-views-")
    assert worker().status()["state"] == "remove_egg"
    for i in range(5):
        send(True, i * 4)
    assert len(predictions) == 1
    send()
    send()
    assert worker().status()["state"] == "waiting"


def test_webcam_mode_requires_matching_browser_session_and_retains_serial_limits(tmp_path, shared):
    local, _ = make_box(tmp_path)
    worker = ServerlessBox(local.database, local.evidence, local.predict, Supabase(URL, SECRET))
    for key, session in ((f"webcam-{SESSION}-1", "signed-usb"), (f"webcam-{SESSION}-1", "browser-wrong"), ("old-serial-frame", "signed-usb")):
        with pytest.raises(HTTPException):
            worker.receive_frame(webcam_frame(), key, session)


@pytest.mark.parametrize("interruption", ["none", "reconnect", "pause", "empty", "expiry"])
def test_webcam_partial_scan_survives_cold_workers_but_not_interrupted_eggs(tmp_path, shared, monkeypatch, interruption):
    local, predictions = make_box(tmp_path)
    now, sequence = [time.time()], 0
    session = SESSION
    monkeypatch.setattr("balut_api.serverless_box.time.time", lambda: now[0])
    cloud = Supabase(URL, SECRET)
    def worker():
        evidence = SupabaseEvidence(tmp_path / f"worker-{sequence}", cloud)
        return ServerlessBox(local.database, evidence, local.predict, cloud)
    def send(occupied=False, variation=0):
        nonlocal sequence
        sequence += 1
        now[0] += 1
        return worker().receive_frame(webcam_frame(occupied, variation), f"webcam-{session}-{sequence}", "browser-" + session)
    for _ in range(3): send()
    worker().mutate(lambda box: box.calibrate_saved())
    send(True)
    send(True)
    assert len(shared["camera"]["config"]["webcamViews"]) == 1
    if interruption == "reconnect": session = "87654321-1234-4234-8234-123456789012"
    elif interruption == "pause": worker().mutate(lambda box: box.enable(False))
    elif interruption == "empty": send()
    elif interruption == "expiry": now[0] += 20
    send(True, 10)
    send(True, 20)
    assert len(predictions) == (1 if interruption == "none" else 0)


@pytest.mark.parametrize("accepted_pass", [2, None])
def test_webcam_retries_uncertain_video_automatically_then_stops(tmp_path, shared, monkeypatch, accepted_pass):
    local, _ = make_box(tmp_path)
    now, sequence, attempts = [time.time()], 0, []
    monkeypatch.setattr("balut_api.serverless_box.time.time", lambda: now[0])

    def predict(bodies, key, owner=None):
        attempts.append(key)
        accepted = len(attempts) == accepted_pass
        return {"predictionId": key, "sourcePrediction": "DAY_16" if accepted else None,
                "analysisOutcome": "CLASSIFIED" if accepted else "RECAPTURE_REQUIRED",
                "recaptureRequested": not accepted, "recaptureReasons": [] if accepted else ["UNFAMILIAR_APPEARANCE"]}

    def worker():
        return ServerlessBox(local.database, local.evidence, predict, Supabase(URL, SECRET))

    def send(occupied=False):
        nonlocal sequence
        sequence += 1
        now[0] += 1
        body = webcam_frame(occupied, sequence % 24)
        key = f"webcam-{SESSION}-{sequence}"
        worker().receive_frame(body, key, "browser-" + SESSION)
        # A repeated upload must not spend another scan pass.
        worker().receive_frame(body, key, "browser-" + SESSION)

    for _ in range(3): send()
    worker().mutate(lambda box: box.calibrate_saved())
    for _ in range(4): send(True)
    assert len(attempts) == 1
    assert worker().status()["state"] == "settling"
    assert not shared["camera"]["config"]["latched"]
    for _ in range(24): send(True)
    assert len(attempts) == (accepted_pass or 3)
    assert len(set(attempts)) == len(attempts)
    assert worker().status()["state"] == ("remove_egg" if accepted_pass else "recapture")
    assert shared["camera"]["config"]["latched"]
    send()
    send()
    assert worker().status()["state"] == "waiting"
    assert not shared["camera"]["config"].get("webcamScanAttempts")
    for _ in range(4): send(True)
    assert len(attempts) == (accepted_pass or 3) + 1
    assert worker().status()["state"] == "settling"
