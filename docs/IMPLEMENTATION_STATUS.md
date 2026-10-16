# Implementation status

Status is intentionally split into software evidence and physical/research evidence.

The 2026-09-12 software-first update adds a verified Windows model-serving
profile, source-label JPEG analysis in the browser, authentication and upload
hardening, versioned model verification, durable predictions, and tested
backup/restore. See [the current verification report](SOFTWARE_READINESS_2026-09-12.md).
The historical scaffold/build snapshot below describes the earlier prototype;
physical hardware, cloud, Android, and automatic-grading evidence is still absent.

| Capability | State | Evidence required to advance |
|---|---|---|
| Domain contracts and banned-claim boundary | Implemented | Contract and unit tests |
| Local FastAPI and SQLite workflow | Implemented locally | Passing API, transaction, and idempotency tests |
| Deterministic scan simulator | Implemented, synthetic only | Passing simulator tests; never treated as hardware evidence |
| React evidence dashboard | Implemented locally; Filipino is a limited preview | Production build plus desktop/mobile inspection; full localization still required |
| ESP32-S3 firmware | Scaffold only | ESP-IDF build on selected board, then hardware-in-loop tests |
| Flutter Android | Source scaffold | Flutter toolchain, emulator/device build, offline and permission tests |
| Supabase | Schema and RLS only | Project provisioning, migrations, policy tests, and secret review |
| CNN | Trained public-source float32 models and verified local ONNX serving | Identified physical data, prospective validation, int8/ESP-DL conversion and device parity |
| Electrical safety | Blocked | As-built wiring inspection and 100/100 physical cutoff trials |
| Optical/mechanical repeatability | Blocked | Physical enclosure, calibrated optics, egg rotation and thermal trials |
| 300-egg validation | Blocked | Approved collection, two-reviewer labels, frozen prospective test |
| Vendor usability | Blocked | At least ten representative operators and recorded results |
| Production readiness | Blocked | Prototype gates do not constitute regulatory or commercial authorization |

The final release gate is fail-closed: unmet evidence preserves `PARTIAL—SHADOW MODE ONLY` or `FEASIBILITY NOT DEMONSTRATED`.

## Verification snapshot — 2026-08-29

- `scripts/verify.ps1`: pass.
- Python API/ML suite: 23 passed; one upstream Starlette `TestClient` deprecation warning.
- React/Vitest suite: 2 passed.
- TypeScript composite build and Vite production build: pass; 1,810 modules transformed.
- Built web assets: 222.85 kB JavaScript (70.69 kB gzip) and 17.89 kB CSS (4.47 kB gzip).
- Live browser: real FastAPI + Vite integration exercised for decided and abstained synthetic cases; no console warnings/errors.
- Responsive inspection: all nine reachable views checked at 390×844 with no document-level horizontal overflow; workbench checked at 1440×900.
- Client/firmware static scan: no Supabase service-role reference and no banned operator safety claim in shipping source.
- Toolchain audit: Flutter, ESP-IDF, CMake, and a host C/C++ compiler were not installed, so those source trees remain unbuilt.

These are software-only results. They provide no evidence for physical cutoff,
mechanical, optical, CNN, 300-egg, vendor-usability, or production gates.
