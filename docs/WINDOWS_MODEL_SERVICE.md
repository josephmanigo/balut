# Windows laptop model service

The [2026-10-04 hardening report](HARDENING_AND_ACCURACY_2026-10-04.md) is the current software verification. The hardened handoff is `artifacts/balut-hardened-20261004.zip`. Model release `automatic-recapture-20260912` is retained; the new research candidate is not activated. The updated startup checks every shipped class and recapture fixture before serving.

Prepared on 2026-09-12 for the requested **software-first** deployment. The service runs a real trained ONNX model, stores image evidence and prediction records locally, and presents an authenticated browser workflow. Its scope is **automatic appearance classification with recapture**. There is no mandatory human review: unclear images remain unclassified and request another image. Physical egg grading is disabled; the assembled candler and timestamped real-egg dataset have not yet been supplied.

## Use this laptop

For the optional PC/iPhone HTTPS mode prepared on 2026-10-16, see [physical box connection](BOX_CONNECTION_2026-10-16.md). It uses `Start-Balut.ps1 -Phone -Supervise` and a separate private profile; the default loopback mode below remains available.

The prepared service listens at **http://127.0.0.1:8765**. It accepts loopback connections only. On the first visit, choose a username and password, confirm the password, and select **Create account**. Creation signs you in immediately. Later visits use **Sign in** with those same credentials. No terminal command or generated password is needed. After signing in, **Analyze** handles image uploads and **History** shows the latest 50 saved predictions. Technical record details expand on demand. English and Filipino controls are available.

Browser access uses a random, HttpOnly, SameSite=Strict session cookie. Sessions expire after eight hours or a service restart; **Sign out** revokes the current session immediately. The password is not stored in browser storage. The application shell is public; records and operator APIs remain authenticated. Legacy explicit Basic and Bearer API credentials remain supported, but the server no longer sends the Basic challenge that triggers a browser login popup. This HTTP cookie configuration is for the loopback-only service.

If Codex's embedded browser reports `ERR_BLOCKED_BY_CLIENT` or a site-reachability error, open the address in the laptop's normal browser. The embedded browser was observed blocking both the dashboard and the public readiness page while direct local HTTP checks succeeded. In File Explorer, double-click `Open EggGrade IoT.url` in the development workspace to open the address in Windows' default browser. Use `http://`, including port `8765`. A phone or another computer's `127.0.0.1` does not refer to this laptop.

This laptop has one local account. Registration closes once that account exists. Usernames use 3–32 letters, numbers, dots, underscores, or hyphens, begin with a letter or number, and are case-insensitive. Passwords use 12–128 characters; a short phrase is suitable. The database stores a salted scrypt password hash, never the plaintext password. Account creation preserves existing records, and the account survives service restarts.

The private profile is `deployment/private/windows.json`; Windows ACLs limit that directory to the current user and SYSTEM. Its generated credentials and `Copy-Balut-Login.ps1` remain available for legacy API integration only. They are not the browser account password. Private profiles and runtime databases are excluded from the handoff ZIP and source control.

On **Analyze egg**, select a JPEG cropped around one egg and click **Analyze egg**. The single model predicts Day 16, Day 18, or a suspected reject when its gates pass. Otherwise, it displays **Another image needed**, leaves the egg unclassified, and asks for a replacement JPEG. There is no model selector or human review requirement. Each result has a saved record ID. Scores are not calibrated probabilities. Repeated unclear images remain unclassified.

The active release is `automatic-recapture-20260912`. See [the automatic-recapture report](AUTOMATIC_RECAPTURE_2026-09-12.md) for class-specific performance, coverage, and dataset limitations. The 2026-10-16 cleanup removed earlier classifier binaries and obsolete packages; historical reports remain. Only the retained classifier and the `balut-hardened-20261004.zip` handoff remain locally. A rollback to an earlier classifier would require restoring its model, dashboard, and API from a separately held archive.

## Start, stop, and recover

After a reboot, start the service from the workspace:

