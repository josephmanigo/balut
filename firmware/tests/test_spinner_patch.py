import unittest
import struct
from pathlib import Path

from scripts.patch_spinner_continuous import (
    ORIGINAL_INSTRUCTION, RETURN_INSTRUCTION, checked_image, instruction_offset, patch_application,
)
from scripts.flash_spinner_continuous import require_original_boot_selection


class SpinnerPatchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        backup = Path(__file__).resolve().parents[2] / "deployment/private/spinner-backup/original-20261017.bin"
        if not backup.exists():
            raise unittest.SkipTest("Requires the private original physical-controller backup")
        cls.full_backup = backup.read_bytes()
        _, cls.original = checked_image(cls.full_backup[0x10000:])

    def test_only_the_return_instruction_and_integrity_bytes_change(self):
        image, original = checked_image(self.original)
        offset = instruction_offset(original)
        self.assertEqual(original[offset:offset + 3], ORIGINAL_INSTRUCTION)
        patched = patch_application(original)
        self.assertEqual(patched[offset:offset + 3], RETURN_INSTRUCTION)
        self.assertEqual(patched[:offset], original[:offset])
        self.assertEqual(patched[offset + 3:image.data_length - 1], original[offset + 3:image.data_length - 1])
        checked_image(patched)

    def test_a_previously_patched_image_cannot_be_patched_again(self):
        with self.assertRaisesRegex(ValueError, "exact backed-up"):
            patch_application(patch_application(self.original))

    def test_a_corrupt_original_is_rejected(self):
        damaged = bytearray(self.original)
        damaged[100] ^= 1
        with self.assertRaisesRegex(ValueError, "checksum or digest"):
            patch_application(damaged)

    def test_other_boot_selections_are_rejected_before_any_flash(self):
        require_original_boot_selection(self.full_backup)
        changed = bytearray(self.full_backup)
        struct.pack_into("<I", changed, 0xE000, 2)
        with self.assertRaisesRegex(ValueError, "boot selection changed"):
            require_original_boot_selection(changed)


if __name__ == "__main__":
    unittest.main()
