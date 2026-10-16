"""Create the user's cloud account settings locally; never send credentials to chat."""
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import subprocess

from balut_api.browser_auth import hash_password


def main():
    root = Path(__file__).resolve().parents[1]
    private = root / "deployment/private"
    private.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        raise SystemExit("Run this helper on the Windows box laptop")
    identity = subprocess.check_output(["whoami.exe"], text=True).strip()
    subprocess.run(["icacls.exe", str(private), "/inheritance:r", "/grant:r", identity + ":(OI)(CI)F", "SYSTEM:(OI)(CI)F"], check=True, capture_output=True)
    target = private / "render-env.txt"
    if target.exists():
        print("Render settings already exist. Keep them; changing settings would change the account after a cloud reset.")
        return
    username = input("Choose your Render username: ").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,31}", username):
        raise SystemExit("Use 3-32 letters, numbers, dots, underscores or hyphens")
    password = getpass.getpass("Choose your password (hidden, at least 12 characters): ")
    if not 12 <= len(password) <= 128 or password != getpass.getpass("Confirm password (hidden): "):
        raise SystemExit("Passwords must match and contain 12-128 characters")
    values = {"BALUT_OPERATOR_USERNAME": username, "BALUT_OPERATOR_PASSWORD_HASH": hash_password(password),
              "BALUT_LOCAL_ADMIN_TOKEN": secrets.token_urlsafe(48), "BALUT_DEVICE_SHARED_SECRET": secrets.token_urlsafe(48)}
    target.write_text("\n".join(name + "=" + value for name, value in values.items()) + "\n", encoding="utf-8")
    (private / "render-device.json").write_text(json.dumps({"secret": values["BALUT_DEVICE_SHARED_SECRET"]}), encoding="utf-8")
    print("Created deployment/private/render-env.txt. Paste its four settings into Render Environment Variables.")
    print("Your password was not saved. Protect this folder and never add it to Git or send it in chat.")


if __name__ == "__main__":
    main()
