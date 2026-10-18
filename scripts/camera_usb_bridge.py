"""Expose the identified USB camera to the existing local snapshot client."""
import argparse
import ipaddress
import json
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

MAX_IMAGE = 128 * 1024
USB_BAUD = 921600


def read_snapshot(port):
    port.reset_input_buffer()
    port.write(b"CAPTURE\n")
    port.flush()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        line = port.readline(128).strip()
        if line.startswith(b"BALUT_ERROR"):
            raise ValueError("Camera capture failed")
        if line.startswith(b"BALUT_JPEG "):
            fields = line.split()
            if len(fields) != 3:
                raise ValueError("Invalid camera frame header")
            length, checksum = int(fields[1]), int(fields[2], 16)
            if not 4 < length <= MAX_IMAGE:
                raise ValueError("Camera frame exceeds the USB limit")
            break
    else:
        raise ValueError("Camera did not answer over USB")
    body = bytearray()
    while len(body) < length and time.monotonic() < deadline:
        body.extend(port.read(length - len(body)))
    if len(body) != length or zlib.crc32(body) != checksum:
        raise ValueError("Incomplete or corrupt USB image")
    if not body.startswith(b"\xff\xd8") or not body.endswith(b"\xff\xd9"):
        raise ValueError("Camera did not return a JPEG")
    return bytes(body)


def read_fresh_snapshot(port):
    # GC2145 uses one WHEN_EMPTY buffer; the first frame may predate this request.
    read_snapshot(port)
    return read_snapshot(port)


class CameraHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.client_address[0] != self.server.server_address[0]:
            return self.send_error(403)
        if urlsplit(self.path).path != "/capture":
            return self.send_error(404)
        if not self.server.camera_lock.acquire(timeout=1):
            return self.send_error(503, "USB camera busy")
        try:
            try:
                for attempt in range(2):
                    try:
                        if self.server.camera is None:
                            self.server.camera = self.server.camera_factory()
                        body = read_fresh_snapshot(self.server.camera)
                        break
                    except OSError:
                        if self.server.camera is not None:
                            self.server.camera.close()
                            self.server.camera = None
                        if attempt:
                            raise
                    except ValueError:
                        if attempt:
                            raise
                        print("USB frame rejected; retrying once.", flush=True)
            except (OSError, ValueError) as error:
                print(type(error).__name__ + ": " + str(error), flush=True)
                return self.send_error(503, "USB camera unavailable")
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.server.camera_lock.release()

    def log_message(self, *_):
        pass


def find_camera_port(ports):
    cameras = [port.device for port in ports if port.vid == 0x0403 and port.pid == 0x6001
               and port.serial_number == "A5069RR4A"]
    if len(cameras) != 1:
        raise ValueError("Connect the box camera USB cable; its identified FTDI adapter must appear exactly once")
    return cameras[0]


def open_camera():
    import serial
    from serial.tools import list_ports

    camera = serial.Serial(port=None, baudrate=USB_BAUD, timeout=0.25, write_timeout=2)
    camera.dtr = camera.rts = False
    camera.port = find_camera_port(list_ports.comports())
    camera.open()
    return camera


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loopback", action="store_true", help="Use the portable school laptop's local connection")
    args = parser.parse_args()
    host = "127.0.0.1"
    if not args.loopback:
        root = Path(__file__).resolve().parents[1]
        profile = json.loads((root / "deployment/private/windows-phone.json").read_text(encoding="utf-8-sig"))
        host = urlsplit(profile["https_origin"]).hostname
        address = ipaddress.IPv4Address(host)
        if not address.is_private or address.is_loopback:
            raise ValueError("USB bridge requires this PC's private IPv4 address")
    with ThreadingHTTPServer((host, 8767), CameraHandler) as server:
        server.camera = None
        server.camera_factory = open_camera
        server.camera_lock = threading.Lock()
        try:
            print(f"USB camera bridge ready: http://{host}:8767/capture", flush=True)
            server.serve_forever()
        finally:
            if server.camera is not None:
                server.camera.close()


if __name__ == "__main__":
    main()
