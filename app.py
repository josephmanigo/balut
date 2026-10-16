"""Vercel's FastAPI entrypoint; secrets stay in server environment variables."""
import os
import sys
import secrets
from pathlib import Path

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "apps/edge_api"))
# Cloud mode rejects local admin credentials; no operator token needs to be configured.
os.environ.setdefault("BALUT_LOCAL_ADMIN_TOKEN", secrets.token_urlsafe(48))
os.environ.update({"BALUT_ENV": "production", "BALUT_ALLOW_SIMULATOR": "false", "BALUT_CORS_ORIGINS": "",
                   "BALUT_DATABASE_PATH": "/tmp/balut/balut.db", "BALUT_EVIDENCE_PATH": "/tmp/balut/evidence"})

from balut_api.config import Settings
from balut_api.main import create_app

registry = root / "deployment/releases/automatic-recapture-20260912/registry.json"
app = create_app(Settings(
    environment="production", database_path=Path("/tmp/balut/balut.db"), evidence_path=Path("/tmp/balut/evidence"),
    local_admin_token=os.environ["BALUT_LOCAL_ADMIN_TOKEN"], device_shared_secret=os.environ["BALUT_DEVICE_SHARED_SECRET"],
    allow_simulator=False, cors_origins=(), model_registry_path=registry,
    model_registry_sha256=(registry.parent / "registry.sha256").read_text().split()[0],
    web_dist_path=root / "apps/web/dist",
    cloud_origin=os.getenv("BALUT_CLOUD_ORIGIN") or "https://" + os.environ["VERCEL_PROJECT_PRODUCTION_URL"], serverless=True,
    max_request_bytes=160 * 1024, supabase_url=os.environ["SUPABASE_URL"], supabase_secret_key=os.environ["SUPABASE_SECRET_KEY"],
))
