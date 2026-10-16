"""Verify archive contents, offline installation, and packaged model startup."""
from pathlib import Path
import argparse
import re
import hashlib
import json
import os
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="production")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.prefix):
        parser.error("Invalid verification prefix")
    package = json.loads((ROOT / f"artifacts/{args.prefix}-package.json").read_text())
    archive = Path(package["package"])
    assert sha(archive) == package["sha256"]
    output = ROOT / "deployment/runtime" / time.strftime("package-check-%Y%m%d-%H%M%S")
    output.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as bundle:
        inventory = json.loads(bundle.read("file-hashes.json"))
        assert set(bundle.namelist()) == {"README.md", "file-hashes.json", *inventory}
        for name in bundle.namelist():
            assert (output / name).resolve().is_relative_to(output.resolve())
        bundle.extractall(output)
    for name, digest in inventory.items():
        assert sha(output / name) == digest
    log = ROOT / f"artifacts/{args.prefix}-offline-install.log"
    # PowerShell 7 adjusts this path when launching Windows PowerShell directly;
    # Python does not. Let 5.1 reconstruct its own stock module search paths.
    installer_environment = {key: value for key, value in os.environ.items() if key.lower() != "psmodulepath"}
    with log.open("w", encoding="utf-8") as handle:
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        str(output / "scripts/Install-Balut.ps1"), "-PythonExecutable", sys.executable],
                       cwd=output, env=installer_environment, check=True, stdout=handle, stderr=subprocess.STDOUT, timeout=240)
    code = '''from pathlib import Path
import json
from balut_api.model_service import ModelService
root = Path.cwd()
profile = json.loads((root / "deployment/private/windows.json").read_text(encoding="utf-8-sig"))
registry = Path(profile["model_registry_path"])
expected = (registry.parent / "registry.sha256").read_text().split()[0]
service = ModelService()
service.load(registry, expected)
assert len(service.models) == len(json.loads(registry.read_text())["models"])
print(json.dumps({"loaded_models": list(service.models), "analysis_model": service.analysis_model_id, "scope": "SOURCE_LABEL_SHADOW_ONLY"}))
service.close()
'''
    result = subprocess.run([str(output / ".venv-serving/Scripts/python.exe"), "-"],
                            input=code, text=True, capture_output=True, check=True, timeout=60,
                            cwd=output, env={**os.environ, "PYTHONPATH": str(output / "apps/edge_api")})
    report = {"passed": True, "offline_installation": True,
              "fresh_environment_model_verification": json.loads(result.stdout), "directory": str(output),
              "inventory_files_verified": len(inventory), "package_sha256": package["sha256"]}
    (ROOT / f"artifacts/{args.prefix}-offline-verification.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
