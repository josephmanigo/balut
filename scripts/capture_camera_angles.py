"""Save three paused views of one numbered egg without changing its dataset split."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/edge_api"))
from balut_api.automatic_box import prepare_camera_frame
from balut_api.model_service import decode_jpeg
if __package__:
    from .camera_usb_bridge import open_camera
    from .capture_camera_pilot import partition_for
    from .spinner_control import open_spinner, capture_views
else:
    from camera_usb_bridge import open_camera
    from capture_camera_pilot import partition_for
    from spinner_control import open_spinner, capture_views

OUTPUT = ROOT / "output/physical-multiangle-20261019"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("egg_id")
    args = parser.parse_args()
    age, partition = partition_for(args.egg_id)
    original = json.loads((ROOT / "output/physical-pilot-20261018" / f"{args.egg_id}.json").read_text())
    if original["egg_id"] != args.egg_id or original["partition"] != partition or original["reported_age_days"] != age:
        raise ValueError("Original egg identity or partition changed")
    target = OUTPUT / args.egg_id
    if target.exists():
        raise FileExistsError("Egg already captured; preserve its images and label")
    camera, spinner = None, None
    try:
        camera = open_camera()
        spinner = open_spinner()
        views = capture_views(camera, spinner)
        prepared = []
        for body, metadata in views:
            body = prepare_camera_frame(body)
            with decode_jpeg(body) as image:
                if image.size != (600, 800):
                    raise ValueError("Expected the unchanged 600 by 800 serving frame")
            prepared.append((body, {**metadata, "raw_sha256": metadata["sha256"], "sha256": hashlib.sha256(body).hexdigest()}))
        target.mkdir(parents=True)
        records = []
        for body, metadata in prepared:
            name = f'view-{metadata["view_index"]}.jpg'
            with (target / name).open("xb") as handle:
                handle.write(body)
            records.append({**metadata, "image": name})
        record = {"egg_id": args.egg_id, "reported_age_days": age, "partition": partition,
                  "physical_egg_id": f"physical-camera-20261018:{args.egg_id}",
                  "capture_session_id": "physical-multiangle-20261019", "original_record_sha256": hashlib.sha256(
                      (ROOT / "output/physical-pilot-20261018" / f"{args.egg_id}.json").read_bytes()).hexdigest(),
                  "label_authority": original["label_authority"], "label_reference": "Original numbered egg cohort; not an independently verified current age",
                  "model_used_for_label": False, "capture_protocol": "three-paused-views-v1",
                  "rotation": "Approximately 120 degrees of commanded motor steps between views; no position encoder",
                  "test_status": "closed_original_pilot_test" if partition == "test" else None, "views": records}
        with (target / "record.json").open("x", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2)
    finally:
        if camera is not None:
            camera.close()
        if spinner is not None:
            spinner.close()
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "ml"))
    from balut_ml.camera_angles import build_dataset
    audit = build_dataset(partial=True)
    print(json.dumps({"egg": args.egg_id, "partition": partition, "saved_views": len(views), "holder_resumed": True,
                      "dataset_eggs": audit["captured_eggs"], "dataset_new_views": audit["new_views"]}), flush=True)


if __name__ == "__main__":
    main()
