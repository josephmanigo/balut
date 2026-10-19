# EggGrade IoT Android workspace

The native Flutter Android app follows the current web workspace: account creation/sign-in, **Analyze**, and **History**. It uses the same authentication, model and prediction endpoints as the web app. This replaces the older device/review simulator screens.

## What matches the web

- Paper and forest-green palette, amber accents, serif headings, short copy, and an egg/scanner identity.
- First-workspace account creation, normal sign-in, password visibility and confirmation, session expiry, and sign-out.
- Automatic-only camera capture, a continuously refreshed preview, shared results, and empty-box calibration. The photo picker has been removed in version 0.4.0.
- Automatic analysis, explicit recapture, and the latest 50 saved predictions.
- English/Filipino main controls, native Android touch controls, system dark mode, phone/tablet layouts and keyboard insets.

Android uses bundled Libre Caslon Text for the web's serif character; Georgia is not redistributed. Font source: https://github.com/google/fonts/tree/main/ofl/librecaslontext. The SIL Open Font License is included in `assets/fonts/OFL.txt`.

## Connection

The current 0.4.0 box preview APK is built for `https://192.168.2.2:8765` and includes the public Balut Local Box certificate, with normal chain and hostname verification. Connect an Android phone to the PC router network and sign in with the web account. The PC must keep this address; changing its certificate requires rebuilding the certificate asset. Physical-phone setup remains pending. The earlier loopback/USB instructions below apply when running the separate default loopback service profile.

For the user's iPhone, use the web workspace in Safari. This repository does not currently contain an iOS native target. The optional local HTTPS setup, certificate installation, and current hardware status are documented in [physical box connection](../../docs/BOX_CONNECTION_2026-10-16.md).

The model, account, and records live on the connected EggGrade IoT server. Android stores the server address and session cookie in platform secure storage; it does not store the password or maintain a separate account database. Changing servers clears the session. Android backups are disabled for the app.

The current Windows service is loopback-only. For a USB development connection, enable USB debugging on the Android device, connect it to this laptop, and run:

```powershell
adb -s DEVICE_SERIAL reverse tcp:8765 tcp:8765
adb -s DEVICE_SERIAL install -r artifacts/Balut-Android-0.4.0-preview.apk
```

Start the existing Windows service, then open **EggGrade IoT** on the device. The default address is `http://127.0.0.1:8765`. Sign in with the same account used in the web app. No password-copy command or pairing token is needed.

For a deployed server, choose **Your workspace** on the account screen or **Change server** on the connection screen. Enter the HTTPS origin. Public hosting still requires backend deployment changes; changing this app setting does not expose the local Windows service. Cleartext HTTP is allowed only for loopback USB testing. Requests do not follow redirects with credentials.

## Build and verification

Validated toolchain versions and runtime evidence are recorded in [the Android verification report](../../docs/ANDROID_UI_2026-10-14.md). The local Flutter SDK is installed at `C:\balut-dev\flutter`; Android SDK at `C:\Users\My Pc\.cache\balut-tools\android-sdk`. The Unity-provided JDK is reused without modifying the Unity installation.

From the repository root:

```powershell
.\scripts\Build-BalutAndroid.ps1
# Other installations:
.\scripts\Build-BalutAndroid.ps1 -FlutterExecutable 'C:\flutter\bin\flutter.bat' -Server 'https://balut.example.com'
```

The script resolves dependencies, runs Flutter analysis and tests, then produces an optimized preview APK. The preview uses the Android debug signing key; configure a private release key before public distribution.

The Windows desktop app host can cause Java AF_UNIX selector failures. The build script scopes a Java socket-directory override to its child processes so Java uses TCP fallback. It restores the caller's environment afterward.

All 18 unit/widget tests pass, including authentication, research-only result validation, account confirmation, history errors, automatic-only layouts, changing live previews while analysis is paused, and certificate loading. The optimized 0.4.0 preview APK is built with the Android debug key. Earlier emulator evidence is recorded separately in [automatic camera setup and verification](../../docs/AUTOMATIC_BOX_2026-10-14.md). The current box USB feed and web preview have been verified on this PC; physical Android installation, real egg framing/placement cycles, and TalkBack acceptance remain pending.