```powershell
.\scripts\Start-Balut.ps1 -Supervise
```

The supervisor retries unexpected exits at most five times, with increasing delays. Startup rechecks the registry, every model/config/fixture checksum, model input contract, and known-answer outputs. A failed check stops startup. There is no automatic Windows logon task or system service registration; the launcher must be started after reboot. Keep the laptop powered and prevent sleep during a working session.

Logs rotate at 5 MB with five retained log files under `deployment/logs`. Request IDs, method, status, and elapsed time are logged; credentials, image bodies, and arbitrary query strings are not logged. User interface/API predictions persist atomically with an audit event, outbox event, and idempotency record. If inference or evidence storage fails, the API does not return a successful prediction.

`GET /health` is process/model status. `GET /ready` returns HTTP 200 only when storage and configured models are available; `automaticGradingReady` remains false. A ready HTTP service is not physical-candler acceptance. The service uses one ONNX inference slot and rejects concurrent excess work with HTTP 429 and a retry hint; the outer server connection limit can return 503. Clients should retry with the **same Idempotency-Key**. A changed image/model/release with a reused key returns 409.

The current detached process is recorded in `deployment/runtime/service-process.json`. To stop it, verify that the recorded PID still belongs to `balut_api.service_runner` with this workspace's private profile before stopping it; PIDs can be reused. For an interactive launcher, use Ctrl+C.

## Backup and restore

Back up while the service is running. The command takes a consistent SQLite snapshot and copies every referenced, checksum-verified evidence image. The snapshot includes the local account and its password hash, so protect the backup like the database. The manifest reports whether an account hash is included. Private-profile API/device credentials and model weights are excluded; keep the corresponding sealed release separately.

```powershell
.\.venv-serving\Scripts\python.exe scripts\backup_serving.py --profile deployment\private\windows.json --output deployment\backups\my-first-backup
```

Copy the completed backup to separate storage. A backup on the same drive does not protect against drive failure. A failed backup has no completed manifest and cannot be restored through the tool.

Restore into a fresh directory:

```powershell
.\.venv-serving\Scripts\python.exe scripts\backup_serving.py --restore deployment\backups\my-first-backup --output deployment\runtime\restored
```

The tool verifies the manifest, file hashes, SQLite integrity, and foreign keys; it never replaces existing directories. Stop the service, update `database_path` and `evidence_path` in the protected profile to the restored locations, then start and verify readiness and a known saved prediction. Preserve the former data until recovery is confirmed.

## Install the handoff on another Windows laptop

The account-creation UI is available in the current workspace. The existing `balut-hardened-20261004.zip` predates this change and has not been repackaged. For a handoff built from current source, install 64-bit Python 3.12 first. The handoff includes pinned Windows dependency wheels, the built dashboard, hardened source, the retained ONNX model, sealed recapture gates and training references, sample images, checksums, and licenses.

```powershell
.\scripts\Install-Balut.ps1 -PythonExecutable 'C:\path\to\python.exe'
.\scripts\Start-Balut.ps1 -Supervise
```

The start command remains running in that PowerShell window. Open the browser while it runs and create the laptop's account on the first visit.

Dependency installation uses the bundled wheels without an index or internet connection. The initializer creates new credentials for that laptop. Do not copy the originating laptop's private profile. The archive is Windows x64/Python 3.12 specific; it is not an ESP32 or Android package.

To roll back a model set, retain a prior sealed release directory, stop the service, change both the registry path and pinned registry SHA-256 in the private profile, then start it and verify the known-answer checks. There is no HTTP endpoint for arbitrary model upload or activation. A source-label release cannot be turned into an automatic-grading release by changing a UI setting.

## API and device integration

