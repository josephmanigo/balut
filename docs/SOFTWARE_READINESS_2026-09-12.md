# Windows software readiness — 2026-09-12

Status: **SOFTWARE VERIFIED FOR LOCAL SHADOW USE**. The user requested the Windows laptop and confirmed software first because the assembled candler and timestamped own-egg images are not yet available. Automatic grading remains disabled.

The implemented service loads the three verified ONNX models, requires a local operator login, accepts bounded JPEG uploads through the browser/API, preserves image and prediction evidence, handles retries idempotently, and provides backup/restore and supervised startup scripts.

| Verification | Measured result |
|---|---|
| API/core tests | 54 passed; 4 optional training entries skipped in the serving environment |
| Web checks | 2 tests passed; TypeScript and production build passed |
| Live model inference | 3 real models match their known answers |
| Browser flow | JPEG upload, saved result, and review outcome passed at 1440×1000 and 390×844; no horizontal overflow or browser errors |
| Restart recovery | Saved prediction retained after abrupt test-process termination and restart |
| Backup/restore | Database integrity, evidence hashes, saved responses, and replay verified after restoring and restarting |
| Concurrent requests | Eight-request burst returned HTTP status counts {'200': 1, '429': 7}; no guessed success |
| Dependency audit | 0 known findings in the pinned Python environment and npm lockfile at scan time |
| Offline dependencies | 35 Windows x64/Python 3.12 wheels included, with SHA-256 inventory |

Single measured HTTP prediction samples on this laptop were 140 ms for age16-18, 125 ms for pat-status, 16 ms for duck-status. These are functional smoke-test timings, not percentile latency, sustained-load, thermal, or availability guarantees.

Windows restart verification recorded three distinct listening processes and confirmed the test port closed after every process-tree termination. Backup verification includes a live WAL database, a standalone snapshot, all referenced images, and rejection of incomplete inventories.

Pinned source-label registry SHA-256: `8efcac05d73a7c0b8b2bec10fddd6b05be66ac986b43e141aff3391b040120be`.

The final Python suite reports two upstream TestClient/AnyIO deprecation warnings. They did not fail the software checks. The four skips concern optional training dependencies; serving and release-verification tests ran. The earlier feature/public training suite separately passed 21 tests.

The runtime uses a single local operator credential and a separate device credential. The browser and data API are loopback-only, and credentials are generated per installation. Version-2 device signatures bind route and replay key; real firmware must implement that protocol before connection. The application does not claim independent reviewer accounts, working cloud delivery, or physical hardware control.

The package is suitable for installing and exercising the local source-label review software. It is not a validated automatic-grading, food-safety, Android, ESP32, or cloud release. Age-source accuracy is 82.9% on 35 historical images, and Pat still misses 14/137 Reject-labelled images. The physical study and candler acceptance criteria remain in the existing validation ledger.

[Operating and recovery guide](WINDOWS_MODEL_SERVICE.md) · [Accuracy report](ACCURACY_RESULTS_2026-09-12.md) · [Real-data collection guide](REAL_CANDLING_DATA_COLLECTION.md)
