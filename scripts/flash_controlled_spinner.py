"""Install capture-hold control on the identified spinner, preserving its boot records."""
import hashlib
import json
from pathlib import Path
import esptool
from serial.tools import list_ports

from scripts.patch_spinner_continuous import checked_image
from scripts.flash_spinner_continuous import require_original_boot_selection


def main():
    root = Path(__file__).resolve().parents[1]
    backup = root / "deployment/private/spinner-backup"
    original = (backup / "original-20261017.bin").read_bytes()
    manifest = json.loads((backup / "manifest.json").read_text())
    if not manifest["complete"] or hashlib.sha256(original).hexdigest() != manifest["sha256"]:
        raise ValueError("Verified original spinner backup required")
    require_original_boot_selection(original)
    previous = (root / "deployment/private/spinner-build/continuous-app.bin").read_bytes()
    if hashlib.sha256(previous).hexdigest() != "1a3f817634d36669c2c321c6e544762ad2d63f794f12db8d90252b6a11f358e4":
        raise ValueError("Verified current spinner application required")
    build = root / "deployment/private/spinner-controlled-build"
    built = json.loads((build / "capture-build.json").read_text())
    target = (build / "ControlledSpinner.ino.bin").read_bytes()
    source = root / "firmware/spinner/ControlledSpinner/ControlledSpinner.ino"
    if (hashlib.sha256(target).hexdigest() != built["application_sha256"]
            or hashlib.sha256(source.read_bytes()).hexdigest() != built["source_sha256"] or len(target) >= 0x140000):
        raise ValueError("Controlled spinner build changed")
    checked_image(target)
    ports = [p.device for p in list_ports.comports() if p.vid == 0x10C4 and p.pid == 0xEA60 and p.serial_number == "0001"]
    if len(ports) != 1:
        raise ValueError("Spinner adapter identity changed")
    esp = esptool.detect_chip(ports[0], 115200, connect_attempts=2)
    try:
        mac = ":".join(f"{v:02x}" for v in esp.read_mac())
        if esp.CHIP_NAME != "ESP32" or mac != manifest["mac"] or mac != "3c:8a:1f:09:88:8c":
            raise ValueError("Spinner controller identity changed")
        esp = esp.run_stub()
        esptool.cmds.attach_flash(esp)
        for offset, length in ((0x8000, 0x1000), (0xE000, 0x2000)):
            if esp.flash_md5sum(offset, length).lower() != hashlib.md5(original[offset:offset + length]).hexdigest():
                raise ValueError("Spinner partitions or boot selection changed")
        if esp.flash_md5sum(0x10000, len(previous)).lower() != hashlib.md5(previous).hexdigest():
            raise ValueError("Installed application differs from the verified continuous spinner")
        installed = esp.read_flash(0x10000, len(previous))
        if installed != previous:
            raise ValueError("Current spinner application backup failed")
        preserved = backup / "before-capture-hold.bin"
        if preserved.exists():
            raise FileExistsError("Preserve the existing before-capture backup")
        preserved.write_bytes(installed)
        esptool.cmds.write_flash(esp, [(0x10000, target)])
        if esp.flash_md5sum(0x10000, len(target)).lower() != hashlib.md5(target).hexdigest():
            raise ValueError("Controlled spinner write verification failed")
        print(json.dumps({"installed": True, "mac": mac, "application_sha256": built["application_sha256"],
                          "application_bytes": len(target), "boot_records_preserved": True, "camera_firmware_changed": False}), flush=True)
    finally:
        esp.hard_reset()
        esp._port.close()


if __name__ == "__main__":
    main()