- `GET /api/v1/models` lists loaded source-label models and their hashes.
- `POST /api/v1/egg-analysis` chooses the release's three-class model automatically. It takes the same authenticated raw-JPEG headers as the model-specific endpoint below.
- `POST /api/v1/model-predictions/{model_id}` takes a raw `image/jpeg` body, operator Bearer or Basic authentication, `X-Balut-Origin: local`, and an `Idempotency-Key` of 8–120 characters.
- `GET /api/v1/model-predictions/records/{prediction_id}` retrieves the saved record.
- JPEGs must decode successfully, be at least 32 pixels per side, at most 16 megapixels, and under the 10 MB request limit. Accepted files then pass through development-selected quality, score-margin, and feature-distance heuristics. These gates are not a guarantee of correct classification or validated optical acceptance.
- A recapture result has `sourcePrediction=null`, `analysisOutcome=RECAPTURE_REQUIRED`, `recaptureRequested=true`, reason codes, and `reviewRequired=false`. Classified results use `analysisOutcome=CLASSIFIED`. Both keep physical `operationalUseAuthorized=false`; this does not require human review. Use a new idempotency key for a replacement image; retain the same key only for transport retries of the same input.
- Production mode disables simulator submission, development defaults, API documentation routes, wildcard CORS, and unvalidated device grading authority. Operator data requires authentication; the browser can load the app shell to display the sign-in form.
- `GET /api/v1/auth/session` reports browser session state and whether initial account setup is required. `POST /api/v1/auth/register` accepts `username`, `password`, and `confirmPassword` JSON and creates an account with private history. Signup remains available after initial setup. Duplicate usernames return 409 without changing credentials or other users' sessions. `POST /api/v1/auth/login` accepts the chosen username/password; `POST /api/v1/auth/logout` revokes the session. All three writes require `X-Balut-Origin: local` and reject foreign origins. Login attempts are limited after ten failed attempts within one minute. Cookie-authenticated writes require the same origin safeguards.
- `GET /api/v1/model-predictions?limit=50` lists the signed-in account's newest saved predictions (maximum 100 per request). Record URLs return 404 for another account's prediction. Existing records belong to the original account after migration. The separate research/admin endpoints remain restricted to the original operator or local administrative credential.

Device uploads require HMAC version 2. Set `X-Device-Signature-Version: 2`, `X-Device-Id`, Unix-seconds `X-Device-Timestamp`, and `X-Device-Signature`. The signature is HMAC-SHA256 with the separate device credential over the following UTF-8 prefix, a newline, then `timestamp + '.' + device_id + '.' + raw_body`:

```text
BALUT-HMAC-V2
HTTP_METHOD
URL_PATH
QUERY_STRING_WITHOUT_QUESTION_MARK
Idempotency-Key
Content-Type
X-Image-SHA256_OR_EMPTY
```

The signature binds the request to the route, view, replay key, content type, and image hash. Timestamp tolerance is five minutes. Version 1 remains accepted only in development/test for existing fixtures; update physical firmware before connecting it to this profile. This release does not add a physical camera/motor transport, a reverse proxy, LAN exposure, cloud sync worker, or independent reviewer accounts.

## Verified scope and remaining work

Local tests cover authentication, invalid settings, request limits, route-bound signatures, corrupt models and recapture artifacts, known-answer mismatches, unclassified recapture, persistence, busy inference, and storage failure. Live tests exercised all three predicted classes and two recapture cases, browser upload at desktop/mobile sizes, abrupt process restarts, backup, restore, and retrieval from restored storage. See [the current verification report](AUTOMATIC_RECAPTURE_2026-09-12.md).

The user confirmed that the assembled candler and timestamped images are not available yet. The next phase is hardware integration, the [identified-egg collection](REAL_CANDLING_DATA_COLLECTION.md), an untouched prospective evaluation at the egg/session level, optical/physical safety tests, and embedded int8 validation if grading will run on the ESP32-S3. The existing Android, cloud synchronization, multi-reviewer UI, and firmware remain separate unfinished project surfaces. No software check here establishes physical grading accuracy or food safety.

Implementation references: [FastAPI lifespan resources](https://fastapi.tiangolo.com/advanced/events/), [ONNX Runtime session API](https://onnxruntime.ai/docs/api/python/api_summary.html), and [Python SQLite backup API](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup).
