"""Bound incoming bodies and protect the loopback production service."""
import asyncio
import logging
import time
import re
from uuid import uuid4

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .browser_auth import COOKIE_NAME
from .security import is_local_address, valid_operator_request
from .supabase_store import CloudStorageError

logger = logging.getLogger("balut.requests")


class HttpGuard:
    def __init__(self, app, settings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        # Cloud hosting terminates TLS before forwarding; use the configured origin for cookie security.
        if self.settings.cloud_origin:
            scope = {**scope, "scheme": "https"}
        request = Request(scope)
        request_id = uuid4().hex
        started = time.monotonic()
        status = 500

        async def traced_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).extend([
                    (b"x-request-id", request_id.encode()), (b"x-content-type-options", b"nosniff"),
                    (b"cache-control", b"no-store"), (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"),
                    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), serial=(self)"),
                    (b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"),
                ])
                if self.settings.cloud_origin:
                    message["headers"].append((b"strict-transport-security", b"max-age=31536000"))
            await send(message)

        async def reject(code, detail, headers=None):
            await JSONResponse({"detail": detail}, status_code=code, headers=headers)(scope, receive, traced_send)

        try:
            production = self.settings.environment == "production"
            if production:
                if self.settings.cloud_origin:
                    if str(request.base_url).rstrip("/") != self.settings.cloud_origin:
                        return await reject(400, "Use the configured cloud address")
                    cloud_routes = {"/", "/health", "/ready", "/api/v1/models", "/api/v1/model-predictions",
                                    "/api/v1/auth/session", "/api/v1/auth/login", "/api/v1/auth/logout",
                                    "/api/v1/box/status", "/api/v1/box/connect", "/api/v1/box/reference", "/api/v1/box/frame",
                                    "/api/v1/box/enabled", "/api/v1/device/box/frame"}
                    if request.url.path not in cloud_routes and not request.url.path.startswith("/assets/") and not re.fullmatch(r"/api/v1/model-predictions/records/[a-z0-9-]{1,80}", request.url.path):
                        return await reject(404, "Route unavailable")
                elif self.settings.https_origin:
                    if str(request.base_url).rstrip("/") != self.settings.https_origin:
                        return await reject(400, "Use the configured local HTTPS address")
                    if not is_local_address(request.client.host if request.client else None):
                        return await reject(403, "This workspace is available on the local network only")
                elif request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
                    return await reject(400, "This deployment accepts loopback hosts only")
            auth_route = request.url.path.startswith("/api/v1/auth/")
            if request.method not in {"GET", "HEAD", "OPTIONS"} and (auth_route or COOKIE_NAME in request.cookies):
                origin = request.headers.get("Origin")
                if request.headers.get("X-Balut-Origin") != "local" or (origin and origin != str(request.base_url).rstrip("/")):
                    return await reject(403, "Sign in from the local Balut page")
                if request.headers.get("Sec-Fetch-Site") == "cross-site":
                    return await reject(403, "Cross-site requests are not accepted")
            public_page = request.method in {"GET", "HEAD"} and (
                request.url.path in {"/", "/health", "/ready", "/api/v1/auth/session"} or request.url.path.startswith("/assets/")
            )
            public_auth = request.method == "POST" and request.url.path in {"/api/v1/auth/register", "/api/v1/auth/login", "/api/v1/auth/logout"}
            if production and request.method != "OPTIONS" and not (public_page or public_auth):
                if not request.url.path.startswith("/api/v1/device/") and not await run_in_threadpool(valid_operator_request, request, self.settings):
                    return await reject(401, "Operator authentication required")
            if request.headers.get("Content-Encoding", "identity") != "identity":
                return await reject(415, "Compressed request bodies are not accepted")
            try:
                declared = int(request.headers.get("Content-Length", "0"))
            except ValueError:
                return await reject(400, "Invalid Content-Length")
            if declared < 0 or declared > self.settings.max_request_bytes:
                return await reject(413, "Request body is too large")
            body = bytearray()
            try:
                async with asyncio.timeout(30):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        body.extend(message.get("body", b""))
                        if len(body) > self.settings.max_request_bytes:
                            return await reject(413, "Request body is too large")
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                return await reject(408, "Request body timeout")
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            await self.app(scope, replay, traced_send)
        except CloudStorageError:
            return await reject(503, "Shared storage unavailable; retry when connected")
        finally:
            # Never log auth headers, request bodies, or arbitrary query strings.
            logger.info("request_id=%s method=%s status=%s elapsed_ms=%.1f", request_id, request.method, status, (time.monotonic()-started)*1000)
