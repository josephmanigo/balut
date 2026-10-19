"""Authenticated, limited cloud entry point; the main USB/AI service stays on loopback."""
import asyncio
import hmac
import json
import re
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse, Response

ROUTES = {
    "auth/session": "GET", "auth/login": "POST", "auth/logout": "POST",
    "models": "GET", "model-predictions": "GET", "box/status": "GET",
    "box/connect": "POST", "box/reference": "POST", "box/enabled": "POST",
}
USB_ORIGIN = "http://127.0.0.1:8767"


def create_gateway(key, transport=None):
    if not re.fullmatch(r"[A-Za-z0-9_=-]{32,128}", key):
        raise ValueError("Invalid private cloud key")

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(base_url="http://127.0.0.1:8765", timeout=45,
                                     follow_redirects=False, trust_env=False, transport=transport) as client:
            app.state.client = client
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def forward(request: Request, _):
        def error(code, detail):
            return JSONResponse({"detail": detail}, status_code=code, headers={"Cache-Control": "no-store"})

        supplied = request.headers.get("X-Balut-Box-Key", "").encode()
        if not hmac.compare_digest(supplied, key.encode()):
            return error(403, "Box connector authentication required")
        route = request.url.path.removeprefix("/api/v1/")
        if request.url.path != "/api/v1/" + route or route not in ROUTES:
            return error(404, "Route unavailable")
        if request.method != ROUTES[route]:
            return error(405, "Method unavailable")
        query = list(request.query_params.multi_items())
        history_query = (route == "model-predictions" and len(query) == 1 and query[0][0] == "limit"
                         and re.fullmatch(r"[0-9]{1,3}", query[0][1]) and 1 <= int(query[0][1]) <= 100)
        preview_query = route == "box/status" and query in ([("preview", "false")], [("preview", "true")])
        if query and not (history_query or preview_query):
            return error(400, "Invalid query")
        body = bytearray()
        try:
            async with asyncio.timeout(10):
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > 16384:
                        return error(413, "Request too large")
        except TimeoutError:
            return error(408, "Request timed out")
        if request.method == "POST":
            if request.headers.get("content-type", "").split(";")[0] != "application/json":
                return error(415, "Use JSON")
            try:
                if route == "auth/logout" and not body:
                    body = bytearray(b"{}")
                value = json.loads(body)
                if not isinstance(value, dict):
                    raise ValueError()
                if route == "box/connect" and value != {"cameraUrl": USB_ORIGIN}:
                    return error(400, "Use the school USB camera address")
            except (ValueError, UnicodeError):
                return error(400, "Invalid JSON")
        elif body:
            return error(400, "GET body unavailable")
        # An explicit empty Cookie prevents HTTPX's shared jar from reusing another visitor's session.
        headers = {"X-Balut-Origin": "local", "Content-Type": "application/json", "Cookie": ""}
        cookie = request.cookies.get("balut_session", "")
        if re.fullmatch(r"[A-Za-z0-9_-]{20,100}", cookie):
            headers["Cookie"] = "balut_session=" + cookie
        try:
            async with app.state.client.stream(request.method, "/api/v1/" + route,
                                               params=query, content=bytes(body), headers=headers) as upstream:
                if not 200 <= upstream.status_code < 300 and upstream.status_code < 400:
                    return error(502, "Unexpected connector response")
                if upstream.headers.get("content-type", "").split(";")[0] != "application/json":
                    return error(502, "Unexpected connector response")
                result = bytearray()
                async for chunk in upstream.aiter_bytes():
                    result.extend(chunk)
                    if len(result) > 2 * 1024 * 1024:
                        return error(502, "Connector response too large")
                response = Response(bytes(result), status_code=upstream.status_code, media_type="application/json",
                                    headers={"Cache-Control": "no-store", "Vary": "Cookie"})
                for cookie in upstream.headers.get_list("set-cookie"):
                    response.headers.append("set-cookie", cookie + "; Secure")
                if "retry-after" in upstream.headers:
                    response.headers["Retry-After"] = upstream.headers["retry-after"]
                return response
        except httpx.HTTPError:
            return error(503, "Box offline. Start the school laptop connector.")

    return app


def main():
    import uvicorn
    root = Path(__file__).resolve().parents[3]
    profile = json.loads((root / "deployment/private/windows.json").read_text(encoding="utf-8-sig"))
    if profile.get("port") != 8765 or profile.get("https_origin"):
        raise ValueError("Cloud connector requires the school loopback profile")
    with httpx.Client(trust_env=False, timeout=5) as client:
        response = client.get("http://127.0.0.1:8765/api/v1/auth/session")
        response.raise_for_status()
        if response.json().get("setupRequired") is not False:
            raise ValueError("Create your account on the local EggGrade IoT page before starting the cloud connector")
    key = (root / "deployment/private/cloud-key.txt").read_text(encoding="utf-8-sig").strip()
    uvicorn.run(create_gateway(key), host="127.0.0.1", port=8768, proxy_headers=False, access_log=False)


if __name__ == "__main__":
    main()
