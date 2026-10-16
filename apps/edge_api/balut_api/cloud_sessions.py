"""Opaque, revocable sessions shared across workers; only token hashes leave the server."""
import hashlib
import re
import secrets
from datetime import datetime, timezone

from .browser_auth import BrowserSessions, COOKIE_NAME


class CloudSessions(BrowserSessions):
    def __init__(self, cloud):
        self.cloud = cloud

    def username(self, request):
        if hasattr(request.state, "session_username"):
            return request.state.session_username
        token = request.cookies.get(COOKIE_NAME, "")
        username = None
        if re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
            rows = self.cloud.request("GET", "/rest/v1/balut_sessions", params={
                "token_hash": "eq." + hashlib.sha256(token.encode()).hexdigest(),
                "expires_at": "gt." + datetime.now(timezone.utc).isoformat(), "select": "username", "limit": "1"}).json()
            username = rows[0]["username"] if rows else None
        request.state.session_username = username
        return username

    def issue(self, username):
        token = secrets.token_urlsafe(32)
        self.cloud.request("POST", "/rest/v1/rpc/balut_create_session", json={
            "p_hash": hashlib.sha256(token.encode()).hexdigest(), "p_username": username})
        return token

    def revoke(self, token):
        if token:
            self.cloud.request("DELETE", "/rest/v1/balut_sessions", params={
                "token_hash": "eq." + hashlib.sha256(token.encode()).hexdigest()})

    def clear(self):
        self.cloud.request("DELETE", "/rest/v1/balut_sessions", params={"token_hash": "not.is.null"})

    def attempt(self):
        return self.cloud.request("POST", "/rest/v1/rpc/balut_login_attempt", json={}).json()

    def failed(self):
        pass  # The shared limit counts every attempt before password verification.
