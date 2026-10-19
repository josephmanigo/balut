from pathlib import Path
import csv
import sys
from types import SimpleNamespace
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from collect_scientific_field_scan import collect_attempt, score_record, registration


def test_full_score_vector_and_raw_mean_do_not_override_app_abstention():
    result = {"sourcePrediction": None, "multiView": {"views": [
        {"sourceClassDecisionScores": dict(zip(["DAY_16", "DAY_18", "UNFERTILIZED"], values))}
        for values in ([2., 1., -3.], [1., 2., -3.], [4., 1., -5.])]}}
    value = score_record(result)
    assert len(value["score_vector"]) == 9 and value["raw_scan_prediction"] == "DAY_16"
    assert result["sourcePrediction"] is None


def test_discarded_capture_is_saved_and_reader_restored(tmp_path):
    original = lambda port: b"raw sensor bytes"
    module = SimpleNamespace(read_snapshot=original)
    def capture(camera, spinner):
        module.read_snapshot(camera)
        raise ValueError("Spinner moved during capture")
    value = collect_attempt(None, None, None, tmp_path / "failed", capture=capture,
                            prepare=lambda value: value, read_module=module)
    assert value["score_vector"] is None and "Spinner moved" in value["error"]
    assert (tmp_path / "failed/sensor-frame-01.jpg").read_bytes() == b"raw sensor bytes"
    assert module.read_snapshot is original and (tmp_path / "failed/attempt.json").exists()


def test_blank_registration_is_not_accepted(tmp_path):
    source = tmp_path / "unfilled.csv"
    source.write_text("slot,egg_id,reference_class\nD16-01,,DAY_16\n")
    with pytest.raises(ValueError, match="90 new eggs"):
        registration(source)


def test_preregistration_requires_independent_repeat_batches(tmp_path):
    reference = tmp_path / "independent-reference.txt"; reference.write_text("Synthetic test fixture; not field observations")
    rows = []
    for label in ("DAY_16", "DAY_18", "UNFERTILIZED"):
        for i in range(30):
            rows.append(dict(slot=f"{label}-{i}", egg_id=f"fixture-{label}-{i}", reference_class=label,
                             batch_id=f"batch-{i//10}", assessor="fixture", reference_file=str(reference.resolve()),
                             reference_method="fixture", unseen_egg="YES", independent_reference="YES",
                             incubation_start_utc="2026-10-01T00:00:00+00:00", repeats="10" if i in (0, 10, 20) else "1"))
    source = tmp_path / "registration.csv"
    def save():
        with source.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    save()
    actual, hashes = registration(source)
    assert len(actual) == 90 and len(hashes) == 1
    rows[10]["batch_id"] = rows[0]["batch_id"]; save()
    with pytest.raises(ValueError, match="three batches"):
        registration(source)
