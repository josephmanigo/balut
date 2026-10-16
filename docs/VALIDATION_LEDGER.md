# Validation and acceptance ledger

Evidence is entered only after a protocol run. Empty cells mean **not tested**,
not pass.

Latest local evidence is in [the 2026-10-04 hardening report](HARDENING_AND_ACCURACY_2026-10-04.md): 90 serving/core checks passed, five optional checks skipped, 25 overlapping training checks passed, and eight web tests plus the TypeScript/build passed. Real ONNX, desktop/mobile recapture, restart, and backup/restore passed. All three supplied ZIPs were re-audited; they match the already-used public archives and do not supply independent candler/egg evidence. The 80-candidate comparison is retained but not promoted because it does not improve the historical accepted result. The physical gates below remain blocked.

Current software-first evidence is recorded in
[AUTOMATIC_RECAPTURE_2026-09-12.md](AUTOMATIC_RECAPTURE_2026-09-12.md): 72 API/core
checks, eight web tests, real ONNX classification/automatic recapture, desktop/mobile upload, process
restart recovery, and database/evidence backup/restore passed. The user has
confirmed that the assembled candler and own timestamped egg images are not
available yet. Historical rows below do not supersede this newer software
report or change any physical acceptance gate.

## Software evidence

| Gate | Target | Current evidence | Status |
|---|---|---|---|
| Python API/ML unit suite | All pass | 23 passed on 2026-08-29; one upstream deprecation warning | PASS — local software |
| React tests | All pass | 2 passed on 2026-08-29 | PASS — local software |
| React production build | Completes | Vite build passed; artifact sizes recorded in implementation status | PASS — local software |
| Duplicate ingestion | One inspection/audit/outbox identity | Automated SQLite idempotency tests | Implemented locally |
| Append-only review | Machine result unchanged | Automated API test | Implemented locally |
| Client secrets | No service-role key in artifacts | Static scan plus release artifact scan | Pending release build |

## Physical and firmware evidence

| Gate | Target | Completed / failures | Evidence link | Status |
|---|---:|---:|---|---|
| Empty-holder cycles | 100 | 0 / — | — | BLOCKED |
| Egg-loaded cycles | 100, no holder-caused crack/drop | 0 / — | — | BLOCKED |
| Complete scans | at least 95 / 100 | 0 / — | — | BLOCKED |
| Lid-open cutoff | 100 / 100 | 0 / — | — | BLOCKED |
| E-stop cutoff | 100 / 100 | 0 / — | — | BLOCKED |
| Scan duration | at most 45 s target | — | — | BLOCKED |
| Full revolution | verified with fiducial | — | — | BLOCKED |
| Thermal limit | within approved protocol | — | — | BLOCKED |
| Offline box result | succeeds without laptop/Wi-Fi/cloud | — | — | BLOCKED |
| ESP32 int8 latency/memory | within measured target | — | — | BLOCKED |

## Model and research evidence

Public-source model training is recorded separately in
[TRAINING_RESULTS_2026-09-12.md](TRAINING_RESULTS_2026-09-12.md). It provides real
local checkpoints, source-label test results, and float32 ONNX parity. It does
not satisfy any physical-egg, prospective-test, int8, or operational-release
gate below.

The second [accuracy experiment](ACCURACY_RESULTS_2026-09-12.md) improved
historical source-age accuracy to 29/35 (82.9%) and Pat status to 445/461
(96.5%); its duck candidate regressed to 81/87 (93.1%). All 583 candidate
test predictions match between the frozen GPU results, CPU Torch, and
float32 ONNX exports. These are images/crops with unknown physical egg
identities. They do not satisfy the session-level or prospective gates below.

| Gate | Target | Current | Status |
|---|---:|---:|---|
| Unique physical eggs | at least 300 | 0 supplied here | BLOCKED |
| Automatic-decision coverage | at least 70% | — | BLOCKED |
| Balanced accuracy on decided sessions | at least 90% | — | BLOCKED |
| Per-class recall on decided sessions | at least 85% | — | BLOCKED |
| Int8 vs float loss | no more than 2 points | — | BLOCKED |
| Independent reviewers | 2 per condition label | none evidenced | BLOCKED |
| Representative usability participants | at least 10 | 0 | BLOCKED |
| Assisted-free completion | at least 90% | — | BLOCKED |
| SUS | target at least 80 | — | BLOCKED |

Final status must be one of `CAPSTONE TARGET MET`, `PARTIAL—SHADOW MODE ONLY`,
or `FEASIBILITY NOT DEMONSTRATED`. At the current evidence level it cannot be
the first option.
