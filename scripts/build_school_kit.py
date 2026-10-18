"""Build an allowlisted Windows USB kit and a separate credential-free Vercel source ZIP."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/school-defense-20261017"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def tree(files, source, target):
    source = ROOT / source
    assert source.is_dir(), source
    for path in source.rglob("*"):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            files[(Path(target) / path.relative_to(source)).as_posix()] = path


def pack(name, top, files):
    archive = OUT / name
    inventory = {}
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for name, path in sorted(files.items()):
            assert not any(part in {"private", "backups", "logs", ".git", "node_modules"} for part in Path(name).parts), name
            assert path.is_file(), path
            bundle.write(path, top + "/" + name)
            inventory[name] = sha(path)
        bundle.writestr(top + "/file-hashes.json", json.dumps(inventory, indent=2) + "\n")
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
    return {"path": str(archive), "bytes": archive.stat().st_size, "sha256": sha(archive), "payloadFiles": len(inventory)}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cloud = ROOT / "deployment/runtime/school-tools/cloudflared-windows-amd64.exe"
    assert sha(cloud) == "4d2490e74082c5d48dbfedaf92576fa5bd1702379ab88eb7faa0cfbe8dc891b6"
    school = {}
    for source, target in [
        ("apps/edge_api/balut_api", "apps/edge_api/balut_api"), ("apps/web/dist", "apps/web/dist"),
        ("deployment/releases/automatic-recapture-20260912", "deployment/releases/automatic-recapture-20260912"),
        ("deployment/runtime/school-python-build/cpython-3.12.15-windows-x86_64-none", "runtime/python"),
        ("deployment/drivers/ftdi/exported", "deployment/drivers/ftdi/exported"),
        ("deployment/drivers/cp210x/package", "deployment/drivers/cp210x/package"),
    ]:
        tree(school, source, target)
    for name in ["SchoolBox.ps1", "Initialize-Serving.ps1", "Start-Balut.ps1", "camera_usb_bridge.py", "spinner_control.py", "prepare_render_account.py", "upload_box_frames.py", "backup_serving.py", "migrate_supabase.py"]:
        school["scripts/" + name] = ROOT / "scripts" / name
    for name in ["Start School Box.cmd", "Stop School Box.cmd", "Start Vercel Connector.cmd", "Copy Vercel Key.cmd", "Install USB Drivers.cmd", "Prepare Render Account.cmd", "Connect Render Box.cmd", "Connect Cloud Box.cmd"]:
        school[name] = ROOT / name
    school["runtime/cloudflared.exe"] = cloud
    for name in ["cloudflared-LICENSE", "cloudflared-source.json"]:
        school["runtime/" + name] = cloud.parent / name
    school["deployment/drivers/vcredist/vc_redist.x64.exe"] = ROOT / "deployment/drivers/vcredist/vc_redist.x64.exe"
    school["README.md"] = ROOT / "docs/VERCEL_SUPABASE_SETUP.md"
    school["LOCAL_FALLBACK.md"] = ROOT / "docs/SCHOOL_VERCEL_SETUP.md"
    school["RENDER_SETUP.md"] = ROOT / "docs/RENDER_FREE_SETUP.md"
    school["SUPABASE_SETUP.md"] = ROOT / "docs/SUPABASE_SETUP.md"
    school["requirements-serving.lock.txt"] = ROOT / "deployment/requirements-serving.lock.txt"

    result = {
        "school": pack("Balut-School-Cloud-20261017.zip", "BalutSchoolBox", school),
        "vercel": "Run scripts/build_vercel_source.py for the Vercel website and AI package",
        "scope": "Prepared software; actual other laptop, public Vercel and real-egg acceptance still required",
    }
    (OUT / "packages.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
