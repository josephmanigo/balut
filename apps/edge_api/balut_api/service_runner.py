"""Start the Windows service on loopback, or an explicitly configured HTTPS LAN address."""
import argparse
import json
import logging
import logging.handlers
import os
from pathlib import Path
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text(encoding="utf-8-sig"))
    required = ["database_path", "evidence_path", "model_registry_path", "model_registry_sha256", "web_dist_path", "log_path", "local_admin_token", "device_shared_secret", "port"]
    if any(key not in profile for key in required):
        raise SystemExit("Deployment profile is incomplete")
    for key in ["database_path", "evidence_path", "model_registry_path", "web_dist_path", "log_path"]:
        if not Path(profile[key]).is_absolute():
            raise SystemExit("Deployment paths must be absolute")
    os.environ.update({"BALUT_ENV": "production", "BALUT_ALLOW_SIMULATOR": "false", "BALUT_CORS_ORIGINS": "",
                       "BALUT_DATABASE_PATH": profile["database_path"], "BALUT_EVIDENCE_PATH": profile["evidence_path"],
                       "BALUT_MODEL_REGISTRY": profile["model_registry_path"], "BALUT_MODEL_REGISTRY_SHA256": profile["model_registry_sha256"],
                       "BALUT_WEB_DIST": profile["web_dist_path"], "BALUT_LOCAL_ADMIN_TOKEN": profile["local_admin_token"],
                       "BALUT_DEVICE_SHARED_SECRET": profile["device_shared_secret"],
                       "BALUT_HTTPS_ORIGIN": profile.get("https_origin", "")})
    host, tls = "127.0.0.1", {}
    if profile.get("https_origin"):
        from .config import Settings
        Settings.from_env().validate()
        origin = urlsplit(profile["https_origin"])
        if origin.port != int(profile["port"]):
            raise SystemExit("HTTPS origin port does not match the serving port")
        for key in ("ssl_certfile", "ssl_keyfile"):
            path = Path(profile.get(key, ""))
            if not path.is_absolute() or not path.is_file():
                raise SystemExit(f"HTTPS requires an existing absolute {key}")
            tls[key] = str(path)
        host = origin.hostname
    log_path = Path(profile["log_path"])
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(log_path, maxBytes=5*1024*1024, backupCount=5, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler()],
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    import uvicorn
    uvicorn.run("balut_api.main:app", host=host, port=int(profile["port"]), workers=1, reload=False,
                proxy_headers=False, access_log=False, log_config=None, limit_concurrency=16,
                timeout_keep_alive=5, timeout_graceful_shutdown=30, **tls)


if __name__ == "__main__":
    main()
