"""Remove reversal/dwell from this exact supplied application; keep its GPIO setup."""
import hashlib
import io
import json
import struct
from pathlib import Path

from esptool.bin_image import ESP32FirmwareImage

ORIGINAL_DIGEST = "82f97a80956cb498d47accf252041bebe03d9c9c2281b149785576ce29887694"
RETURN_ADDRESS = 0x400D16F9
ORIGINAL_INSTRUCTION = bytes.fromhex("a2a3e8")  # movi a10, 1000, immediately after forward step(512).
RETURN_INSTRUCTION = bytes.fromhex("900000")  # retw: return to Arduino's outer loop.


def checked_image(body):
    image = ESP32FirmwareImage(io.BytesIO(body))
    if not image.append_digest or image.data_length is None:
        raise ValueError("Expected an ESP32 application with an appended digest")
    if image.checksum != image.calculate_checksum() or image.stored_digest != image.calc_digest:
        raise ValueError("Application checksum or digest is invalid")
    return image, bytes(body[:image.data_length + 32])


def instruction_offset(body):
    position = 24
    for _ in range(body[1]):
        address, length = struct.unpack_from("<II", body, position)
        position += 8
        if address <= RETURN_ADDRESS and RETURN_ADDRESS + 3 <= address + length:
            return position + RETURN_ADDRESS - address
        position += length
    raise ValueError("Spinner loop is missing")


def patch_application(body):
    image, original = checked_image(body)
    if image.calc_digest.hex() != ORIGINAL_DIGEST:
        raise ValueError("This patch is only for the exact backed-up spinner application")
    offset = instruction_offset(original)
    if original[offset:offset + 3] != ORIGINAL_INSTRUCTION:
        raise ValueError("Unexpected spinner instruction; no patch applied")
    patched = bytearray(original)
    patched[offset:offset + 3] = RETURN_INSTRUCTION
    checksum_offset = image.data_length - 1
    changed = ESP32FirmwareImage(io.BytesIO(patched))
    patched[checksum_offset] = changed.calculate_checksum()
    patched[image.data_length:] = hashlib.sha256(patched[:image.data_length]).digest()
    _, verified = checked_image(patched)
    allowed = set(range(offset, offset + 3)) | {checksum_offset} | set(range(image.data_length, image.data_length + 32))
    if len(verified) != len(original) or any(a != b and i not in allowed for i, (a, b) in enumerate(zip(original, verified))):
        raise ValueError("Unexpected changes outside the spinner instruction and integrity bytes")
    return verified


def main():
    root = Path(__file__).resolve().parents[1]
    backup = root / "deployment/private/spinner-backup"
    manifest = json.loads((backup / "manifest.json").read_text())
    original = (backup / "original-20261017.bin").read_bytes()
    if not manifest["complete"] or manifest["mac"] != "3c:8a:1f:09:88:8c" or hashlib.sha256(original).hexdigest() != manifest["sha256"]:
        raise ValueError("Verified original spinner backup required")
    _, application = checked_image(original[0x10000:])
    patched = patch_application(application)
    output = root / "deployment/private/spinner-build"
    output.mkdir(parents=True, exist_ok=True)
    (backup / "original-app.bin").write_bytes(application)
    (output / "continuous-app.bin").write_bytes(patched)
    report = {"originalApplicationSha256": hashlib.sha256(application).hexdigest(),
              "patchedApplicationSha256": hashlib.sha256(patched).hexdigest(),
              "bytes": len(patched), "instructionAddress": hex(RETURN_ADDRESS),
              "originalInstruction": ORIGINAL_INSTRUCTION.hex(), "patchedInstruction": RETURN_INSTRUCTION.hex(),
              "pinsChanged": False, "speedChanged": False, "flashOffset": "0x10000"}
    (output / "manifest.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
