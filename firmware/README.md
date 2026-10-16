# ESP32-S3 firmware boundary

The separate [AI-Thinker camera target](camera/BoxCamera/BoxCamera.ino) is for the identified ESP32-CAM and supplies snapshots over its USB cable. The local PC bridge exposes `/capture` to the existing web workflow. Its setup and verification are tracked in [physical box connection](../docs/BOX_CONNECTION_2026-10-16.md). The motor/light restrictions below still apply to the ESP32-S3 scaffold in `main/`.

This directory is an ESP-IDF safety-first scaffold for the Balut box. It does
not contain board pin assignments, a camera sensor profile, an ESP-DL model, or
evidence from physical hardware. Those omissions are intentional: the default
build cannot energize either the motor or the candling light.

## Implemented in source

- Explicit inspection-state transition table.
- Latched safe-stop logic and fresh-start recovery contract.
- Motor and light gate abstraction whose compile-time default is disabled.
- FreeRTOS task boundaries and priorities.
- Pure-C fail-closed aggregate decision policy.
- A/B firmware and A/B model partition-table proposal for a 16 MB flash part.
- Host-side unit tests for safety and aggregation logic.

## Hardware enable gate

`main/include/board_config.h` deliberately defines all board-specific pins as
`GPIO_NUM_NC` and `BALUT_HARDWARE_ENERGIZING_BUILD` as `0`. Do not change the
energizing flag until the final schematic, external hardware cutoff, GPIO boot
states, actual Korvo-2 pin availability, and bench tests are approved.

An enabled firmware output is only a command into an external gate. The
normally-closed lid switch and latching emergency stop must still remove the
driver and LED enable in hardware.

## Build prerequisites

ESP-IDF is not installed in the current workspace, so this source has not been
compiled against the target board. After provisioning an ESP-IDF environment:

```powershell
idf.py set-target esp32s3
idf.py build
```

Treat the result as a non-energizing firmware smoke test until the hardware
bring-up checklist in `docs/HARDWARE_BRINGUP.md` is signed.
