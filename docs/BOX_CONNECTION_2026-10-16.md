# Physical box connection — 2026-10-16

## Current status — 2026-10-17

Later on 2026-10-17, the separate spinner controller was updated to continuous forward rotation at the user's request. The original full flash was preserved, the written application was verified, and the user confirmed continuous rotation. See [spinner diagnosis and installed fix](SPINNER_DIAGNOSIS_2026-10-17.md). Earlier statements below that motor firmware remains unchanged describe the camera-connection phase.

The deployed workflow uses **USB through the browser** at [Balut AIoT](https://balutaiot.vercel.app). Chrome or Edge reads the FTDI camera after first-use permission and uploads validated JPEGs to Vercel. Supabase stores the shared account, history, images, sessions, and camera state. No local Python bridge is needed for this workflow. The local launcher and LAN addresses below describe the earlier local workflow.

The installed GC2145 profile uses **800x600, JPEG quality 90, 10 MHz XCLK, and 921600-baud USB serial**. SVGA uses the full sensor window, approximately 25% wider and taller than the previous VGA window. The faster startup firmware is installed and flash-verified, with application SHA-256 `b47c35a9b72ace2a359b487749a4edb229adcc2df9613d70cbda6ed8080e2e9f`. Firmware readiness measured **5.218 seconds**, down from **11.016 seconds**. Six real JPEGs passed CRC and full decode; the initial exposure still takes several frames to settle. See [camera quality and verification](CAMERA_QUALITY_2026-10-17.md). The earlier 20 MHz setting produced half-sized frames and remains excluded.

The current shared pipeline rotates captures **90 degrees counterclockwise**, placing the light at the bottom as requested. The subsequent speed/full-view update removes the former 5% left crop. Web/Android previews and automatic analysis receive the same **600x800** image, without stretching or upscaling. The website accepts both earlier 640x480 source frames and new 800x600 frames, and resets calibration when source dimensions or framing change. The wider field comes from the camera's sensor mode; digital cropping cannot reveal an area outside the captured image.

Web and Android are automatic only. Their previews refresh before calibration and while analysis is paused. The web client polls cloud status every 1.5 seconds and local status every 250 ms; polling does not create additional camera frames. The quality-first feed delivers approximately one image every 1.7 seconds in the tested scene, not 60 fps. Two consecutive changed frames with low motion trigger one saved analysis; a third consecutive changed frame triggers capture even while the holder rotates. Removing the egg rearms capture after three empty frames. Results retain the existing appearance-only Day 16 / Day 18 / suspected Reject / unclassified-recapture policy. This is not a validated egg-presence detector.

The USB camera build does not load or include Wi-Fi credentials. `Build-BoxCamera.ps1 -CompileCheck` compiles without uploading; `Flash-BoxCamera.ps1` still checks the original backup and exact camera identity before uploading. The Wi-Fi build instructions and authentication failures below describe earlier attempts and are superseded by USB operation.

The automatic-only update passed 40 focused backend tests and six web workflow tests. Android analysis and 18 tests passed, and a new preview APK was built. Android includes only the public Balut Local Box certificate; certificate and hostname validation remain enabled. An actual Dart HTTPS request with that certificate passed, while an empty trust store rejected it. Physical Android installation is still pending.

Existing accounts and saved predictions were preserved; expected box configuration changes are separate. A pre-update backup is `deployment/backups/before-live-preview-20261017.db`. Evidence is under `output/box-connection-20261016`.

After camera tuning, automatic analysis remains paused and the old empty reference has been cleared. The latest view is dark and does not yet clearly frame the holder. Check physical position, focus, and normal candling light, then save a fresh empty reference before testing a real placement/removal cycle. Spinner firmware was separately updated and user-confirmed as described above; the camera work does not change its control.

The following sections retain the earlier network setup and diagnostic history.

The user subsequently deferred mobile setup until an Android phone is available. Continue the physical camera connection through the web app. The temporary iPhone certificate/setup server on port 8770 has been stopped. The existing HTTPS web workspace remains running; no additional iPhone firewall exception is authorized or needed for this phase.

## Identified hardware

- Camera: user-confirmed AI-Thinker ESP32-CAM, FTDI adapter on COM3. Read-only chip identification reports ESP32-D0WD-V3 revision 3.1, 4 MB flash, MAC `38:3e:51:c2:95:60`.
- Separate controller: CP2102 adapter on COM4. Installed Silicon Labs driver 11.3.0.176 from Espressif's official installer mirror; its catalog has a valid Microsoft Windows Hardware Compatibility Publisher signature. The existing controller emits `Forward` and `Reverse` messages. No motor commands or replacement motor firmware were sent.
- The original camera firmware continually reported `WiFi connecting`. The user initially supplied SSID `.`, then confirmed it is a 5 GHz-only network. This ESP32 requires 2.4 GHz. Wi-Fi passwords must be entered locally, never in reports or chat.

## PC and iPhone workspace

The existing Flutter package supports Android. The iPhone uses the same web workspace in Safari, optionally added to its Home Screen.

An opt-in HTTPS profile is saved at `deployment/private/windows-phone.json`. It uses the original database, model, evidence, and account. Start it with:

```powershell
.\scripts\Start-Balut.ps1 -Phone -Supervise
```

Stop the existing service before switching between the default loopback mode and phone mode. The launcher rejects a second instance against these profiles.

Current HTTPS origin: `https://192.168.2.2:8765`. The service binds only that address. It validates the exact HTTPS origin, retains authentication and cross-site protections, rejects non-local clients, and marks session cookies Secure. Proxy headers remain disabled. No router port forwarding or public hosting was configured.

The one-time setup page at `http://192.168.2.2:8770` serves only `deployment/phone-setup`. It contains a public root certificate and iPhone instructions, never credentials or server keys. The root certificate is named **Balut Local Box**. The server certificate expires on 2027-10-16. The root signing key was discarded; the server key remains in the protected private directory. If the PC's IP changes, certificates and the phone profile must be regenerated and the iPhone trust updated.

Apple requires installing the downloaded certificate profile and then enabling full trust under Settings > General > About > Certificate Trust Settings. After opening Balut, Safari's Share > Add to Home Screen provides the iPhone launcher. See [Apple certificate instructions](https://support.apple.com/en-us/102390) and [Apple web app instructions](https://support.apple.com/guide/iphone/open-as-web-app-iphea86e5236/ios).

The PC is on `192.168.2.2/24`; the iPhone initially reported `192.168.1.83`. A trace from the PC reaches the phone through `192.168.2.1`. This does not prove that the phone can initiate connections to the PC. The firewall exception allows only `192.168.2.0/24` on TCP 8765 and 8770. An additional exception for exactly `192.168.1.83` was prepared, but its Windows administrator prompt was canceled. The user then chose to connect the iPhone to the PC router's Wi-Fi instead; do not reopen the canceled firewall prompt. The existing rule covers the intended `192.168.2.x` phone address. Do not claim iPhone acceptance until its page and authenticated workflow load on the physical phone.

## Camera firmware preparation

`firmware/camera/BoxCamera/BoxCamera.ino` is a separate Arduino target for the identified AI-Thinker camera. It does not replace the ESP32-S3 research scaffold or control the motor or lights. It supplies JPEGs at `/capture`, matching the existing web and Android connection API, and runs a sensor/JPEG self-check before starting the server. Native-JPEG sensors use 640x480. The actual sensor identifies as **GC2145, PID 0x2145**, with PSRAM present; it requires the tested RGB565-to-JPEG fallback at **320x240**.

`scripts/Build-BoxCamera.ps1 -CompileCheck` compiles using dummy Wi-Fi credentials; that binary must not be flashed. The normal build reads locally saved, Windows-encrypted Wi-Fi credentials and places the generated header, build log, and binary under `deployment/private/camera-build`. The resulting firmware binary also contains the Wi-Fi credentials and must remain private.

The local Wi-Fi popup uses Windows DPAPI directly and stores base64 ciphertext. Its earlier `ConvertTo-SecureString` call failed when Windows PowerShell inherited the app host's module paths. The replacement was tested in that same popup process environment, including JSON round-trip and decryption from the camera-build process. Save errors now leave the form open with a controlled message.

`scripts/Flash-BoxCamera.ps1` verifies the full original backup, requires the locally saved Wi-Fi details, checks the exact COM3 adapter and camera MAC, builds with the real credentials, then uploads at 115200 baud with esptool's flash verification. It has completed successfully. The first physical startup rejected native JPEG; the updated firmware's RGB565 conversion passed its actual sensor/JPEG self-check. The network diagnostic scan did not find `.` on 2.4 GHz and reported disconnect reason 201. The user confirmed the network is 5 GHz-only; a reachable 2.4 GHz network is the remaining provisioning input.

The user then supplied 2.4 GHz network **`p`** and entered its password locally. The camera sees `p` on channel 1 at approximately -70 dBm, with WPA2 authentication. The router rejects authentication with reason **202 (`WIFI_REASON_AUTH_FAIL`)**. The saved password, generated C++ string, and compiled firmware bytes were checked and match. The local credential window was reopened to verify or correct the network password before further router troubleshooting. No live HTTP camera address has been obtained yet.

Toolchain: Arduino CLI 1.5.2-rc.1, Espressif Arduino core 3.3.12, and esptool 5.6.0 in the isolated `.venv-hardware` environment. The compile check uses 1,016,237 bytes of program space and 57,640 bytes of globals.

Continuous original-flash backup attempts at 460800 and 115200 baud failed integrity checks. Reading at 115200 baud in 64 KB chunks succeeded: every transfer's digest was verified, then the complete 4,194,304-byte backup matched the device's whole-flash MD5. The final file also passed a disk SHA-256 check.

The original is preserved at `deployment/private/camera-backup/original-20261016.bin`, with `manifest.json` beside it. SHA-256: `1abaae44a87743d29ce1c8f9c2d7c698d4d29cdf9ed8bce9e15dacc00b983076`. Treat the backup as private: it may contain the previous Wi-Fi credentials. Replacement camera firmware has been installed and verified at 115200 baud. The separate motor controller remains unchanged.

## Verification at this checkpoint

- 32 HTTPS/authentication/production tests and 16 existing automatic-box tests passed. Warnings concern existing library deprecations and pytest cache permissions.
- The real HTTPS `/ready` and application shell return HTTP 200 with certificate verification enabled. One retained model loads; `automaticGradingReady` remains false.
- The public certificate downloads with the correct certificate content type.
- The camera's full original flash is backed up and verified. Real-credential firmware builds and flash verification passed. The current application image SHA-256 is `d2d7b167a22852b8847b3ef7cc15b4fb43947578a8e33616618c8fb3f0f58d66`.
- A pre-change database/evidence backup is in `deployment/backups/before-phone-20261016`. All database tables, including 18 saved predictions and the account, matched after switching to HTTPS.
- The user confirmed an empty box, fixed camera, and normal candling light for calibration. The camera's JPEG self-check passes. Its Wi-Fi connection, HTTP image capture, and placement cycles await successful authentication to the visible 2.4 GHz network `p`. Mobile setup is deferred. Spinner smoothness is a separate hardware/firmware issue.
