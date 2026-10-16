"""Single-worker Render demo: website, model and authenticated USB frame ingestion."""
import os
from pathlib import Path

from .config import Settings

root = Path(__file__).resolve().parents[3]
registry = root / "deployment/releases/automatic-recapture-20260912/registry.json"
data = Path(os.getenv("BALUT_RENDER_DATA", "/tmp/balut"))
# The shared module also creates its loopback app at import; keep that initialization in writable demo storage.
os.environ.update({"BALUT_ENV": "production", "BALUT_ALLOW_SIMULATOR": "false", "BALUT_CORS_ORIGINS": "",
                   "BALUT_DATABASE_PATH": str(data / "balut.db"), "BALUT_EVIDENCE_PATH": str(data / "evidence")})
from .main import create_app

app = create_app(Settings(
    environment="production", database_path=data / "balut.db", evidence_path=data / "evidence",
    local_admin_token=os.environ["BALUT_LOCAL_ADMIN_TOKEN"], device_shared_secret=os.environ["BALUT_DEVICE_SHARED_SECRET"],
    allow_simulator=False, cors_origins=(), model_registry_path=registry,
    model_registry_sha256=(registry.parent / "registry.sha256").read_text().split()[0],
    web_dist_path=root / "apps/web/dist", cloud_origin=os.environ["RENDER_EXTERNAL_URL"],
    max_request_bytes=160 * 1024,
    supabase_url=os.getenv("SUPABASE_URL") or None,
    supabase_secret_key=os.getenv("SUPABASE_SECRET_KEY") or None,
))
