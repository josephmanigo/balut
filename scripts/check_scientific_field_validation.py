"""Synthetic software check only. Never opens camera or spinner ports."""
from contextlib import redirect_stdout
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "scripts"))
import collect_scientific_field_scan as collector
import camera_usb_bridge
import spinner_control
from balut_api.model_service import active_registry

def forbidden():
    raise AssertionError("Validation must never open hardware")

camera_usb_bridge.open_camera = forbidden
spinner_control.open_spinner = forbidden
(root / "tmp/scientific-artifacts").mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix="scientific-validation-", dir=root / "tmp/scientific-artifacts") as temporary:
    folder = Path(temporary)
    reference = folder / "SYNTHETIC-REFERENCE.txt"
    reference.write_text("Software fixture, not a real egg or biological evidence")
    rows = []
    for label in collector.CLASSES:
        for i in range(30):
            rows.append(dict(slot=f"{label}-{i}", egg_id=f"fixture-{label}-{i}", reference_class=label,
                             batch_id=f"fixture-batch-{i//10}", assessor="synthetic-test", reference_file=str(reference),
                             reference_method="SYNTHETIC_SOFTWARE_TEST", unseen_egg="YES", independent_reference="YES",
                             incubation_start_utc="2026-10-01T00:00:00+00:00", repeats="10" if i in (0,10,20) else "1"))
    registration = folder / "synthetic.csv"
    with registration.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    conditions = folder / "synthetic-conditions.json"
    conditions.write_text(json.dumps({"registry_sha256": collector.sha(active_registry(root)),
        **dict.fromkeys(("lighting", "position", "ambient_conditions", "operator", "camera_settings_policy"), "SYNTHETIC_SOFTWARE_TEST")}))
    output = folder / "must-not-exist"
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        collector.main(SimpleNamespace(registration=registration, conditions=conditions, slot=rows[0]["slot"], output=output, validate_only=True))
    value = json.loads(buffer.getvalue()); plan = value["plan"]
    assert value["registration_valid"] and not value["hardware_opened"] and not output.exists()
    for key, source in [("inference_sha256", "apps/edge_api/balut_api/model_service.py"),
                        ("quality_gates_sha256", "apps/edge_api/balut_api/selective_gate.py"),
                        ("measurement_code_sha256", "ml/balut_ml/scientific_metrics.py")]:
        assert plan[key] == collector.sha(root / source)
    assert plan["aggregation_functions"] == "view_consensus and combine_views in the hashed model_service.py"
    assert set(plan["runtime_versions"]) == {"numpy", "onnxruntime", "Pillow", "pyserial"}
    report = {"scope": "SYNTHETIC_SOFTWARE_VALIDATION_ONLY", "planned_fixture_rows": 90,
              "hardware_opened": False, "study_output_created": False, "code_and_runtime_lock_verified": True,
              "collector_sha256": collector.sha(root / "scripts/collect_scientific_field_scan.py"),
              "locked_source_hashes": {key: plan[key] for key in plan if key.endswith("_sha256") and key not in ("registration_sha256", "conditions_sha256")},
              "runtime_versions": plan["runtime_versions"], "physical_measurements_collected": 0}
    target = root / "output/model-results/EggGrade-IoT-Scientific-Defense-20261019/field-validation-self-check.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
