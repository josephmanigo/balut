# Android UI and preview APK — 2026-10-14

The Flutter Android app now follows the production web workspace: a normal account form, Analyze, and History. Paper, forest green, amber accents, serif headings, short instructions, and optional record details carry across both surfaces. Android uses native Material controls, photo selection, secure session storage, system dark mode, and adaptive phone/tablet layouts.

## Deliverable

- APK: `artifacts/Balut-Android-0.2.0-preview.apk`
- Package: `ph.capstone.balut_operator`
- Version: `0.2.0`, build `2`
- Size: 52,960,504 bytes (50.5 MiB)
- SHA-256: `af2551a78286c6262e1630ea48832a03b4b0b4ac03047f4c75901419dbd11d25`
- Minimum Android API: 24. Target/compile API: 36.
- Architectures: ARM64, ARMv7, x86-64.
- Optimized release build, signed with the Android **debug key** for preview use. `apksigner verify` passed with APK Signature Scheme v2. This is not a production-signed store release.

## Behavior

Account creation is available when the connected server has no local account. After setup, use the same username/password as the web app. The current server supports one local workspace account; this change does not introduce multiple users. Android saves only the server address and session cookie in platform secure storage. Changing servers clears the session. Sign-out revokes it; expired sessions return to sign-in.

Analyze accepts one JPEG up to 10 MB. It previews the image, sends the real model request, preserves an idempotency key across retries for that selection, and presents either an appearance estimate or a recapture request. History loads the most recent 50 server records. Research-only authority is checked before displaying a class. Image analysis, records, and accounts remain on the server.

Only HTTPS origins or HTTP loopback are accepted. Requests do not follow credential-bearing redirects. The Android network configuration also restricts cleartext traffic to loopback. The current Windows service is loopback-only, so a phone needs a USB development bridge or a separately deployed HTTPS backend. See [connection and build instructions](../apps/mobile/README.md). Public hosting, offline inference, physical device controls, and iOS are outside this delivery.

## Verification

| Check | Result |
| --- | --- |
| Flutter static analysis | Passed, no issues |
| Unit and widget tests | 15 passed |
| Optimized Android APK build | Passed, including release lint |
| APK identity and signature | Verified with `aapt` and `apksigner` |
| Native Android API 35 emulator | APK installed and launched |
| Account creation | Created test account through native form on isolated server |
| Native photo picker | Selected a real candling JPEG through Android picker |
| Model analysis | Day 16 returned and saved, including a repeat check with final preview APK |
| History | Both isolated test records displayed |
| Sign-out and sign-in | Passed, including sign-in on final preview APK |
| Session persistence | Final preview reopened after force-stop without another login |
| Native visual checks | Phone light/dark; 130% text; tablet split layout; short landscape login with scrollable fields |
| Widget layout checks | 320×700, 700×320, 1100×800, and 1000×420 at 130% text |
| Android error log | No Flutter error or AndroidRuntime error output during the checked session |
| Existing Windows records | All 18 original prediction records unchanged, verified by count and digest |

The native test server used `tmp/android-ui-verification/test.db`, the existing retained ONNX model, and port 8766. Emulator port 8765 was reversed to that isolated service. Two prediction records were created there; no test account or image record was added to the live Windows database.

The image was the existing retained release fixture `deployment/releases/automatic-recapture-20260912/egg-grade/day_16.jpg`. This proves API integration and rendering, not new model accuracy, biological age, food safety, or physical candling acceptance.

Machine-readable results: [.impeccable/review/android/verification.json](../.impeccable/review/android/verification.json).

## Native screenshots

These are Android emulator captures, not browser mockups. Initial create-account, light phone Analyze/History, and phone login captures were taken from the debug build; the result, dark-mode, tablet, and landscape captures include the final optimized preview build.

- [Create account](../.impeccable/review/android/create-phone.png)
- [Phone login](../.impeccable/review/android/login-phone.png)
- [Phone Analyze](../.impeccable/review/android/analyze-phone.png)
- [Day 16 result](../.impeccable/review/android/result-phone.png)
- [History](../.impeccable/review/android/history-phone.png)
- [Dark Analyze at 130% text](../.impeccable/review/android/analyze-phone-dark-130.png)
- [Dark History at 130% text](../.impeccable/review/android/history-phone-dark-130.png)
- [Tablet Analyze](../.impeccable/review/android/analyze-tablet.png)
- [Tablet login](../.impeccable/review/android/login-tablet.png)
- [Landscape login after scrolling](../.impeccable/review/android/login-landscape-130-scrolled.png)

## Build environment and remaining acceptance

Validated with Flutter 3.47.7 / Dart 3.13.5, Android build tools 36.0.0, NDK 28.2.13676358, and Java 17. The reproducible entry is `scripts/Build-BalutAndroid.ps1`. It temporarily works around the Windows app-host Java socket issue, runs analysis/tests, builds, copies the APK, and prints its digest. The toolchain is installed outside the repository; SDK paths remain local configuration.

Flutter currently warns that the legacy Kotlin Gradle plugin needs migration for future Flutter versions. The pinned current build succeeds. The build uses Gradle 9.3.1, Android Gradle Plugin 9.1.0 and Kotlin 2.4.0; keep this compatibility set together until migration is tested.

Physical-phone installation, camera/photo-provider variations, TalkBack acceptance, full Filipino localization, production signing, and public backend deployment have not been verified. Preview checks are not app-store acceptance. The app implements lost-photo-picker recovery, but Android activity destruction during selection was not forcibly exercised.

The bundled serif face comes from [Google Fonts Libre Caslon Text](https://github.com/google/fonts/tree/main/ofl/librecaslontext); its SIL Open Font License is included in `apps/mobile/assets/fonts/OFL.txt`.
