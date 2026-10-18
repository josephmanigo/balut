import io
import http.client
import threading
import zlib
from types import SimpleNamespace
from contextlib import closing

import pytest
from PIL import Image

from scripts import camera_usb_bridge as bridge


def test_camera_adapter_is_identified_on_any_com_port():
    camera = SimpleNamespace(device="COM9", vid=0x0403, pid=0x6001, serial_number="A5069RR4A")
    other = SimpleNamespace(device="COM3", vid=0x0403, pid=0x6001, serial_number="other")
    assert bridge.find_camera_port([other, camera]) == "COM9"
    for ports in ([], [other], [camera, camera]):
        with pytest.raises(ValueError):
            bridge.find_camera_port(ports)


class CameraPort:
    def __init__(self, packet):
        self.packet = packet

    def reset_input_buffer(self):
        self.stream = io.BytesIO()

    def write(self, data):
        assert data == b"CAPTURE\n"
        self.stream = io.BytesIO(self.packet)

    def flush(self):
        pass

    def readline(self, size):
        return self.stream.readline(size)

    def read(self, size):
        return self.stream.read(min(size, 23))


def jpeg():
    output = io.BytesIO()
    Image.new("RGB", (64, 48), "gray").save(output, "JPEG")
    return output.getvalue()


def packet(body, checksum=None):
    checksum = zlib.crc32(body) if checksum is None else checksum
    return f"BALUT_JPEG {len(body)} {checksum:08x}\n".encode() + body + b"\n"


def test_usb_image_survives_boot_messages_and_fragmented_reads():
    body = jpeg()
    assert bridge.read_snapshot(CameraPort(b"booting\nBALUT_USB_READY\n" + packet(body))) == body


def test_snapshot_consumes_frame_terminator_before_requesting_another_image():
    camera = CameraPort(packet(jpeg()))
    bridge.read_snapshot(camera)
    assert camera.stream.read() == b""


def test_fresh_capture_discards_the_queued_frame():
    old = io.BytesIO()
    Image.new("RGB", (64, 48), "red").save(old, "JPEG")
    class BufferedPort(CameraPort):
        requests = 0
        def write(self, data):
            self.requests += 1
            self.packet = packet(old.getvalue() if self.requests == 1 else jpeg())
            return super().write(data)
    camera = BufferedPort(b"")
    assert bridge.read_fresh_snapshot(camera) == jpeg()
    assert camera.requests == 2


@pytest.mark.parametrize("bad", [b"BALUT_ERROR Capture failed\n", b"BALUT_JPEG 99999999 0\n", b"BALUT_JPEG 12\n", packet(jpeg(), 0), packet(b"not a jpeg")])
def test_invalid_camera_packets_are_never_returned_as_images(bad):
    with pytest.raises(ValueError):
        bridge.read_snapshot(CameraPort(bad))


def test_short_usb_transfer_is_rejected(monkeypatch):
    clock = iter(range(20))
    monkeypatch.setattr(bridge.time, "monotonic", lambda: next(clock))
    with pytest.raises(ValueError, match="Incomplete"):
        bridge.read_snapshot(CameraPort(b"BALUT_JPEG 100 0\nshort"))


@pytest.fixture
def camera_server():
    with bridge.ThreadingHTTPServer(("127.0.0.1", 0), bridge.CameraHandler) as server:
        server.camera = CameraPort(packet(jpeg()))
        server.camera_lock = threading.Lock()
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield server
        finally:
            server.shutdown()
            worker.join(timeout=2)


def test_http_snapshot_matches_serial_image_and_disables_caching(camera_server):
    with closing(http.client.HTTPConnection(*camera_server.socket.getsockname(), timeout=2)) as client:
        client.request("GET", "/capture?_balut=unique")
        response = client.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Type") == "image/jpeg"
        assert response.getheader("Cache-Control") == "no-store"
        assert response.read() == jpeg()


def test_usb_disconnect_reopens_identified_adapter_and_missing_camera_can_recover(camera_server):
    class DisconnectedPort:
        closed = False
        def reset_input_buffer(self): raise OSError("USB disconnected")
        def close(self): self.closed = True
    disconnected = DisconnectedPort()
    camera_server.camera = disconnected
    camera_server.camera_factory = lambda: CameraPort(packet(jpeg()))
    with closing(http.client.HTTPConnection(*camera_server.socket.getsockname(), timeout=2)) as client:
        client.request("GET", "/capture")
        response = client.getresponse()
        assert response.status == 200 and response.read() == jpeg()
    assert disconnected.closed
    camera_server.camera = None
    def missing(): raise ValueError("Adapter missing")
    camera_server.camera_factory = missing
    with closing(http.client.HTTPConnection(*camera_server.socket.getsockname(), timeout=2)) as client:
        client.request("GET", "/capture")
        assert client.getresponse().status == 503
    camera_server.camera_factory = lambda: CameraPort(packet(jpeg()))
    with closing(http.client.HTTPConnection(*camera_server.socket.getsockname(), timeout=2)) as client:
        client.request("GET", "/capture")
        assert client.getresponse().status == 200


@pytest.mark.parametrize("recovers", [True, False])
def test_http_retries_one_corrupt_frame_and_never_serves_bad_data(camera_server, recovers):
    class UnreliablePort(CameraPort):
        requests = 0

        def write(self, data):
            self.requests += 1
            self.packet = packet(jpeg()) if recovers and self.requests >= 2 else packet(jpeg(), 0)
            return super().write(data)

    camera_server.camera = UnreliablePort(b"")
    with closing(http.client.HTTPConnection(*camera_server.socket.getsockname(), timeout=2)) as client:
        client.request("GET", "/capture")
        response = client.getresponse()
        assert response.status == (200 if recovers else 503)
        if recovers:
            assert response.read() == jpeg()
        else:
            assert response.getheader("Content-Type") != "image/jpeg"
    assert camera_server.camera.requests == (3 if recovers else 2)


@pytest.mark.parametrize("other_client, path, expected", [(False, "/private", 404), (True, "/capture", 403)])
def test_http_bridge_rejects_other_paths_and_other_computers(camera_server, other_client, path, expected):
    if other_client:
        camera_server.server_address = ("192.168.2.2", 8767)
    with closing(http.client.HTTPConnection(*camera_server.socket.getsockname(), timeout=2)) as client:
        client.request("GET", path)
        assert client.getresponse().status == expected
    assert not hasattr(camera_server.camera, "stream")
