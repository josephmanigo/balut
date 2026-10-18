"""Record one user-identified egg for an isolated camera pilot, never active training."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/edge_api"))
from balut_api.automatic_box import prepare_camera_frame
from balut_api.model_service import decode_jpeg
if __package__:
    from .camera_usb_bridge import open_camera, read_fresh_snapshot
else:
    from camera_usb_bridge import open_camera, read_fresh_snapshot

OUTPUT = ROOT / "output/physical-pilot-20261018"


def partition_for(egg_id):
    match = re.fullmatch(r"(16|18)-([1-9]|1[0-5])", egg_id)
    if not match:
        raise ValueError("Expected a distinct egg ID from 16-1..16-15 or 18-1..18-15")
    age, index = map(int, match.groups())
    # Keep the originally reserved fifth egg untouched as the pilot expands.
    return age, "test" if index in (5, 12, 13, 14, 15) else "train" if index in (1, 2, 3, 6, 7) else "validation"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("egg_id")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--source", type=Path, help="Import an image for audit only; excluded from candidate fitting")
    source.add_argument("--prediction", help="Record the single frame from a confirmed live automatic scan")
    source.add_argument("--live", action="store_true", help="Record a fresh frame from the running camera stream")
    args = parser.parse_args()
    age, partition = partition_for(args.egg_id)
    OUTPUT.mkdir(exist_ok=True)
    if partition == "test" and not (OUTPUT / "candidate/selection-lock.json").is_file():
        raise ValueError("Lock the candidate before recording final-test eggs")
    plan = {"scope": "EXPLORATORY_USER_REPORTED_PHYSICAL_EGGS", "images_per_egg": 1,
            "split": {f"{day}-{i}": partition_for(f"{day}-{i}")[1] for day in (16, 18) for i in range(1, 16)},
            "label_authority": "User reports uncooked farm eggs with confirmed incubation dates; exact records not supplied",
            "species": None, "incubation_timestamps": None, "batch_ids": None,
            "rules": ["Do not reuse an egg under another ID", "Do not inspect test images or predictions before candidate lock",
                      "No automatic promotion or operational accuracy claim from this pilot"]}
    plan_path = OUTPUT / "capture-plan.json"
    if plan_path.exists():
        if json.loads(plan_path.read_text()) != plan:
            raise ValueError("Capture plan changed")
    else:
        plan_path.write_text(json.dumps(plan, indent=2))
    image_path, record_path = OUTPUT / f"{args.egg_id}.jpg", OUTPUT / f"{args.egg_id}.json"
    if image_path.exists() or record_path.exists():
        raise ValueError("This egg is already recorded; do not overwrite or relabel it")
    prediction = None
    live = None
    if args.prediction or args.live:
        from balut_api.supabase_store import Supabase
        profile = json.loads((ROOT / "deployment/private/supabase.json").read_text(encoding="utf-8-sig"))
        cloud = Supabase(profile["url"], profile["secret_key"])
    if args.live:
        marker, advances = None, 0
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            live = cloud.request("GET", "/rest/v1/balut_camera", params={"id": "eq.1", "select": "value"}).json()[0]["value"]
            received = live.get("received", 0)
            if marker is not None and received > marker:
                advances += 1
            marker = received
            # Two updates clear any upload already in flight when recording began.
            if advances >= 2:
                break
            time.sleep(1)
        else:
            raise ValueError("Live camera did not supply fresh frames")
        if (live["config"].get("cameraSession") != "signed-usb" or live["config"].get("sourceSize") != [800, 600]
                or live["config"].get("framingVersion") != 2 or live["config"].get("pending")):
            raise ValueError("Expected the identified USB camera stream")
        body = base64.b64decode(live["preview"], validate=True)
    elif args.prediction:
        prediction_id = str(UUID(args.prediction))
        response = cloud.request("GET", "/rest/v1/balut_predictions", params={"id": f"eq.{prediction_id}", "select": "response"}).json()
        if len(response) != 1:
            raise ValueError("Live prediction not found")
        prediction = response[0]["response"]
        digest = prediction.get("imageSha256", "")
        if (prediction.get("predictionId") != prediction_id or prediction.get("isSimulated") is not False or prediction.get("multiView")
                or prediction.get("captureSource") != "iot_box" or not re.fullmatch(r"[a-f0-9]{64}", digest)):
            raise ValueError("Expected one real automatic camera scan")
        body = cloud.request("GET", f"/storage/v1/object/balut-evidence/{digest[:2]}/{digest}.jpg").content
        if hashlib.sha256(body).hexdigest() != digest:
            raise ValueError("Saved live scan failed its image checksum")
    elif args.source:
        body = args.source.read_bytes()
    else:
        with open_camera() as camera:
            for attempt in range(3):
                try:
                    body = prepare_camera_frame(read_fresh_snapshot(camera))
                    break
                except ValueError:
                    if attempt == 2:
                        raise
    with decode_jpeg(body) as image:
        if image.size != (600, 800):
            raise ValueError("Camera framing changed; keep the pilot at 600 by 800")
    digest = hashlib.sha256(body).hexdigest()
    for previous in OUTPUT.glob("*-*.json"):
        if json.loads(previous.read_text()).get("sha256") == digest:
            raise ValueError("Identical image already recorded for another egg")
    record = {"egg_id": args.egg_id, "reported_age_days": age, "partition": partition,
              "label_authority": plan["label_authority"], "image": image_path.name, "sha256": digest,
              "recorded_at": datetime.now(timezone.utc).isoformat(),
              "capture_source": "live_camera_stream" if live else f"live_prediction:{args.prediction}" if prediction else str(args.source.resolve()) if args.source else "identified USB box camera",
              "freshness": "live_stream_refreshed" if live else "live_single_frame_prediction" if prediction else "source_import" if args.source else "queued_frame_discarded",
              "model_used_for_label": False, "motor_commands": 0}
    if prediction:
        record["prediction_id"] = prediction["predictionId"]
        record["captured_at"] = prediction["createdAt"]
    if live:
        record["captured_at"] = datetime.fromtimestamp(live["received"], timezone.utc).isoformat()
        record["stream_frame_key"] = live["seen"][-1][0]
    with image_path.open("xb") as handle:
        handle.write(body)
    with record_path.open("x") as handle:
        json.dump(record, handle, indent=2)
    print(json.dumps({"egg": args.egg_id, "partition": partition, "saved": True, "portClosed": True}))


if __name__ == "__main__":
    main()
