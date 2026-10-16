"""Send camera frames outward to the Render service; no incoming laptop ports or tunnel."""
import hashlib
import hmac
import json
from pathlib import Path
import re
import time
from uuid import uuid4

import httpx

if __package__:
    from .camera_usb_bridge import open_camera, read_snapshot
else:
    from camera_usb_bridge import open_camera, read_snapshot

FRAME_PATH = "/api/v1/device/box/frame"


def render_origin(value):
    value = value.strip().rstrip("/")
    if not re.fullmatch(r"https://[a-z0-9-]+\.onrender\.com", value):
        raise ValueError("Enter only your https://SERVICE.onrender.com address")
    return value


def frame_headers(body, secret, key, timestamp):
    digest = hashlib.sha256(body).hexdigest()
    prefix = "\n".join(["BALUT-HMAC-V2", "POST", FRAME_PATH, "", key, "image/jpeg", digest])
    message = prefix.encode() + b"\n" + str(timestamp).encode() + b".BOX-USB-1." + body
    return {"Content-Type": "image/jpeg", "Idempotency-Key": key, "X-Image-SHA256": digest,
            "X-Device-Id": "BOX-USB-1", "X-Device-Timestamp": str(timestamp), "X-Device-Signature-Version": "2",
            "X-Device-Signature": hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()}


def main():
    root = Path(__file__).resolve().parents[1]
    profile_path = root / "deployment/private/render-device.json"
    if not profile_path.is_file():
        raise SystemExit("Run Prepare Render Account.cmd first. Copy the SAME protected settings to the school laptop.")
    profile = json.loads(profile_path.read_text(encoding="utf-8-sig"))
    if "origin" not in profile:
        profile["origin"] = render_origin(input("Paste your Render website address: "))
        profile_path.write_text(json.dumps(profile), encoding="utf-8")
    origin = render_origin(profile["origin"])
    if len(profile.get("secret", "")) < 32:
        raise SystemExit("Camera credentials are missing")
    camera = None
    session = uuid4().hex
    sequence = 0
    print("Camera connector active. Keep this window open; Ctrl+C stops it. No photos are written to this laptop.", flush=True)
    try:
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=httpx.Timeout(20, connect=10)) as client:
            while True:
                started = time.monotonic()
                try:
                    if camera is None:
                        camera = open_camera()
                    body = read_snapshot(camera)
                    sequence += 1
                    headers = frame_headers(body, profile["secret"], f"usb-{session}-{sequence}", int(time.time()))
                    response = client.post(origin + FRAME_PATH, content=body, headers=headers)
                    if response.status_code == 200 and response.headers.get("content-type", "").startswith("application/json"):
                        if sequence == 1 or sequence % 30 == 0:
                            print("Live frame accepted by Render.", flush=True)
                    elif response.status_code in {401, 403}:
                        raise SystemExit("Render rejected the camera credentials or clock. Check matching settings and sync Windows time.")
                    else:
                        print("Render is starting or unavailable. Retrying with a new frame; analysis requires fresh images.", flush=True)
                except OSError:
                    if camera is not None:
                        camera.close()
                        camera = None
                    print("USB disconnected. Waiting for the identified camera adapter.", flush=True)
                    time.sleep(2)
                except ValueError:
                    print("Camera frame unavailable. Check the USB cable and close other camera programs.", flush=True)
                    time.sleep(2)
                except httpx.HTTPError:
                    print("Network unavailable. Reconnecting without resending old frames.", flush=True)
                    time.sleep(3)
                time.sleep(max(0, 1 - (time.monotonic() - started)))
    except KeyboardInterrupt:
        print("Camera connector stopped.")
    finally:
        if camera is not None:
            camera.close()


if __name__ == "__main__":
    main()
