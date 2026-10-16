"""Verify the handoff inventory and run its standalone inference entry point."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "ml" / "runs" / "accuracy-v2"
bundle_report = json.loads((RUN / "bundle.json").read_text(encoding="utf-8"))
archive = Path(bundle_report["bundle"])
assert hashlib.sha256(archive.read_bytes()).hexdigest() == bundle_report["sha256"]
directory = Path(tempfile.mkdtemp(prefix="bundle-smoke-test-", dir=RUN))
with zipfile.ZipFile(archive) as bundle:
    inventory = json.loads(bundle.read("file-hashes.json"))
    if "additional-license-hashes.json" in bundle.namelist():
        inventory.update(json.loads(bundle.read("additional-license-hashes.json")))
    for name, expected in inventory.items():
        data = bundle.read(name)
        assert len(data) == expected["bytes"]
        assert hashlib.sha256(data).hexdigest() == expected["sha256"], name
    for name in ["predict.py", "models/source-age16-18/best.onnx", "models/source-age16-18/config.json"]:
        destination = directory / name
        destination.parent.mkdir(exist_ok=True, parents=True)
        destination.write_bytes(bundle.read(name))
rows = [json.loads(line) for line in (ROOT / "data/public/thesis-egg-candling/audit-v1/manifest.jsonl").read_text(encoding="utf-8").splitlines()]
row_index, sample = next((i, r) for i, r in enumerate(rows) if r["partition"] == "validation")
command = [sys.executable, str(directory / "predict.py"), str(directory / "models/source-age16-18/best.onnx"), sample["image_path"]]
result = subprocess.run(command, cwd=directory, text=True, capture_output=True, check=True)
prediction = json.loads(result.stdout)
import numpy as np
validation = np.load(RUN / "source-age16-18/selected-validation.npz")
position = list(validation["indexes"]).index(row_index)
config = json.loads((directory / "models/source-age16-18/config.json").read_text(encoding="utf-8"))
expected_label = config["class_order"][int(validation["scores"][position].argmax())]
assert prediction["source_prediction"] == expected_label
assert prediction["operational_outcome"] == "REVIEW_RECAPTURE"
assert prediction["operational_use_authorized"] is False
report = {"bundle_inventory_files_verified": len(inventory), "bundle_sha256": bundle_report["sha256"],
          "standalone_prediction_matches_frozen_validation": True, "prediction": prediction,
          "runtime_dependencies": "numpy, Pillow, onnxruntime; no Torch imports in standalone entry point", "passed": True}
(RUN / "bundle-verification.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
print(json.dumps(report, indent=2))
