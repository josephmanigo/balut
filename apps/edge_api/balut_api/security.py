from __future__ import annotations

import hashlib
import hmac
import ipaddress
import time
import base64
import binascii
import re

from fastapi import HTTPException, Request, status

from .config import Settings


def is_local_address(host: str | None) -> bool:
    if host == "testclient":
        return True
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host in {"localhost"}
    return address.is_loopback or address.is_private or address.is_link_local


def valid_operator_credential(authorization: str, settings: Settings) -> bool:
    if settings.cloud_origin:
        return False
    supplied = ""
    if authorization.startswith("Bearer "):
        supplied = authorization[7:]
    elif authorization.startswith("Basic "):
        try:
            decoded = base64.b64decode(authorization[6:], validate=True).decode("utf-8")
            username, separator, password = decoded.partition(":")
            if separator and username == "operator":
                supplied = password
        except (ValueError, UnicodeError, binascii.Error):
            return False
    return bool(supplied) and hmac.compare_digest(supplied.encode(), settings.local_admin_token.encode())


def valid_operator_request(request: Request, settings: Settings) -> bool:
    sessions = getattr(request.app.state, "browser_sessions", None)
    return valid_operator_credential(request.headers.get("Authorization", ""), settings) or bool(
        sessions and sessions.authenticated(request)
    )


def require_local_operator(request: Request, settings: Settings) -> str:
    if not is_local_address(request.client.host if request.client else None):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Physical scan commands are restricted to the local device network.",
        )
    if request.headers.get("X-Balut-Origin") != "local":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing local-presence marker.",
        )
    if not valid_operator_request(request, settings):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid local operator credential.",
        )
    sessions = getattr(request.app.state, "browser_sessions", None)
    session_username = sessions.username(request) if sessions else None
    actor = session_username or request.headers.get("X-Actor-Id", "local-operator")
    if not re.fullmatch(r"[A-Za-z0-9_.:@-]{1,80}", actor):
        raise HTTPException(status_code=400, detail="Invalid actor identifier")
    return actor


def require_box_operator(request: Request, settings: Settings) -> str:
    if not settings.cloud_origin:
        return require_local_operator(request, settings)
    if request.headers.get("X-Balut-Origin") != "local" or not valid_operator_request(request, settings):
        raise HTTPException(401, "Sign in to the Balut workbench")
    return request.app.state.browser_sessions.username(request)


async def verify_device_signature(request: Request, settings: Settings) -> str:
    timestamp = request.headers.get("X-Device-Timestamp", "")
    signature = request.headers.get("X-Device-Signature", "")
    device_id = request.headers.get("X-Device-Id", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,80}", device_id):
        raise HTTPException(status_code=401, detail="Invalid device identity")
    try:
        timestamp_number = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid device timestamp") from exc
    if abs(int(time.time()) - timestamp_number) > 300:
        raise HTTPException(status_code=401, detail="Expired device request")
    body = await request.body()
    message = timestamp.encode() + b"." + device_id.encode() + b"." + body
    version = request.headers.get("X-Device-Signature-Version", "1")
    if version == "2":
        # Bind replay identity, exact route, query, content type and image hash.
        prefix = "\n".join(["BALUT-HMAC-V2", request.method, request.url.path, request.url.query,
                            request.headers.get("Idempotency-Key", ""),
                            request.headers.get("Content-Type", ""), request.headers.get("X-Image-SHA256", "")])
        message = prefix.encode() + b"\n" + message
    elif version != "1" or settings.environment == "production":
        raise HTTPException(status_code=401, detail="Device signature version 2 is required")
    expected = hmac.new(
        settings.device_shared_secret.encode(), message, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid device signature")
    return device_id


def require_idempotency_key(request: Request) -> str:
    value = request.headers.get("Idempotency-Key", "").strip()
    if len(value) < 8 or len(value) > 120:
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key must contain between 8 and 120 characters.",
        )
    return value
