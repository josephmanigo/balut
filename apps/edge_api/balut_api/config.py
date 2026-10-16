from __future__ import annotations

import os
import ipaddress
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    environment: str
    database_path: Path
    evidence_path: Path
    local_admin_token: str
    device_shared_secret: str
    allow_simulator: bool
    cors_origins: tuple[str, ...]
    model_registry_path: Path | None = None
    model_registry_sha256: str | None = None
    web_dist_path: Path | None = None
    max_request_bytes: int = 10 * 1024 * 1024
    https_origin: str | None = None
    cloud_origin: str | None = None
    serverless: bool = False
    supabase_url: str | None = None
    supabase_secret_key: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> "Settings":
        environment = os.getenv("BALUT_ENV", "development")
        default_token = "dev-local-token" if environment == "development" else ""
        default_device_secret = "dev-device-secret" if environment == "development" else ""
        origins = tuple(
            origin.strip()
            for origin in os.getenv(
                "BALUT_CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            ).split(",")
            if origin.strip()
        )
        return cls(
            environment=environment,
            database_path=Path(os.getenv("BALUT_DATABASE_PATH", "./data/balut.db")),
            evidence_path=Path(os.getenv("BALUT_EVIDENCE_PATH", "./data/evidence")),
            local_admin_token=os.getenv("BALUT_LOCAL_ADMIN_TOKEN", default_token),
            device_shared_secret=os.getenv(
                "BALUT_DEVICE_SHARED_SECRET", default_device_secret
            ),
            allow_simulator=_as_bool(
                os.getenv("BALUT_ALLOW_SIMULATOR"), environment == "development"
            ),
            cors_origins=origins,
            model_registry_path=Path(os.environ["BALUT_MODEL_REGISTRY"]) if os.getenv("BALUT_MODEL_REGISTRY") else None,
            model_registry_sha256=os.getenv("BALUT_MODEL_REGISTRY_SHA256"),
            web_dist_path=Path(os.environ["BALUT_WEB_DIST"]) if os.getenv("BALUT_WEB_DIST") else None,
            https_origin=os.getenv("BALUT_HTTPS_ORIGIN") or None,
            supabase_url=os.getenv("SUPABASE_URL") or None,
            supabase_secret_key=os.getenv("SUPABASE_SECRET_KEY") or None,
        )

    def validate(self) -> None:
        if bool(self.supabase_url) != bool(self.supabase_secret_key):
            raise RuntimeError("Set both SUPABASE_URL and SUPABASE_SECRET_KEY; partial cloud configuration is not allowed")
        if self.supabase_url:
            if not re.fullmatch(r"https://[a-z0-9-]+\.supabase\.co", self.supabase_url):
                raise RuntimeError("SUPABASE_URL must be the project's HTTPS supabase.co origin")
            key = self.supabase_secret_key
            if len(key) < 32 or any(character.isspace() for character in key) or not key.startswith(("sb_secret_", "eyJ")):
                raise RuntimeError("Use a server-only Supabase secret key")
        if self.cloud_origin and (self.environment != "production" or self.https_origin
                                  or not re.fullmatch(r"https://[a-z0-9-]+\.(onrender\.com|vercel\.app)", self.cloud_origin)):
            raise RuntimeError("Cloud mode requires one explicit HTTPS onrender.com or vercel.app origin in production")
        if self.serverless and not (self.cloud_origin and self.supabase_url):
            raise RuntimeError("Serverless mode requires a cloud origin and Supabase")
        if self.https_origin:
            try:
                origin = urlsplit(self.https_origin)
                address = ipaddress.IPv4Address(origin.hostname or "")
                private = any(address in ipaddress.ip_network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
                if not private or not origin.port or not 1024 <= origin.port <= 65535 or self.https_origin != f"https://{address}:{origin.port}":
                    raise ValueError()
            except ValueError as exc:
                raise RuntimeError("HTTPS origin must be https://PRIVATE_IPV4:PORT with port 1024-65535") from exc
        if self.environment not in {"development", "test", "production"}:
            raise RuntimeError("BALUT_ENV must be development, test, or production")
        if not self.local_admin_token:
            raise RuntimeError("BALUT_LOCAL_ADMIN_TOKEN is required outside development")
        if not self.device_shared_secret:
            raise RuntimeError("BALUT_DEVICE_SHARED_SECRET is required outside development")
        if self.environment == "production":
            if self.allow_simulator:
                raise RuntimeError("The simulator must be disabled in production")
            for value in (self.local_admin_token, self.device_shared_secret):
                if len(value) < 32 or value.startswith(("dev-", "test-")):
                    raise RuntimeError("Production requires distinct generated credentials of at least 32 characters")
            if self.local_admin_token == self.device_shared_secret:
                raise RuntimeError("Operator and device credentials must be different")
            if "*" in self.cors_origins:
                raise RuntimeError("Wildcard CORS is not allowed in production")
            if self.model_registry_path and not self.model_registry_sha256:
                raise RuntimeError("A production model registry must have a pinned SHA-256")
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.evidence_path.mkdir(parents=True, exist_ok=True)
