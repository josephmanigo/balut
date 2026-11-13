import pytest

from scripts.capture_emeet_egg import sha, write
from scripts.emeet_physical_metrics import count_attempts, load_physical_study
from scripts.repeat_emeet_candidate import run_repeats


def test_physical_protocol_counts_all_ten_when_camera_is_unavailable(tmp_path, monkeypatch):
    from scripts import repeat_emeet_candidate as repeat
    dataset, study = tmp_path / "dataset", tmp_path / "study"
    folder = dataset / "captures/D18-09/test"
    folder.mkdir(parents=True)
    study.mkdir()
    plan = {"eggs": {"D18-09": {"partition": "test", "label": "DAY_18"}}, "camera": "software-test-only"}
    write(dataset / "collection-plan.json", plan)
    artifact = tmp_path / "software-test-only"
    artifact.write_text("dummy")
    write(dataset / "candidate-lock.json", {"schema_version": 1, "run": str(tmp_path),
          "collection_plan_sha256": sha(dataset / "collection-plan.json"), "artifacts": [{"path": str(artifact), "sha256": sha(artifact)}]})
    write(folder / "record.json", {"status":"complete"})
    write(study / "protocol.json", {"candidate_lock_sha256":sha(dataset / "candidate-lock.json"), "selected_eggs":["D18-09"],
          "attempts_per_egg":10, "count_all_scheduled_attempts":True, "imported_original_physical_records":[], "scope":"unit test"})
    monkeypatch.setattr(repeat, "finish", lambda *args: {"physical_egg_id":"dataset:D18-09","source_label":"DAY_18"})
    monkeypatch.setattr(repeat, "load_engine", lambda *args: None)
    def unavailable(*args, **kwargs):
        raise OSError("simulated disconnected camera")
    monkeypatch.setattr(repeat.subprocess, "run", unavailable)
    run_repeats(dataset, "D18-09", study)
    result = load_physical_study(study, dataset)
    assert result["repeated_attempts"]["acquisition_failures"] == 10
    assert result["primary_first_attempt_per_egg"]["attempts"] == 1
    assert result["repeated_attempts"]["accuracy"] == 0


def test_count_first_scans_separately_and_keep_failed_and_unclassified_attempts():
    def attempt(label):
        return {"result": None if label == "FAILED" else {"sourcePrediction": label}}

    records = [{"truth": "DAY_16", "attempts": [attempt(x) for x in ["DAY_16", "REJECT", None, "FAILED"]]},
               {"truth": "DAY_18", "attempts": [attempt(x) for x in ["DAY_16", "DAY_18"]]}]
    all_scans, first = count_attempts(records), count_attempts(records, first_only=True)
    assert first["accuracy"] == .5 and first["attempts"] == 2
    assert all_scans["correct"] == 2 and all_scans["attempts"] == 6
    assert all_scans["wrong_classified"] == 2 and all_scans["unclassified"] == all_scans["acquisition_failures"] == 1
    assert all_scans["accuracy_among_classified"] == .5
    assert [r["f1"] for r in all_scans["per_class"][:2]] == pytest.approx([1 / 3, 2 / 3])
    assert all_scans["per_class"][2]["f1"] is None and all_scans["per_class"][2]["FP"] == 1
    assert all_scans["macro_f1_represented_classes"] == pytest.approx(.5)


def test_changed_protocol_wrong_truth_and_training_eggs_cannot_enter_physical_testing(tmp_path):
    dataset, study = tmp_path / 'dataset', tmp_path / 'physical'
    dataset.mkdir(); study.mkdir()
    write(dataset / 'collection-plan.json', {"eggs": {"D16-17": {"partition": "test", "label": "DAY_16"},
          "D16-01": {"partition": "train", "label": "DAY_16"}}})
    artifact = dataset / 'test-only-artifact'; artifact.write_bytes(b'synthetic')
    write(dataset / 'candidate-lock.json', {"schema_version": 1, "collection_plan_sha256": sha(dataset / 'collection-plan.json'),
          "artifacts": [{"path": str(artifact), "sha256": sha(artifact)}]})
    protocol = {"candidate_lock_sha256": sha(dataset / 'candidate-lock.json'), "attempts_per_egg": 10,
                "selected_eggs": ["D16-17"], "imported_original_physical_records": [], "scope": "unit test"}
    write(study / 'protocol.json', protocol)
    with pytest.raises(ValueError, match="reserved egg"):
        run_repeats(dataset, 'D16-01', study)
    folder = study / 'D16-17'; folder.mkdir()
    record = {"egg_id": "D16-17", "physical_egg_id": "dataset:D16-17", "truth": "DAY_18",
              "candidate_lock_sha256": protocol['candidate_lock_sha256'], "physical_study_protocol_sha256": sha(study / 'protocol.json'),
              "attempts": [{"number": 1, "result": None, "elapsed_seconds": 1}]}
    write(folder / 'record.json', record)
    with pytest.raises(ValueError, match="identity"):
        load_physical_study(study, dataset)
    record['truth'] = 'DAY_16'; write(folder / 'record.json', record)
    result = load_physical_study(study, dataset)
    assert result['primary_first_attempt_per_egg']['acquisition_failures'] == 1 and result['completed_eggs'] == 0
    write(study / 'protocol.json', {**protocol, "scope": "changed"})
    with pytest.raises(ValueError, match="protocol changed"):
        load_physical_study(study, dataset)
