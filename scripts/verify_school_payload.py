"""Verify an extracted school ZIP using its own relocated Python runtime."""
import hashlib
import json
from pathlib import Path
import sys

from balut_api import model_service

root = Path(sys.argv[1]).resolve()
assert Path(sys.executable).is_relative_to(root / "runtime/python")
assert Path(model_service.__file__).is_relative_to(root)
inventory = json.loads((root / "file-hashes.json").read_text())
for name, expected in inventory.items():
    path = (root / name).resolve()
    assert path.is_relative_to(root)
    with path.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == expected, name
registry = root / "deployment/releases/automatic-recapture-20260912/registry.json"
service = model_service.ModelService()
service.load(registry, (registry.parent / "registry.sha256").read_text().split()[0])
examples = json.loads(registry.read_text())["software_test_examples"]
outcomes = []
for example in examples:
    result = service.predict("egg-grade", (registry.parent / example["file"]["path"]).read_bytes())
    assert result["sourcePrediction"] == example["expected_prediction"]
    assert result["analysisOutcome"] == example["expected_analysis_outcome"]
    assert result["recaptureReasons"] == example["expected_recapture_reasons"]
    outcomes.append({"file": example["file"]["path"], "class": result["sourcePrediction"], "outcome": result["analysisOutcome"]})
service.close()
print(json.dumps({"relocatedPython": sys.version.split()[0], "inventoryFilesVerified": len(inventory),
                  "knownAnswerOutcomes": outcomes, "physicalEggValidation": False}, indent=2))
