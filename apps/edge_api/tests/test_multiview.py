import hashlib
import io

import pytest
from fastapi.testclient import TestClient

from balut_api.main import create_app
from balut_api.model_service import combine_views, sha256_file
from test_production import registry, settings_for
from test_selective_gate import selective_registry, sharp_image


def result(label):
    return dict(modelId="test", modelReleaseId="test", registrySha256="test", modelSha256="test",
                isSimulated=True, operationalOutcome="NOT_AUTHORIZED", operationalUseAuthorized=False,
                authority="SHADOW_ONLY", limitations="Software fixture only", inferenceMs=1,
                sourcePrediction=label, recaptureRequested=label is None,
                analysisOutcome="CLASSIFIED" if label else "RECAPTURE_REQUIRED", recaptureReasons=[],
                sourceClassDecisionScores={"DAY_16": 100})


@pytest.mark.parametrize("labels,hashes,expected", [
    (["DAY_16"] * 3, ["a", "b", "c"], "DAY_16"),
    (["DAY_18", None, "DAY_18"], ["a", "b", "c"], "DAY_18"),
    (["REJECT", "REJECT", None], ["a", "b", "c"], "REJECT"),
    (["DAY_16", "DAY_16", "DAY_18"], ["a", "b", "c"], None),
    (["DAY_16", None, None], ["a", "b", "c"], None),
    ([None] * 3, ["a", "b", "c"], None),
    (["DAY_16"] * 3, ["same"] * 3, None),
])
def test_consensus_preserves_abstention_conflicts_and_distinct_evidence(labels, hashes, expected):
    combined = combine_views([result(label) for label in labels], hashes)
    assert combined["sourcePrediction"] == expected
    assert combined["recaptureRequested"] == (expected is None)
    assert "sourceClassDecisionScores" not in combined
    assert not combined["operationalUseAuthorized"] and not combined["multiView"]["anglesVerified"]
    assert len(combined["multiView"]["views"]) == 3
    if len(set(label for label in labels if label)) > 1:
        assert combined["recaptureReasons"] == ["MULTIVIEW_DISAGREEMENT"]


def test_all_three_view_evidence_and_one_result_survive_retry_and_restart(tmp_path, registry, monkeypatch):
    path = selective_registry(tmp_path, registry)
    settings = settings_for(tmp_path, model_registry_path=path, model_registry_sha256=sha256_file(path))
    bodies = []
    for quality in (80, 90, 95):
        output = io.BytesIO()
        sharp_image().save(output, "JPEG", quality=quality)
        bodies.append(output.getvalue())
    app = create_app(settings)
    with TestClient(app, base_url="http://127.0.0.1"):
        saved = app.state.box.predict(bodies, "multiview-test")
        assert saved["sourcePrediction"] == "DAY_16"
        assert len(app.state.database.list_predictions()) == 1
        assert [view["imageHash"] for view in saved["multiView"]["views"]] == [hashlib.sha256(body).hexdigest() for body in bodies]
        def no_inference(*_): raise AssertionError("Replay must use the saved result")
        monkeypatch.setattr(app.state.model_service, "predict_views", no_inference)
        assert app.state.box.predict(bodies, "multiview-test") == saved
        with pytest.raises(ValueError, match="different request"):
            app.state.box.predict(list(reversed(bodies)), "multiview-test")
    restarted = create_app(settings)
    with TestClient(restarted, base_url="http://127.0.0.1"):
        assert restarted.state.box.predict(bodies, "multiview-test") == saved
        last = restarted.state.box.evidence.path_for(hashlib.sha256(bodies[-1]).hexdigest())
        last.write_bytes(b"corrupt last view")
        with pytest.raises(OSError, match="Evidence"):
            restarted.state.box.predict(bodies, "multiview-test")
        assert len(restarted.state.database.list_predictions()) == 1


def test_failed_views_keep_actionable_quality_reasons():
    views = [result(None) for _ in range(3)]
    views[0]["recaptureReasons"] = ["IMAGE_TOO_BLURRY"]
    views[1]["recaptureReasons"] = ["IMAGE_TOO_BLURRY", "UNFAMILIAR_APPEARANCE"]
    combined = combine_views(views, ["a", "b", "c"])
    assert combined["recaptureReasons"] == ["MULTIVIEW_INSUFFICIENT_ACCEPTED_VIEWS", "IMAGE_TOO_BLURRY", "UNFAMILIAR_APPEARANCE"]
