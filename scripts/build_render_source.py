"""Package the selected free Render deployment without private state or giant Git blobs."""
import hashlib
import json
from pathlib import Path
import zipfile

from build_school_kit import ROOT, OUT, pack, sha, tree


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    chunks = ROOT / "deployment/runtime/render-model-parts-build"
    chunks.mkdir(parents=True, exist_ok=True)
    model = ROOT / "deployment/releases/automatic-recapture-20260912/egg-grade/best.onnx"
    manifest = {"bytes": model.stat().st_size, "sha256": sha(model), "parts": []}
    with model.open("rb") as stream:
        index = 0
        while body := stream.read(20 * 1024 * 1024):
            name = f"best.onnx.part{index:02}"
            path = chunks / name
            path.write_bytes(body)
            manifest["parts"].append({"name": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
            index += 1
    (chunks / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    files = {name: ROOT / name for name in ["Dockerfile", ".dockerignore", "render.yaml", "package.json", "package-lock.json",
                                          "scripts/assemble_render_model.py", "deployment/requirements-serving.lock.txt"]}
    tree(files, "apps/edge_api/balut_api", "apps/edge_api/balut_api")
    tree(files, "apps/web/src", "apps/web/src")
    for name in ["index.html", "package.json", "tsconfig.json", "tsconfig.app.json", "tsconfig.node.json", "vite.config.ts"]:
        files["apps/web/" + name] = ROOT / "apps/web" / name
    tree(files, "deployment/releases/automatic-recapture-20260912", "deployment/releases/automatic-recapture-20260912")
    files.pop("deployment/releases/automatic-recapture-20260912/egg-grade/best.onnx")
    for part in chunks.iterdir():
        if part.name == "manifest.json" or part.name in {entry["name"] for entry in manifest["parts"]}:
            files["deployment/model-parts/" + part.name] = part
    files["README.md"] = ROOT / "docs/RENDER_FREE_SETUP.md"
    files["SUPABASE_SETUP.md"] = ROOT / "docs/SUPABASE_SETUP.md"
    files["supabase/migrations/202610170001_shared_workspace.sql"] = ROOT / "supabase/migrations/202610170001_shared_workspace.sql"
    files["scripts/migrate_supabase.py"] = ROOT / "scripts/migrate_supabase.py"
    files[".gitignore"] = ROOT / "deployment/templates/vercel.gitignore"
    result = pack("Balut-Render-Supabase-20261017.zip", "BalutRender", files)
    result["scope"] = "Shared storage requires Supabase setup; live deployment and physical acceptance pending"
    (OUT / "render-supabase-package.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
