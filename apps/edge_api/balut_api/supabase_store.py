"""Server-only shared account, prediction history and private evidence storage."""
import hashlib
from uuid import uuid4

import httpx

from .database import Database, utc_now
from .evidence import EvidenceStore


class CloudStorageError(RuntimeError):
    pass


class Supabase:
    def __init__(self, url, secret):
        self.url = url
        self.headers = {"apikey": secret}
        if not secret.startswith("sb_secret_"):
            self.headers["Authorization"] = "Bearer " + secret
        self.client = httpx.Client(timeout=20, follow_redirects=False,
                                   limits=httpx.Limits(keepalive_expiry=30))

    def close(self):
        self.client.close()

    def request(self, method, path, *, allowed=(), **kwargs):
        headers = {**self.headers, **kwargs.pop("headers", {})}
        try:
            response = self.client.request(method, self.url + path, headers=headers, **kwargs)
        except httpx.HTTPError:
            raise CloudStorageError("Shared storage unavailable; retry when connected") from None
        if response.is_success or response.status_code in allowed:
            return response
        if response.status_code == 409 and path.startswith("/rest/v1/rpc/"):
            raise ValueError("idempotency key or prediction identity conflicts with an earlier record")
        # Provider errors can contain private data; never return their body or credentials.
        raise CloudStorageError("Shared storage rejected the request; no result accepted")

    def check(self):
        self.request("GET", "/rest/v1/balut_predictions", params={"select": "id", "limit": "1"})
        bucket = self.request("GET", "/storage/v1/bucket/balut-evidence").json()
        if bucket.get("public") is not False:
            raise CloudStorageError("Evidence bucket must be private")


class SupabaseDatabase(Database):
    # Camera calibration and the separate research simulator remain local to each backend.
    def __init__(self, path, cloud):
        super().__init__(path)
        self.cloud = cloud

    def initialize(self):
        super().initialize()
        self.cloud.check()

    def get_operator_account(self, username=None):
        rows = self.cloud.request("GET", "/rest/v1/balut_account", params={
            **({"username": "eq." + username} if username is not None else {"order": "id.asc"}),
            "select": "username,password_hash", "limit": "1"}).json()
        return rows[0] if rows else None

    def create_operator_account(self, username, password_hash):
        rows = self.cloud.request("POST", "/rest/v1/balut_account", params={"on_conflict": "username"},
            headers={"Prefer": "resolution=ignore-duplicates,return=representation"},
            json={"username": username, "password_hash": password_hash}).json()
        return bool(rows)

    def prediction_replay(self, actor_id, key, request_hash):
        rows = self.cloud.request("GET", "/rest/v1/balut_predictions", params={
            "actor_id": "eq." + actor_id, "request_key": "eq." + key,
            "select": "request_hash,response", "limit": "1"}).json()
        if not rows:
            return None
        if rows[0]["request_hash"] != request_hash:
            raise ValueError("idempotency key was reused with a different request")
        return rows[0]["response"]

    def import_prediction(self, response, actor_id, key, request_hash):
        return self.cloud.request("POST", "/rest/v1/rpc/balut_record_prediction", json={
            "p_response": response, "p_actor": actor_id, "p_key": key, "p_hash": request_hash}).json()

    def record_prediction(self, result, image_sha256, actor_id, key, request_hash):
        response = {**result, "predictionId": str(uuid4()), "imageSha256": image_sha256, "createdAt": utc_now()}
        return self.import_prediction(response, actor_id, key, request_hash)

    def get_prediction(self, prediction_id, owner=None):
        rows = self.cloud.request("GET", "/rest/v1/balut_predictions", params={
            **({"owner_username": "eq." + owner} if owner is not None else {}),
            "id": "eq." + prediction_id, "select": "response", "limit": "1"}).json()
        return rows[0]["response"] if rows else None

    def list_predictions(self, limit=50, owner=None):
        rows = self.cloud.request("GET", "/rest/v1/balut_predictions", params={
            **({"owner_username": "eq." + owner} if owner is not None else {}),
            "select": "response", "order": "created_at.desc,id.desc", "limit": str(limit)}).json()
        return [row["response"] for row in rows]


class SupabaseEvidence(EvidenceStore):
    def __init__(self, root, cloud):
        super().__init__(root)
        self.cloud = cloud

    def object_path(self, digest):
        self.path_for(digest)  # Reuse the hash/path validation before constructing a remote path.
        return "/storage/v1/object/balut-evidence/" + digest[:2] + "/" + digest + ".jpg"

    def download_path(self, digest):
        return self.object_path(digest).replace("/object/", "/object/authenticated/", 1)

    def contains(self, digest):
        if super().contains(digest):
            return True
        response = self.cloud.request("GET", self.download_path(digest), allowed=(400, 404))
        if response.status_code in (400, 404):
            # Supabase uses 400 with NoSuchKey for some missing-object responses.
            if response.status_code == 404 or response.json().get("error") in ("not_found", "NoSuchKey"):
                return False
            raise CloudStorageError("Evidence could not be retrieved")
        super().store_jpeg(response.content, digest)
        return True

    def store_jpeg(self, body, declared_sha256):
        stored = super().store_jpeg(body, declared_sha256)
        response = self.cloud.request("POST", self.object_path(stored.sha256), content=body,
            headers={"Content-Type": "image/jpeg", "x-upsert": "false"}, allowed=(400, 409))
        if response.status_code in (400, 409):
            # A timed-out upload may have succeeded; verify bytes before accepting a duplicate.
            existing = self.cloud.request("GET", self.download_path(stored.sha256))
            if hashlib.sha256(existing.content).hexdigest() != stored.sha256:
                raise CloudStorageError("Stored evidence checksum does not match")
        return stored
