from contextlib import contextmanager
import hashlib
import json

import pytest

from scripts import capture_camera_sweep as sweep


def test_commanded_angle_bins_cover_a_full_turn_and_survive_counter_wrap():
    assert {sweep.angle_bin((index*2048+49)//50, 0) for index in range(50)} == set(range(50))
    assert sweep.angle_bin(10, 0xffffffff-9) == sweep.angle_bin(20, 0)
    with pytest.raises(ValueError): sweep.angle_bin(True, 0)


def test_capture_retries_bad_frames_skips_used_angles_and_checkpoints_each_photo(tmp_path, monkeypatch):
    monkeypatch.setattr(sweep.time, "sleep", lambda _: None)
    monkeypatch.setattr(sweep, "TARGET", 3)
    # Use the same hardware counter contract while keeping the test to three saved images.
    monkeypatch.setattr(sweep, "STEPS_PER_REVOLUTION", 12)
    class Motor:
        held = False
        steps = -4
        last_steps = 0
        def command(self, verb):
            if verb == "STATUS" and not self.held:
                self.steps += 4
                self.last_steps = self.steps
            return ("HELD" if self.held else "RUNNING"), self.last_steps
        @contextmanager
        def capture_hold(self):
            self.held = True
            try: yield
            finally: self.held = False
    motor = Motor()
    reads = [0]
    def read(_):
        assert motor.held
        reads[0] += 1
        if reads[0] == 1: raise ValueError("CRC mismatch")
        return f"image-{motor.steps}".encode()
    monkeypatch.setattr(sweep, "read_fresh_snapshot", read)
    monkeypatch.setattr(sweep, "prepared_frame", lambda body, _: (body, "pixel-"+hashlib.sha256(body).hexdigest(), {}))
    record = {"egg_id": "16-1", "views": [], "angle_origin_steps": None}
    sweep.collect("camera", motor, tmp_path, record, {}, set())
    saved = json.loads((tmp_path / "record.json").read_text())
    assert saved["completed"] and len(saved["views"]) == 3 and not motor.held
    assert {v["angle_bin"] for v in saved["views"]} == {0, 1, 2}
    assert len(list(tmp_path.glob("view-*.jpg"))) == 3 and reads[0] == 4


def test_durable_view_cannot_overwrite_an_existing_image(tmp_path):
    (tmp_path / "view-1.jpg").write_bytes(b"preserved")
    record = {"views": []}
    with pytest.raises(FileExistsError): sweep.save_view(tmp_path, record, b"new", {})
    assert (tmp_path / "view-1.jpg").read_bytes() == b"preserved" and not record["views"]


def test_camera_disconnect_preserves_the_last_checkpoint_and_releases_the_hold(tmp_path, monkeypatch):
    monkeypatch.setattr(sweep.time, "sleep", lambda _: None)
    class Motor:
        held, steps = False, 0
        def command(self, verb):
            if not self.held: self.steps += 50
            return ("HELD" if self.held else "RUNNING"), self.steps
        @contextmanager
        def capture_hold(self):
            self.held = True
            try: yield
            finally: self.held = False
    motor = Motor()
    reads = [0]
    def read(_):
        reads[0] += 1
        if reads[0] == 2: raise OSError("camera disconnected")
        return b"first-view"
    monkeypatch.setattr(sweep, "read_fresh_snapshot", read)
    monkeypatch.setattr(sweep, "prepared_frame", lambda body, _: (body, "pixels", {}))
    record = {"egg_id": "16-1", "views": [], "angle_origin_steps": None}
    with pytest.raises(OSError, match="disconnected"):
        sweep.collect("camera", motor, tmp_path, record, {}, set())
    saved = json.loads((tmp_path / "record.json").read_text())
    assert len(saved["views"]) == 1 and not motor.held
    assert (tmp_path / "view-1.jpg").read_bytes() == b"first-view"
