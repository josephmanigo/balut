# Automatic ESP32-CAM capture

## Current USB cloud flow (2026-10-17)

The deployed USB flow supersedes the original LAN setup below. After recognizing
the confirmed empty reference, placement starts a three-view scan automatically.
The camera captures three fresh views at least 1.5 seconds apart while the holder
rotates independently. Keep the same egg in place until the saved result appears.
The UI shows capture progress; no manual start or capture button is required.
These are timed views, not measured angles or verified full-turn coverage.
Empty recognition accepts the calibrated lower holder's shape despite background
or exposure changes. Two consecutive matching uploads return the box to Ready;
the shape check also requires contrast to reject black or washed-out frames.

Each view passes the unchanged sealed model's quality and uncertainty gates.
At least two distinct accepted JPEGs must agree, and any accepted contradictory
view forces recapture. Repeated identical JPEGs do not count as separate votes.
The result keeps each view's evidence hash and decision; raw model scores are
never presented as a combined probability. One scan creates one history record.
The policy is `three-timed-views-v1`; it has not been validated for biological age.

Partial scans persist between Vercel requests. Removal, pause, reconnect, framing
change, or a scan exceeding 20 seconds cancels the partial set and requires an
empty-box recheck. Completed sets persist before inference and retry with the
same identity. Legacy single-image pending captures remain recoverable.
Cloud state and all three evidence images use the existing Supabase storage.

Three views add capture time. The previously measured camera takes about two
seconds per JPEG; this change does not provide 60 FPS. Exposure tuning is a
separate firmware and physical-image check. Actual Day 16/Day 18 accuracy still
requires held-out eggs with verified incubation records.

## Original LAN flow

The web and Android apps now offer **Automatic** and **Attach photo** inside Analyze. Automatic mode uses the laptop to watch the ESP32-CAM snapshot endpoint, process a steady scene change, and save the result. Both clients read the same camera state and prediction history.

**Status:** software implemented and tested with an isolated camera feed and the real retained model. The user's ESP32-CAM address, firmware, lighting, and physical detection behavior have not been tested. No presence sensor or lid switch was confirmed.

## Connect once

1. Put the laptop and ESP32-CAM on the same local network. The camera must serve a fresh JPEG from `http://CAMERA_IP/capture`.
2. Open **Analyze > Automatic > Box setup** in either app. Enter the camera origin, such as `http://192.168.1.50`, and choose **Connect camera**. Use the actual address assigned to your camera.
3. Leave the box empty, with the camera fixed and normal candling lighting in place. Confirm **The box is empty** and choose **Save empty view & start**.
4. Place one egg in the holder, clear your hands, and hold the scene steady. A result appears automatically and is saved to History.
5. Remove the egg. Once the empty view is recognized, the next placement can start a new capture. Use **Attach photo** whenever you want to select a JPEG manually.

