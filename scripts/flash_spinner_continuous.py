"""Flash only the verified application on the identified spinner controller."""
import hashlib
import json
import struct
from pathlib import Path

import esptool
from serial.tools import list_ports

from scripts.patch_spinner_continuous import checked_image


def require_original_boot_selection(flash):
    entries = tuple(struct.unpack_from("<I20xII", flash, offset) for offset in (0xE000, 0xF000))
    # Confirmed legacy OTA sequence 1 boots app0; do not alter the boot records.
    if entries != ((1, 0xFFFFFFFF, 0x4743989A), (0, 0xFFFFFFFF, 0xFFFFFFFF)):
        raise ValueError("Spinner boot selection changed; app0 is not confirmed")


def main():
    root = Path(__file__).resolve().parents[1]
    backup = root / "deployment/private/spinner-backup"
    build = root / "deployment/private/spinner-build"
    manifest = json.loads((backup / "manifest.json").read_text())
    original = (backup / "original-20261017.bin").read_bytes()
    if not manifest["complete"] or hashlib.sha256(original).hexdigest() != manifest["sha256"]:
        raise ValueError("Verified full original backup is required")
    require_original_boot_selection(original)
    _, original_app = checked_image(original[0x10000:])
    _, patched = checked_image((build / "continuous-app.bin").read_bytes())
    build_manifest = json.loads((build / "manifest.json").read_text())
    if hashlib.sha256(patched).hexdigest() != build_manifest["patchedApplicationSha256"]:
        raise ValueError("Patched application hash changed")
    ports = [p for p in list_ports.comports() if p.device == "COM4" and p.vid == 0x10C4 and p.pid == 0xEA60 and p.serial_number == "0001"]
    if len(ports) != 1:
        raise ValueError("Spinner USB adapter identity changed")
    esp = esptool.detect_chip("COM4", 115200, connect_attempts=2)
    try:
        mac = ":".join(f"{value:02x}" for value in esp.read_mac())
        if esp.CHIP_NAME != "ESP32" or mac != "3c:8a:1f:09:88:8c" or mac != manifest["mac"]:
            raise ValueError("Spinner controller identity changed")
        esp = esp.run_stub()
        esptool.cmds.attach_flash(esp)
        for offset, length in ((0x8000, 0x1000), (0xE000, 0x2000)):
            if esp.flash_md5sum(offset, length).lower() != hashlib.md5(original[offset:offset + length]).hexdigest():
                raise ValueError("Installed partitions or boot selection changed since backup")
        current = esp.flash_md5sum(0x10000, len(original_app)).lower()
        expected = hashlib.md5(patched).hexdigest()
        if current == expected:
            print("Continuous spinner application is already installed.", flush=True)
        else:
            if current != hashlib.md5(original_app).hexdigest():
                raise ValueError("Installed spinner application changed since backup")
            esptool.cmds.write_flash(esp, [(0x10000, patched)])
        if esp.flash_md5sum(0x10000, len(patched)).lower() != expected:
            raise ValueError("Written spinner application failed verification")
        print("Spinner application verified on-device. Original bootloader, partitions, and settings retained.", flush=True)
    finally:
        esp.hard_reset()
        esp._port.close()


if __name__ == "__main__":
    main()
