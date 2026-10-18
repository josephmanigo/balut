import pytest
from scripts import spinner_control
from scripts import upload_box_frames


class Port:
    def __init__(self, drift=False, fail_hold=False):
        self.commands = []
        self.state = "RUNNING"
        self.steps = 12
        self.drift, self.fail_hold = drift, fail_hold

    def reset_input_buffer(self):
        pass

    def write(self, body):
        verb, self.nonce, *_ = body.decode().split()
        self.commands.append(verb)
        if verb == "HOLD" and not self.fail_hold:
            self.state = "HELD"
        if verb == "RUN":
            self.state = "RUNNING"
        if verb == "STATUS" and self.drift:
            self.steps += 1

    def flush(self):
        pass

    def readline(self, _):
        return f"BALUT_MOTOR_V1 {self.nonce} {self.state} steps={self.steps} mac={spinner_control.MOTOR_MAC}\n".encode()


def test_capture_holds_until_camera_finishes_and_resumes(monkeypatch):
    monkeypatch.setattr(spinner_control.time, "sleep", lambda _: None)
    port = Port()
    with spinner_control.Spinner(port).capture_hold():
        assert port.state == "HELD"
    assert port.commands == ["HOLD", "STATUS", "RUN"]
    assert port.state == "RUNNING"


def test_capture_failure_still_resumes(monkeypatch):
    monkeypatch.setattr(spinner_control.time, "sleep", lambda _: None)
    port = Port()
    with pytest.raises(OSError, match="camera"):
        with spinner_control.Spinner(port).capture_hold():
            raise OSError("camera disconnected")
    assert port.commands == ["HOLD", "RUN"] and port.state == "RUNNING"


def test_connector_reads_fresh_camera_frame_while_held_and_returns_after_resume(monkeypatch):
    monkeypatch.setattr(spinner_control.time, "sleep", lambda _: None)
    port = Port()
    def read(camera):
        assert camera == "camera" and port.state == "HELD"
        return b"fresh frame"
    monkeypatch.setattr(upload_box_frames, "read_fresh_snapshot", read)
    assert upload_box_frames.read_upload_frame("camera", spinner_control.Spinner(port), True) == b"fresh frame"
    assert port.commands == ["HOLD", "STATUS", "RUN"] and port.state == "RUNNING"


def test_preview_does_not_pause_motor(monkeypatch):
    port = Port()
    monkeypatch.setattr(upload_box_frames, "read_fresh_snapshot", lambda _: b"preview")
    assert upload_box_frames.read_upload_frame("camera", spinner_control.Spinner(port), False) == b"preview"
    assert not port.commands


@pytest.mark.parametrize("drift,fail_hold", [(True, False), (False, True)])
def test_unverified_hold_rejects_capture_and_resumes(monkeypatch, drift, fail_hold):
    monkeypatch.setattr(spinner_control.time, "sleep", lambda _: None)
    port = Port(drift, fail_hold)
    with pytest.raises(ValueError):
        with spinner_control.Spinner(port).capture_hold():
            pass
    assert port.commands[-1] == "RUN" and port.state == "RUNNING"
