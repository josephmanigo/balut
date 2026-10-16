"""Reassemble the sealed model from GitHub-uploadable chunks and verify its original hash."""
import hashlib
import json
from pathlib import Path


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def assemble(root):
    release = root / "deployment/releases/automatic-recapture-20260912"
    entry = json.loads((release / "registry.json").read_text())["models"][0]["model"]
    assert entry["path"] == "egg-grade/best.onnx"
    target = release / entry["path"]
    if target.exists():
        if sha(target) != entry["sha256"]:
            raise ValueError("Existing model differs from the sealed release")
        return
    parts = root / "deployment/model-parts"
    manifest = json.loads((parts / "manifest.json").read_text())
    if manifest["sha256"] != entry["sha256"] or not 1 <= len(manifest["parts"]) <= 8:
        raise ValueError("Invalid model chunk manifest")
    temporary = target.with_suffix(".assembling")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with temporary.open("xb") as output:
            for index, part in enumerate(manifest["parts"]):
                if part["name"] != f"best.onnx.part{index:02}":
                    raise ValueError("Invalid chunk path or order")
                source = parts / part["name"]
                if source.stat().st_size != part["bytes"] or sha(source) != part["sha256"]:
                    raise ValueError("Model chunk missing or corrupt")
                output.write(source.read_bytes())
        if temporary.stat().st_size != manifest["bytes"] or sha(temporary) != entry["sha256"]:
            raise ValueError("Reassembled model checksum mismatch")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    assemble(Path(__file__).resolve().parents[1])
    print("Sealed model hash verified.")
