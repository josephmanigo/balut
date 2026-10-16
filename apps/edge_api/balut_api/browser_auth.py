"""One local account with persistent password hashing and revocable sessions."""
import asyncio
import hashlib
import hmac
import re
import secrets
import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

COOKIE_NAME = "balut_session"
SESSION_SECONDS = 8 * 60 * 60


class LoginInput(BaseModel):
    username: str = Field(max_length=80)
    password: str = Field(max_length=128)


class RegistrationInput(LoginInput):
    password: str = Field(min_length=12, max_length=128)
    confirm_password: str = Field(alias="confirmPassword", min_length=12, max_length=128)


def password_digest(password: str, salt: bytes) -> str:
    # OWASP scrypt baseline; run off the event loop, one hash operation at a time.
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**17, r=8, p=1,
                          maxmem=256 * 1024 * 1024, dklen=32).hex()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt$131072$8$1${salt.hex()}${password_digest(password, salt)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, cost, block, parallel, salt, digest = stored.split("$")
        if (algorithm, cost, block, parallel) != ("scrypt", "131072", "8", "1"):
            return False
        if len(salt) != 32 or len(digest) != 64:
            return False
        return hmac.compare_digest(password_digest(password, bytes.fromhex(salt)), digest)
    except ValueError:
        return False


class BrowserSessions:
    def __init__(self):
        self.tokens: dict[str, tuple[float, str]] = {}
        self.failures: list[float] = []

    def authenticated(self, request: Request) -> bool:
        return self.username(request) is not None

    def username(self, request: Request) -> str | None:
        expires, username = self.tokens.get(request.cookies.get(COOKIE_NAME, ""), (0, ""))
        return username if expires > time.monotonic() else None

    def issue(self, username: str) -> str:
        now = time.monotonic()
        self.tokens = {token: session for token, session in self.tokens.items() if session[0] > now}
        if len(self.tokens) >= 64:
            del self.tokens[next(iter(self.tokens))]
        token = secrets.token_urlsafe(32)
        self.tokens[token] = (now + SESSION_SECONDS, username)
        return token


def browser_auth_router(database, sessions: BrowserSessions) -> APIRouter:
    router = APIRouter(prefix="/api/v1/auth")
    password_gate = asyncio.Lock()

    def signed_in(response: Response, username: str, request: Request):
        response.set_cookie(COOKIE_NAME, sessions.issue(username), httponly=True, secure=request.url.scheme == "https", samesite="strict", path="/")
        return {"authenticated": True, "username": username, "setupRequired": False}

    def check_attempts():
        now = time.monotonic()
        sessions.failures = [stamp for stamp in sessions.failures if now - stamp < 60]
        if len(sessions.failures) >= 10:
            raise HTTPException(429, "Too many sign-in attempts. Wait one minute and try again.", headers={"Retry-After": "60"})
        if password_gate.locked():
            raise HTTPException(429, "Sign-in is busy. Try again shortly.", headers={"Retry-After": "1"})

    @router.get("/session")
    def session(request: Request):
        return {"authenticated": sessions.authenticated(request), "username": sessions.username(request),
                "setupRequired": database.get_operator_account() is None,
                **({"cloudDemo": True} if request.app.state.settings.cloud_origin else {})}

    @router.post("/register", status_code=201)
    async def register(credentials: RegistrationInput, response: Response, request: Request):
        username = credentials.username.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,31}", username):
            raise HTTPException(400, "Use 3–32 letters, numbers, dots, underscores or hyphens for your username.")
        if credentials.password != credentials.confirm_password:
            raise HTTPException(400, "Passwords do not match.")
        if database.get_operator_account() is not None:
            raise HTTPException(409, "This laptop already has an account. Sign in instead.")
        check_attempts()
        async with password_gate:
            hashed = await run_in_threadpool(hash_password, credentials.password)
            if not database.create_operator_account(username, hashed):
                raise HTTPException(409, "This laptop already has an account. Sign in instead.")
        sessions.tokens.clear()
        return signed_in(response, username, request)

    @router.post("/login")
    async def login(credentials: LoginInput, response: Response, request: Request):
        check_attempts()
        account = database.get_operator_account()
        async with password_gate:
            valid_password = bool(account) and await run_in_threadpool(verify_password, credentials.password, account["password_hash"])
        if not account or credentials.username.strip().lower() != account["username"] or not valid_password:
            sessions.failures.append(time.monotonic())
            raise HTTPException(401, "Username or password is incorrect. Try again.")
        return signed_in(response, account["username"], request)

    @router.post("/logout")
    async def logout(request: Request, response: Response):
        sessions.tokens.pop(request.cookies.get(COOKIE_NAME, ""), None)
        response.delete_cookie(COOKIE_NAME, httponly=True, secure=request.url.scheme == "https", samesite="strict", path="/")
        return {"authenticated": False}

    return router
