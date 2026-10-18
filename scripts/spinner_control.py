"""Local, bounded capture hold for the identified spinner; no cloud motion endpoint."""
from contextlib import contextmanager
import re
import time
from uuid import uuid4

MOTOR_MAC = "3c:8a:1f:09:88:8c"


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
