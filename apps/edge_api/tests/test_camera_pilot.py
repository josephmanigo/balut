import pytest
import hashlib
import json
from PIL import Image
from types import SimpleNamespace

from scripts.capture_camera_pilot import partition_for
from scripts import capture_camera_pilot


def test_capture_plan_keeps_each_egg_in_one_partition_and_preserves_reserved_eggs():
    for age in (16, 18):
        groups = {split: [i for i in range(1, 16) if partition_for(f"{age}-{i}") == (age, split)]
                  for split in ("train", "validation", "test")}
        assert groups == {"train": [1, 2, 3, 6, 7], "validation": [4, 8, 9, 10, 11], "test": [5, 12, 13, 14, 15]}
    for invalid in ("16-0", "16-16", "18-01", "20-1", "../16-1", "16-1.jpg"):
        with pytest.raises(ValueError):
            partition_for(invalid)


def test_import_records_original_bytes_and_rejects_overwrites_or_duplicate_eggs(tmp_path, monkeypatch):
    source = tmp_path / "source.jpg"
    Image.new("RGB", (600, 800), "gray").save(source, "JPEG")
    original = source.read_bytes()
    output = tmp_path / "pilot"
    monkeypatch.setattr(capture_camera_pilot, "OUTPUT", output)
    monkeypatch.setattr("sys.argv", ["capture", "16-1", "--source", str(source)])
    capture_camera_pilot.main()
    assert (output / "16-1.jpg").read_bytes() == source.read_bytes() == original
    record = json.loads((output / "16-1.json").read_text())
    assert record["sha256"] == hashlib.sha256(original).hexdigest()
    assert record["model_used_for_label"] is False and record["partition"] == "train"
    with pytest.raises(ValueError, match="already recorded"):
        capture_camera_pilot.main()
    monkeypatch.setattr("sys.argv", ["capture", "18-5", "--source", str(source)])
    with pytest.raises(ValueError, match="Identical image"):
        capture_camera_pilot.main()
    assert not (output / "18-5.jpg").exists()


def test_live_scan_import_verifies_evidence_and_rejects_multi_view(tmp_path, monkeypatch):
    from balut_api import supabase_store
    source = tmp_path / "source.jpg"
    Image.new("RGB", (600, 800), "gray").save(source, "JPEG")
    body = source.read_bytes()
    prediction_id = "00000000-0000-4000-8000-000000000001"
    prediction = {"predictionId": prediction_id, "isSimulated": False, "captureSource": "iot_box",
                  "imageSha256": hashlib.sha256(body).hexdigest(), "createdAt": "2026-10-18T15:00:00Z"}
    profile = tmp_path / "deployment/private"
    profile.mkdir(parents=True)
    (profile / "supabase.json").write_text(json.dumps({"url": "unused", "secret_key": "unused"}))
    def request(method, path, **kwargs):
        if path == "/rest/v1/balut_predictions":
            assert kwargs["params"]["id"] == f"eq.{prediction_id}"
            return SimpleNamespace(json=lambda: [{"response": prediction}])
        return SimpleNamespace(content=body)
    monkeypatch.setattr(supabase_store, "Supabase", lambda *_: SimpleNamespace(request=request))
    monkeypatch.setattr(capture_camera_pilot, "ROOT", tmp_path)
    monkeypatch.setattr(capture_camera_pilot, "OUTPUT", tmp_path / "pilot")
    monkeypatch.setattr("sys.argv", ["capture", "16-4", "--prediction", prediction_id])
    capture_camera_pilot.main()
    record = json.loads((tmp_path / "pilot/16-4.json").read_text())
    assert record["freshness"] == "live_single_frame_prediction"
    assert record["model_used_for_label"] is False
    assert record["captured_at"] == prediction["createdAt"]
    prediction["multiView"] = {"views": [1, 2, 3]}
    monkeypatch.setattr("sys.argv", ["capture", "18-4", "--prediction", prediction_id])
    with pytest.raises(ValueError, match="one real automatic"):
        capture_camera_pilot.main()
    assert not (tmp_path / "pilot/18-4.jpg").exists()
