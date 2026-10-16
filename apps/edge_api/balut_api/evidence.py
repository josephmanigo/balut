from __future__ import annotations

import hashlib
import os
import tempfile
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredEvidence:
    sha256: str
    byte_size: int
    path: Path
    repeated: bool


class EvidenceStore:
    def __init__(self, root: Path, max_image_bytes: int = 10 * 1024 * 1024):
        self.root = root
        self.max_image_bytes = max_image_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, sha256: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ValueError("Invalid evidence SHA-256")
        return self.root / sha256[:2] / f"{sha256}.jpg"

    def contains(self, sha256: str) -> bool:
        path = self.path_for(sha256)
        if not path.is_file():
            return False
        return self._hash_file(path) == sha256

    def store_jpeg(self, body: bytes, declared_sha256: str) -> StoredEvidence:
        if len(body) < 4 or len(body) > self.max_image_bytes:
            raise ValueError("JPEG byte size is outside the accepted range")
        if not body.startswith(b"\xff\xd8") or not body.endswith(b"\xff\xd9"):
            raise ValueError("evidence payload does not have JPEG boundary markers")
        actual_sha256 = hashlib.sha256(body).hexdigest()
        if actual_sha256 != declared_sha256:
            raise ValueError("declared image SHA-256 does not match the uploaded bytes")
        from .model_service import decode_jpeg
        decode_jpeg(body)

        destination = self.path_for(actual_sha256)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if self._hash_file(destination) != actual_sha256:
                raise RuntimeError("content-addressed evidence path contains conflicting bytes")
            return StoredEvidence(actual_sha256, len(body), destination, True)

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix="evidence-",
                suffix=".tmp",
                dir=destination.parent,
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, destination)
            temporary_path = None
            if os.name != "nt":
                directory_handle = os.open(destination.parent, os.O_RDONLY)
                try:
                    os.fsync(directory_handle)
                finally:
                    os.close(directory_handle)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
        return StoredEvidence(actual_sha256, len(body), destination, False)

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
