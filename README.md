# Balut AIoT research prototype

Deploy the **website and AI on Vercel**, with the account, sessions, prediction
history, camera state and private images in Supabase. See
[Vercel deployment and environment variables](docs/VERCEL_SUPABASE_SETUP.md) and
[Supabase setup and local-data migration](docs/SUPABASE_SETUP.md).
The USB laptop sends signed frames; any signed-in laptop or phone can view results.

This repository implements the software side of a single-egg, eight-view Balut candling research prototype. It contains a runnable local API and simulator, a bilingual React dashboard, ESP32-S3 firmware and hardware interfaces, a Flutter Android workspace, leakage-safe ML tooling, and Supabase schema/RLS definitions.

The GitHub checkout includes source code, documentation, test fixtures, and the
current model release. Its model is stored in five chunks; the Vercel and Docker
builds reconstruct it and verify its SHA-256. Import the repository root into
Vercel with the **FastAPI** preset and the commands in `vercel.json`.
The [Render guide](docs/RENDER_FREE_SETUP.md) remains an alternative deployment.
Training checkpoints, downloaded datasets, private credentials, saved predictions,
installed runtimes, and generated APK/ZIP packages stay local and are excluded
from Git. The simulator setup below does not require the trained model.

The Windows **software-first model service** is now prepared: authenticated
manual photo uploads and automatic ESP32-CAM snapshot processing, a single Day 16 / Day 18 / Reject model with automatic recapture for unclear images, durable prediction records,
offline installation, and backup/restore. Read the
[2026-10-04 hardening and accuracy comparison](docs/HARDENING_AND_ACCURACY_2026-10-04.md),
[Windows operating guide](docs/WINDOWS_MODEL_SERVICE.md) and
[current automatic-recapture report](docs/AUTOMATIC_RECAPTURE_2026-09-12.md). There is no mandatory human review in this upload workflow. Unclear images remain unclassified. Historical accepted accuracy is 95/97 with 97/172 coverage; 100% accuracy has not been achieved.
Use `scripts/Start-Balut.ps1` for that profile; the development commands below
continue to run the separate simulator configuration. Automatic physical egg
grading and physical actuation remain disabled pending the candler and real-egg validation. Camera scene-change capture is available as a research workflow; it requires an empty-box reference and a reachable camera. See [automatic camera setup](docs/AUTOMATIC_BOX_2026-10-14.md). Physical ESP32-CAM acceptance has not been performed.

## What is real today

- A fail-closed domain model that keeps recorded age, visual morphology, machine outcome, and human review separate.
- An executable FastAPI service backed by SQLite WAL.
- Transactional inspection, audit, and sync-outbox persistence.
- A safe deterministic simulator that is visibly labeled synthetic and never represents a trained CNN or physical device.
- A responsive evidence-workbench dashboard that consumes the local API.
- A Flutter Android workspace matching the web account, Analyze, and History flow; see [Android setup and verification](apps/mobile/README.md).
- Source scaffolds for ESP-IDF, model training/export, and Supabase.
- Automated tests for aggregation, idempotency, local authority, immutable machine results, and leakage checks.
- Downloaded public candling datasets and saved comparisons of exploratory MobileNetV3-Small and DINOv2/ConvNeXt classifiers. Only the retained `selective-v2` classifier weights remain after cleanup. See the [complete accuracy comparison](docs/ACCURACY_RESULTS_2026-09-12.md) and [original training results](docs/TRAINING_RESULTS_2026-09-12.md) for historical results.

### Retained model files

The 2026-10-16 cleanup keeps `selective-v2` as the only fitted classifier, with its
active release at `deployment/releases/automatic-recapture-20260912`. Earlier
classifier weights, candidate heads, obsolete packages, extracted package-test
copies, and generated Android build files were removed at the owner's request.
Historical reports and metrics remain as evidence; their old model-download and
candidate-inference paths are no longer available. Frozen backbone encoders,
development feature caches, manifests, and licenses remain where the retained
training/export tools expect them. Datasets, saved predictions, credentials,
source code, the current Android APK, and `balut-hardened-20261004.zip` are retained.
The local cleanup record is `artifacts/cleanup-20261016/summary.json`; its
post-cleanup verification is `artifacts/cleanup-20261016/verification-after.json`.

## What is not yet proven

The public-source CNN experiments do not establish a validated combined Day-16-like / Day-18-like / reject model. There is no physical ESP32-S3 box, wired interlock, identified 300-egg study, qualified two-reviewer adjudication, prospective device test, or vendor usability evidence in this repository. The software therefore reports `SIMULATOR / SHADOW ONLY` and keeps production readiness blocked.

The system must never be described as certifying an egg as safe, edible, pathogen-free, rotten, disposable, or sellable.

## Run the local vertical slice

Use the bundled or system Python and Node.js:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
npm.cmd install
.\.venv\Scripts\python.exe -m uvicorn balut_api.main:app --app-dir apps\edge_api --host 127.0.0.1 --port 8000
npm.cmd run dev
```

Open `http://127.0.0.1:5173`. The development UI uses the documented local simulator token. Replace all development credentials before any shared-network trial.

## Verify

```powershell
.\.venv\Scripts\python.exe -m pytest
npm.cmd run verify
# Or run both suites plus client secret/banned-claim scans:
.\scripts\verify.ps1
```

Flutter and ESP-IDF builds additionally require their vendor toolchains. Their absence does not convert source inspection into a successful device build.

## Main directories

- `apps/edge_api`: FastAPI, SQLite, simulator, and device-ingestion boundary.
- `apps/web`: React/TypeScript operator and research dashboard.
- `apps/mobile`: Flutter Android application source.
- `firmware`: ESP-IDF state-machine and hardware-port scaffold.
- `ml`: manifest audit, aggregation, training, evaluation, and export contracts.
- `supabase`: PostgreSQL schema, private evidence storage, and RLS.
- `contracts`: shared enum and payload contracts.
- `docs`: operating, hardware, protocol, API, and readiness documentation.
