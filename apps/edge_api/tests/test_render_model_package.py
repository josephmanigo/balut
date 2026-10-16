import hashlib
import json

import pytest

from scripts.assemble_render_model import assemble


@pytest.mark.parametrize("fault", [None, "corrupt", "path"])
def test_chunk_assembly_verifies_bytes_and_never_leaves_a_partial_model(tmp_path, fault):
    body = b"synthetic packaging fixture"
    digest = hashlib.sha256(body).hexdigest()
    release = tmp_path / "deployment/releases/automatic-recapture-20260912"
    parts = tmp_path / "deployment/model-parts"
    release.mkdir(parents=True)
    parts.mkdir(parents=True)
    (release / "registry.json").write_text(json.dumps({"models": [{"model": {"path": "egg-grade/best.onnx", "sha256": digest}}]}))
    (parts / "best.onnx.part00").write_bytes(body if fault != "corrupt" else b"changed")
    (parts / "manifest.json").write_text(json.dumps({"sha256": digest, "bytes": len(body), "parts": [
        {"name": "best.onnx.part00" if fault != "path" else "../escape", "bytes": len(body), "sha256": digest}]}))
    target = release / "egg-grade/best.onnx"
    if fault:
        with pytest.raises(ValueError):
            assemble(tmp_path)
        assert not target.exists()
    else:
        assemble(tmp_path)
        assert target.read_bytes() == body
        assemble(tmp_path)
    assert not target.with_suffix(".assembling").exists()
