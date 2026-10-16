# Spinner diagnosis — 2026-10-17

The user requests continuous rotation in one direction, rather than the current forward/reverse behavior.

## Observed evidence

- User video: `C:\Users\My Pc\Downloads\e47bb179-a688-4fa4-9211-3907e145f12b.mp4`, 5.6 seconds, 576x1024 at 30 fps. It shows the illuminated empty holder; it does not expose the motor or driver label/wiring.
- Existing motor adapter: CP210x, COM4, VID/PID `10c4:ea60`, serial `0001`. This is separate from the FTDI camera on COM3.
- A four-second passive serial capture at 115200 baud sent no commands. The console changed from Forward at 0.093 seconds to Reverse at 0.734 seconds, then Forward at 3.234 seconds. The reverse interval was 2.5 seconds. The Forward message is printed rapidly; these counts are not motor steps or RPM measurements.
- Evidence: `output/spinner-diagnosis-20261017/controller-log-summary.json`, contact sheet, and holder frame.

## Hardware and original behavior

The second user video, `38161b8b-1603-4439-86ff-03085eb6ee10.mp4`, shows a five-wire geared stepper and its drive gear. The user confirmed that the box receives power only from its two USB cables. The motor/driver labels are not legible; exact replacement part ratings are not established.

Read-only identification reports ESP32-D0WD-V3 rev 3.1 on COM4, MAC `3c:8a:1f:09:88:8c`, with 4 MB flash. The supplied application disassembles to Arduino Stepper initialization with 2048 steps per revolution, constructor pin order 18/21/19/22, and speed 10 RPM. Its loop prints Forward, steps +512, waits 1000 ms, prints Reverse, steps -512, and waits another 1000 ms. This accounts for the approximately 2.5-second direction intervals. The firmware speed setting is not a measurement of holder RPM; the external gearing changes holder speed.

The repository's ESP32-S3 firmware is a separate non-energizing research scaffold with unassigned motor pins. It is not evidence of the supplied controller's wiring or installed source. Do not transplant its proposed TMC2209/NEMA17 wiring into the physical box without verification.

## Installed change and verification

The complete 4,194,304-byte original flash is preserved at `deployment/private/spinner-backup/original-20261017.bin`, with a manifest. Every block was checked against its on-device MD5, and the completed backup matched the device's full-flash MD5. Disk SHA-256: `5cab4dd1e4f6c1e3dd3a77442d5104a05ac58e485c284baba126a26c253eeb91`. A faster USB transfer failed before completion; the verified backup used slower reads and independently verified cached/blank blocks.

The user could not identify the motor connector for isolation. The subsequent read and update used the observed empty holder with the user instructed to keep hands clear. No uncertain connector was removed.

The original Arduino source was not supplied. `scripts/patch_spinner_continuous.py` therefore makes a narrowly guarded change to the exact original compiled application. At instruction address `0x400d16f9`, immediately after the forward step(512) call, it replaces the 1000-ms delay argument instruction with an Xtensa `retw`. The Arduino outer loop now repeats forward stepping. The remaining pause/reverse instructions are unreachable. It regenerates and verifies the ESP image checksum and appended SHA-256.

Only three instruction bytes and image-integrity bytes change in the application. GPIO initialization, phase sequence, speed, bootloader, partition selection, and stored settings retain the supplied behavior. The original OTA records confirm app0 at flash offset `0x10000`; populated but invalid image data in app1 was not treated as an empty slot or changed. The flasher verifies those boot records and the existing application before writing.

- Original application SHA-256: `d12df6f631a3f78632c59885c21ce2682fcb31a08adad7ad81f4cd20c769661e`.
- Installed application SHA-256: `1a3f817634d36669c2c321c6e544762ad2d63f794f12db8d90252b6a11f358e4`.
- Application size: 272,960 bytes.
- Four tests passed: exact change boundary/integrity, corrupt-original rejection, already-patched rejection, and changed-boot-selection rejection.
- esptool verified the written application, followed by an independent on-device MD5 match.
- The user observed the empty holder and confirmed **continuous rotation in one direction** after the update.

`scripts/flash_spinner_continuous.py` is bound to this exact controller identity and backup. Both patch and flash scripts refuse mismatched inputs. This is not a general patch for other ESP32 boards or firmware versions. Keep the original backup private.

The spinner runs autonomously in its ESP firmware; the web and Android apps do not send motion commands. No camera firmware or app code was changed during this spinner repair. Rotation with a loaded egg, long-run temperature, and mechanical wear have not been measured.
