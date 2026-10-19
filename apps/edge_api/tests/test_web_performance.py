from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from fastapi.testclient import TestClient

from balut_api.main import create_app
from balut_api.supabase_store import Supabase
from test_production import operator_headers, settings_for


def test_cloud_requests_reuse_one_connection():
    connections = set()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            connections.add(self.client_address)
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"[]")

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cloud = Supabase(f"http://127.0.0.1:{server.server_port}", "test-key")
    try:
        for _ in range(3):
            assert cloud.request("GET", "/rest/v1/test").json() == []
        assert len(connections) == 1
    finally:
        if hasattr(cloud, "close"):
            cloud.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_static_assets_are_compressed_and_cached_but_private_responses_are_not(tmp_path):
    web = tmp_path / "web"
    assets = web / "assets"
    assets.mkdir(parents=True)
    (web / "index.html").write_text("<html>workspace</html>")
    script = "const example = 123;\n" * 1000
    (assets / "index-AbCd1234.js").write_bytes(script.encode())
    settings = settings_for(tmp_path, web_dist_path=web)
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        response = client.get("/assets/index-AbCd1234.js", headers={"Accept-Encoding": "gzip"})
        assert response.text == script
        assert response.headers.get("content-encoding") == "gzip"
        assert int(response.headers["content-length"]) < len(script) / 10
        assert response.headers["cache-control"] == "public, max-age=31536000, immutable"
        cached = client.get("/assets/index-AbCd1234.js", headers={"If-None-Match": response.headers["etag"]})
        assert cached.status_code == 304
        assert cached.headers["cache-control"] == response.headers["cache-control"]
        assert client.get("/assets/missing.js").headers["cache-control"] == "no-store"
        assert client.get("/").headers["cache-control"] == "no-store"
        assert client.get("/api/v1/auth/session").headers["cache-control"] == "no-store"


def test_status_without_preview_is_small_and_keeps_the_camera_image(tmp_path):
    application = create_app(settings_for(tmp_path))
    with TestClient(application, base_url="http://127.0.0.1") as client:
        application.state.box.preview = "x" * 64 * 1024
        full = client.get("/api/v1/box/status", headers=operator_headers())
        small = client.get("/api/v1/box/status?preview=false", headers=operator_headers())
        assert full.status_code == small.status_code == 200
        assert small.json() == {**full.json(), "preview": None}
        assert len(small.content) < len(full.content) / 100
        assert application.state.box.preview == full.json()["preview"]
        assert client.get("/api/v1/box/status?preview=false").status_code == 401
