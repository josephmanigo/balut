"""Write the three Vercel server variables locally without printing credentials."""
import json
from pathlib import Path
import secrets


def main():
    root = Path(__file__).resolve().parents[1]
    private = root / "deployment/private"
    cloud = json.loads((private / "supabase.json").read_text(encoding="utf-8-sig"))
    profile_path = private / "cloud-device.json"
    if profile_path.exists():
        profile = json.loads(profile_path.read_text(encoding="utf-8-sig"))
    else:
        profile = {"secret": secrets.token_urlsafe(48)}
        profile_path.write_text(json.dumps(profile, indent=2) + "\n")
    values = {"SUPABASE_URL": cloud["url"], "SUPABASE_SECRET_KEY": cloud["secret_key"],
              "BALUT_DEVICE_SHARED_SECRET": profile["secret"]}
    destination = private / "vercel.env"
    assert all("\n" not in value and "\r" not in value for value in values.values())
    destination.write_text("".join(f"{name}={value}\n" for name, value in values.items()))
    print(f"Prepared protected environment file: {destination}")


if __name__ == "__main__":
    main()
