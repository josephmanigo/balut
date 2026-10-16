"""Stage an allowlisted Vercel source tree, excluding credentials, local data and training files."""
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from build_school_kit import ROOT, OUT, pack, tree


def main():
    files = {name: ROOT / name for name in (
        "app.py", "vercel.json", ".python-version", "package.json", "package-lock.json",
        "requirements.txt", "scripts/assemble_render_model.py")}
    for directory in ("apps/edge_api/balut_api", "apps/web/src", "deployment/model-parts",
                      "deployment/releases/automatic-recapture-20260912"):
        tree(files, directory, directory)
    files.pop("deployment/releases/automatic-recapture-20260912/egg-grade/best.onnx")
    for name in ("index.html", "package.json", "tsconfig.json", "tsconfig.app.json", "tsconfig.node.json", "vite.config.ts"):
        files["apps/web/" + name] = ROOT / "apps/web" / name
    stage = ROOT / "deployment/runtime" / ("vercel-source-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    stage.mkdir(parents=True)
    for name, source in files.items():
        assert not any(part in {"private", "data", "evidence", "node_modules", "__pycache__"} for part in Path(name).parts)
        target = stage / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    files["README.md"] = ROOT / "docs/VERCEL_SUPABASE_SETUP.md"
    shutil.copy2(files["README.md"], stage / "README.md")
    OUT.mkdir(parents=True, exist_ok=True)
    result = pack("Balut-Vercel-Supabase-20261017.zip", "BalutVercel", files)
    result["stage"] = str(stage)
    (OUT / "vercel-source-package.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
