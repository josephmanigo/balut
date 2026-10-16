# Phased bill of materials

This procurement list intentionally separates the optical feasibility gate from
the full mechanism purchase.

## Phase 1 — optical and on-device feasibility

| Item | Minimum requirement | Freeze decision |
|---|---|---|
| ESP32-S3 multimedia board | 8 MB or more PSRAM; enough flash for dual firmware/model slots | Confirm exact Korvo-2 revision, flash/PSRAM, accessible GPIOs |
| Camera | Board-compatible OV3660 reference | Focus, sensor orientation, locked exposure support |
| LCD extension | Board-compatible | Bilingual state legibility and GPIO conflicts |
| microSD | 32 GB high-endurance | Filesystem, write latency, endurance, card-detect behavior |
| Prototype LED optics | Low-power white sources, diffusers, baffles | Brightness, saturation, contrast, pulse duration |
| Bench power | Current-limited supply, meters, temperature probes | Capture transient and thermal evidence |

Do not purchase/fabricate the final enclosure until camera + SD + LCD + a tiny
int8 known-answer model coexist without resets or memory failure.

## Phase 2 — guarded rotation and illumination

| Item | Requirement |
|---|---|
| Stepper | Low-current NEMA 17 sized from measured holder torque |
| Driver | TMC2209 carrier with accessible current adjustment and enable |
| Drive | Belt reduction or flexible coupling; guarded pinch points |
| Holder | Two removable silicone cups; spring-loaded slide; hard compression stop |
| Index | Hall-effect sensor and shaft magnet |
| Presence | Validated egg-presence sensor |
| Interlocks | Dual-pole NC lid switch plus latching emergency stop with sufficient contacts |
| Candling source | 3–5 W LED star, matched constant-current driver, aluminum heatsink, diffuser, baffle |
| Shell source | Independently switched, current-limited diffuse LED |
| Thermal | Sensor adjacent to LED and independent measurement probe for validation |
| Power | Certified enclosed 12 V / 3 A adapter; fused branches; filtered 5 V buck |
| Enclosure | Opaque guarded chamber, dry electronics area, washable contacts, removable spill tray |

## Consumables and evidence tools

Engineering fiducials, instrumented/non-study test eggs, cleaning materials
compatible with the cups/tray, spare contacts, fuse assortment selected after
measurement, labels, tamper evidence, clamp-force gauge, tachometer/angle
reference, lux or imaging reference, oscilloscope, current probes, and calibrated
temperature logging.

Substitutions require a schematic, firmware-pin, thermal, and test-protocol
review. Similar appearance is not electrical compatibility.
