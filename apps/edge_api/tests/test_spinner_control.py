import pytest
from scripts import spinner_control


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


def test_three_views_pause_for_each_frame_and_advance_between_them(monkeypatch):
    monkeypatch.setattr(spinner_control.time, "sleep", lambda _: None)
    class MovingPort(Port):
        def write(self, body):
            if body.startswith(b"STATUS") and self.state == "RUNNING":
                self.steps += 683
            super().write(body)
    port = MovingPort()
    captures = []
    def read(_):
        assert port.state == "HELD"
        captures.append(port.steps)
        return f"frame-{port.steps}".encode()
    monkeypatch.setattr(spinner_control, "read_fresh_snapshot", read)
    views = spinner_control.capture_views("camera", spinner_control.Spinner(port))
    assert captures == [12, 695, 1378]
    assert len(views) == 3 and port.commands.count("HOLD") == port.commands.count("RUN") == 3
    assert port.state == "RUNNING"


@pytest.mark.parametrize("drift,fail_hold", [(True, False), (False, True)])
def test_unverified_hold_rejects_capture_and_resumes(monkeypatch, drift, fail_hold):
    monkeypatch.setattr(spinner_control.time, "sleep", lambda _: None)
    port = Port(drift, fail_hold)
    with pytest.raises(ValueError):
        with spinner_control.Spinner(port).capture_hold():
            pass
    assert port.commands[-1] == "RUN" and port.state == "RUNNING"


@pytest.mark.parametrize("label,expected", [("DAY_16", "DAY_16"), ("DAY_18", "DAY_18"), ("REJECT", "REJECT"),
                                          ("UNCLASSIFIED", "UNCLASSIFIED"), ("DAY_16\nRUN", "UNCLASSIFIED"),
                                          (None, "UNCLASSIFIED"), ({}, "UNCLASSIFIED")])
def test_lcd_acknowledges_only_allowlisted_labels_without_motor_commands(label, expected):
    class DisplayPort(Port):
        def write(self, body):
            self.body = body
            super().write(body)

        def readline(self, _):
            return f"BALUT_LCD_V1 {self.nonce} READY label={expected}\n".encode()

    port = DisplayPort()
    assert spinner_control.Spinner(port).display(label)
    assert port.commands == ["LCD"] and port.body.endswith(f" {expected}\n".encode())
    assert port.state == "RUNNING" and port.steps == 12


def test_missing_lcd_does_not_change_spinner_state():
    class MissingPort(Port):
        def readline(self, _):
            return f"BALUT_LCD_V1 {self.nonce} MISSING label=OFFLINE\n".encode()

    port = MissingPort()
    assert not spinner_control.Spinner(port).display("OFFLINE")
    assert port.state == "RUNNING"
