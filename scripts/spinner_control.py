"""Local, bounded capture hold for the identified spinner; no cloud motion endpoint."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import re
import time
from uuid import uuid4

if __package__:
    from .camera_usb_bridge import read_fresh_snapshot
else:
    from camera_usb_bridge import read_fresh_snapshot

MOTOR_MAC = "3c:8a:1f:09:88:8c"
STEPS_PER_VIEW = 683  # Approximately 120 degrees with the recovered 2048-step gearing.
LCD_CODES = {"UNCLASSIFIED", "DAY_16", "DAY_18", "REJECT", "WAITING", "CAPTURING", "OFFLINE", "CALIBRATE"}


def next_angle(spinner, previous_steps):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state, steps = spinner.command("STATUS")
        if state != "RUNNING":
            raise ValueError("Holder did not resume between angles")
        if ((steps - previous_steps) & 0xffffffff) >= STEPS_PER_VIEW:
            return
        time.sleep(.03)
    raise ValueError("Holder did not advance to the next angle")


def capture_views(camera, spinner):
    views = []
    for index in range(3):
        if views:
            next_angle(spinner, views[-1][1]["motor_steps"])
        for attempt in range(5):
            try:
                with spinner.capture_hold():
                    _, steps = spinner.command("STATUS")
                    print(f"Angle {index + 1}/3: holder paused; reading fresh camera frame.", flush=True)
                    body = read_fresh_snapshot(camera)
                    captured_at = datetime.now(timezone.utc).isoformat()
                break
            except ValueError as exc:
                print(f"Capture discarded: {exc}", flush=True)
                if attempt == 4:
                    raise
                time.sleep(.5)
        views.append((body, {"view_index": index + 1, "motor_steps": steps, "captured_at": captured_at,
                             "sha256": hashlib.sha256(body).hexdigest()}))
        print(f"Angle {index + 1}/3 captured; holder resumed.", flush=True)
    if len({view[1]["sha256"] for view in views}) != 3:
        raise ValueError("Duplicate camera frames; discard this capture")
    return views


class Spinner:
    def __init__(self, port):
        self.port = port

    def command(self, verb):
        nonce = uuid4().hex[:16]
        self.port.reset_input_buffer()
        self.port.write(f"{verb} {nonce}".encode() + (b" 12000\n" if verb == "HOLD" else b"\n"))
        self.port.flush()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            line = self.port.readline(180).decode("ascii", errors="replace").strip()
            match = re.fullmatch(rf"BALUT_MOTOR_V1 {nonce} (HELD|RUNNING) steps=(\d+) mac=([0-9a-f:]{{17}})", line)
            if match:
                if match[3] != MOTOR_MAC:
                    raise ValueError("Spinner controller identity changed")
                state, steps = match[1], int(match[2])
                if verb == "HOLD" and state != "HELD" or verb == "RUN" and state != "RUNNING":
                    raise ValueError("Spinner did not acknowledge its capture state")
                return state, steps
        raise ValueError("Spinner did not answer the capture protocol")

    def display(self, label):
        if not isinstance(label, str) or label not in LCD_CODES:
            label = "UNCLASSIFIED"
        nonce = uuid4().hex[:16]
        self.port.reset_input_buffer()
        self.port.write(f"LCD {nonce} {label}\n".encode())
        self.port.flush()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            line = self.port.readline(180).decode("ascii", errors="replace").strip()
            if line == f"BALUT_LCD_V1 {nonce} READY label={label}":
                return True
            if line == f"BALUT_LCD_V1 {nonce} MISSING label={label}":
                return False
        return False

    @contextmanager
    def capture_hold(self):
        try:
            _, initial_steps = self.command("HOLD")
            time.sleep(.3)
            yield
            state, final_steps = self.command("STATUS")
            if state != "HELD" or final_steps != initial_steps:
                raise ValueError("Spinner moved during capture; frame discarded")
        finally:
            self.command("RUN")

    def close(self):
        self.port.close()


def open_spinner():
    import serial
    from serial.tools import list_ports
    matches = [p.device for p in list_ports.comports() if p.vid == 0x10C4 and p.pid == 0xEA60 and p.serial_number == "0001"]
    if len(matches) != 1:
        raise ValueError("Connect the identified spinner USB adapter")
    port = serial.Serial(port=None, baudrate=115200, timeout=.1, write_timeout=1)
    port.port = matches[0]
    port.dtr = port.rts = False
    port.open()
    spinner = Spinner(port)
    try:
        spinner.command("STATUS")
    except Exception:
        spinner.close()
        raise
    return spinner