The official Espressif [CameraWebServer example](https://github.com/espressif/arduino-esp32/tree/master/libraries/ESP32/examples/Camera/CameraWebServer) exposes `GET /capture`; this route was verified in its [HTTP server source](https://github.com/espressif/arduino-esp32/blob/master/libraries/ESP32/examples/Camera/CameraWebServer/app_httpd.cpp). The correct board pin mapping and Wi-Fi configuration still depend on the installed ESP32-CAM module. Do not flash this repository's ESP32-S3 research scaffold onto an unidentified ESP32-CAM. This change does not flash or modify device firmware.

## What automatic means here

- The server compares the center of each image with your saved empty reference. It compensates for uniform exposure changes and waits for three steady changed frames before capturing.
- It saves one result per placement. Three frames matching the empty reference rearm capture. Polling normally waits one second between requests; actual delay also includes camera/network and model time.
- The box can keep processing while both apps are closed, provided the Balut server is running and automatic mode is enabled. **Pause** stops automatic capture; manual upload remains available.
- Configuration, the empty reference, the placement latch, latest result ID, and pending capture identity persist in SQLite. A pending image reuses the same idempotency key after interruption to avoid duplicate records.
- Unclear images remain unclassified. Remove the egg, improve its position or lighting, and place it again for another capture. Manual attachment is also available.

Scene change is a heuristic, not a trained egg-presence detector. Hands, other objects, a shifted camera, shadows, or changing illumination can trigger it or prevent reset. Keep the holder centered and recalibrate after changing camera position or lighting. A presence sensor remains the more reliable trigger once the actual hardware wiring is known. This feature does not operate motors, illumination, sorting, or lid mechanisms. Research estimates do not establish chronological age or food safety.

## Connection and storage

The laptop fetches camera images over the LAN. The web app and Android app communicate with the Balut server, not directly with the camera. Results, account data, evidence, and camera configuration are stored on that server. Supabase is not required for this local workflow.

The current Windows server still listens only on `127.0.0.1:8765`. An Android USB development bridge is described in [the mobile guide](../apps/mobile/README.md). A remote HTTPS deployment must also have a network path to the camera, such as a local gateway or private tunnel; a public server cannot reach a home's private camera address by itself. Public deployment and physical-phone acceptance are separate work.

Only authenticated local operators can configure or read the box. Camera addresses must be literal private IPv4 HTTP/HTTPS origins, without credentials, paths, query strings, or fragments. Snapshot requests use the fixed `/capture` route, do not follow redirects or environment proxies, require JPEG responses, limit downloads to 10 MB, and enforce connection/total timeouts. Self-signed HTTPS certificates are not bypassed.

Endpoints:

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/v1/box/status` | Cached camera state, preview, and latest result |
| POST | `/api/v1/box/connect` | Connect with `{ "cameraUrl": "http://PRIVATE_IP" }` |
| POST | `/api/v1/box/reference` | Calibrate with `{ "emptyConfirmed": true }` |
| POST | `/api/v1/box/enabled` | Pause/resume with `{ "enabled": false/true }` |

Mutations use the same authenticated local-presence boundary as manual analysis. Automatic results use the existing prediction, audit, evidence, and outbox pipeline with `captureSource: "iot_box"`. The legacy physical-device readiness gate remains false.

## Verified software

- Backend: 79 tests passed, including 16 new automatic-box cases covering origins, exposure shifts, steady capture, removal/rearm, restart, pending retry, pause, invalid images, redirects, authorization, and empty-box confirmation. After reusing the shared JPEG decoder, all 16 automatic-box tests passed again.
- Web: 15 tests passed; TypeScript and the production Vite build passed. Automatic status, calibration, polling, offline handling, and manual attachment remain covered.
- Android: static analysis passed and all 16 tests passed, including automatic results without selecting a file, authentication, retry identity, manual flow, and layouts at 130% text. The release-mode preview APK built successfully.
- Runtime: an isolated service on port 8766 used a uniform empty frame and the saved `day_16.jpg` candling fixture as a simulated camera transport. The real retained model produced saved Day 16 research estimates. Removal and reinsertion produced a second record; holding the same scene did not repeatedly save. Web and Android displayed the shared results and history. This is model/software evidence, not physical-box acceptance.
- Visual captures cover desktop/phone web and phone/tablet Android, plus the Android manual-attachment surface. Captures in `.impeccable/review/automatic` use the isolated test feed; the egg image is not a live image from the user's box.

Android package: `ph.capstone.balut_operator`, version `0.3.0+3`.

Preview APK: [Balut-Android-0.3.0-preview.apk](../artifacts/Balut-Android-0.3.0-preview.apk). This optimized preview uses the Android debug signing key. It is not a store-signed release.

SHA-256: `6C20F97A293C76E3ABBE8DF5BD4328805457A613BA4DA01E1210EB79B1E3184E`.

The existing production database was backed up before the service update. All 18 predictions and the account were preserved byte-for-byte at the row level. The local service reports `serviceReady: true` and `automaticGradingReady: false`; authenticated box status succeeds and an unauthenticated request is rejected. Record and account preservation checks are recorded in `.impeccable/review/automatic/live-checks.json`. No test camera, test account, or synthetic result was added to production.

The independent UI review requested removal of one redundant web label. That fix was scored resolved with disposition `ship`; this verdict covers the listed fix, not physical hardware acceptance. Package, signing, build, test, and review evidence is summarized in `.impeccable/review/automatic/verification.json`.

## Physical acceptance still required

Confirm the actual camera address and JPEG endpoint, then test multiple empty/occupied cycles under normal lighting. Check false triggers, missed placements, removal/rearm, camera disconnect/reconnect, and an unclear-image retry. If lighting changes between empty and occupied scenes, correct the lighting/reference or add a reliable presence sensor before relying on automatic capture.
