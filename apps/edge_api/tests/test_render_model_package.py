import hashlib
import json

import pytest

from scripts.assemble_render_model import assemble
from balut_api.model_service import active_registry


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


def test_active_release_pointer_selects_a_version_and_rejects_path_escape(tmp_path):
    assert active_registry(tmp_path).parent.name == "automatic-recapture-20260912"
    pointer = tmp_path / "deployment/active-release.txt"
    pointer.parent.mkdir()
    pointer.write_text("camera-trial-20261018\n")
    assert active_registry(tmp_path) == tmp_path / "deployment/releases/camera-trial-20261018/registry.json"
    pointer.write_text("../../private")
    with pytest.raises(ValueError, match="Invalid active"):
        active_registry(tmp_path)
