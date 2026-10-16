# Camera quality and speed — 2026-10-17

## Installed wider-view profile

At the user's request to zoom out, the GC2145 RGB565 fallback now captures
**800x600** with software JPEG quality **90**, the same 10 MHz clock, one frame
buffer, and 921600-baud USB. In the installed SDK's subsampling mode, Espressif's
[GC2145 driver](https://github.com/espressif/esp32-camera/blob/master/sensors/gc2145.c)
uses a 1600x1200 sensor window for SVGA instead of VGA's 1280x960 center window.
This provides approximately 25% more width and height from the same fixed mount.
The existing rotation and slight rightward framing remain; preview and analysis
now receive **570x800** images. This changes captured field of view, rather than
merely shrinking the image on the page.

The exact camera identity and preserved original flash were checked before
installation. Esptool verified the written firmware; application SHA-256 is
`eba77a4321c2671808f74be19a032469a3dcf67ac5702e11e75316ef5555034b`.
The previous working VGA application and its boot files are preserved under
`deployment/private/camera-backup/before-wide-view-20261017`.

Three real USB JPEGs passed CRC and full decoding at 800x600. Capture times were
2.094, 1.719 and 1.672 seconds, with 33,820–39,452 bytes per image. Startup reached
`BALUT_USB_READY` in 11.031 seconds, within the browser's 16-second timeout.
The diagnostic closed the camera port without uploading images or creating
prediction records. Evidence is under `output/camera-wide-view-20261017`.

The full backend test suite passed, including both supported USB sizes, rejection
of unsupported sizes, and requiring a new empty reference when source dimensions
change. These images confirm the wider capture, not physical classification
accuracy. The egg remains very bright in the observed lighting. Remove it and save
a fresh empty reference before testing analysis. Spinner firmware is unchanged.

## Earlier quality profile and measurements

The user's final preference was high image quality to help classification, rather than maximum frame rate. The retained profile uses GC2145 RGB565 capture at **640x480**, software JPEG quality **90**, a 10 MHz sensor clock, one frame buffer, and 921600-baud USB serial. It supplies four times the pixels of the original 320x240 / JPEG85 / 115200-baud profile. No Wi-Fi credentials are included in this camera build.

The user subsequently requested the light at the bottom of the view, then a slight rightward framing adjustment because the physical camera cannot be moved. The shared camera pipeline rotates each validated capture 90 degrees counterclockwise and trims the leftmost 5% of the oriented image before preview, scene comparison, evidence storage, and analysis. The resulting image is **456x640**, without stretching or upscaling, encoded at JPEG quality 95 without chroma subsampling. This shifts the visible framing within the existing field of view; it cannot reveal anything outside the sensor's image. Preview bounds accommodate portrait images up to 800 pixels per side. Both web and Android consume the same prepared preview without a client rebuild. The existing empty reference was already cleared and analysis remains paused.

Initial rotation verification passed 33 focused backend/USB tests and observed four distinct, fully decoded 480x640 frames. After the framing adjustment, all 33 tests passed again, including asymmetric color strips verifying the left crop and identical preview/analysis bytes. Five live status checks observed four distinct 456x640 frames, and the signed-in web page visibly showed the adjusted image with the light at the bottom. Evidence is under `output/camera-rotation-20261017` and `output/camera-framing-20261017`.

The shared backend preserves validated small JPEGs without another compression pass. Other previews are bounded to 800x600 and JPEG quality 90, replacing the earlier 400x300 / quality 70 preview. EXIF-oriented images are normalized before preview generation. Web and Android poll every 250 ms, and retain their existing guards against overlapping requests and stale updates. A polling rate is not the camera's actual frame rate.

The USB bridge rejects incorrect length, CRC32, or JPEG markers. It retries a rejected capture once and returns an unavailable response if the retry also fails. The backend allows the bridge's two bounded five-second attempts. Both clients allow 45 seconds for box actions, covering three calibration frames and the bounded lock wait. Damaged frames are never passed to analysis. Live bridge logs also show actual rejected frames being retried.

## Measurements

- Installed 640x480 / JPEG90 / 921600 profile: **30 accepted JPEGs in 49.864 seconds, 0.602 fps**. All 30 fully decode at 640x480. One initial CRC failure was discarded and its retry passed. Median accepted capture time was 1.614 seconds; maximum was 3.244 seconds.
- The installed profile also delivered **10 distinct 640x480 preview images in 16.110 seconds** through the authenticated HTTPS API, with no final error. The signed-in web page visibly showed the connected live view.
- Original 320x240 / JPEG85 / 115200 profile: six valid captures, 0.749 fps in that scene.
- Earlier speed trial, 320x240 / JPEG90 / 921600: **40 accepted JPEGs in 17.980 seconds, 2.225 fps**. All 40 fully decode at 320x240. One initial CRC failure was discarded and its retry passed. Median accepted capture time was 0.434 seconds; maximum was 0.864 seconds. Live checks observed 30 distinct images in 15.109 seconds at 500 ms polling, then 36 in 15.219 seconds at 250 ms polling. This is not the final installed resolution.
- Other 640x480 trials were slower at lower baud rates: roughly 0.31–0.58 accepted fps in the tested scenes before retry support.
- A 230400-baud trial failed all eight captures. Corruption also occurred at other rates. The physical cause was not isolated; these experiments do not establish a particular cable or adapter fault.

Scenes changed while the user positioned the camera, so these are measured operating examples, not a controlled sensor benchmark or a guaranteed minimum frame rate. The current USB serial connection and software JPEG conversion do not deliver 60 fps. Espressif documents that GC2145 lacks native JPEG output and that RGB capture stresses the original ESP32; its example recommends QVGA or below for non-JPEG capture on that chip. See the [official camera driver](https://github.com/espressif/esp32-camera).

## Verification and preserved state

- Firmware compile, exact COM3 device identity check, and esptool write verification passed. Installed application SHA-256: `c2510ca9ab7d74318a9ced7d81deafe2fa0db2c7f2ead12891008222731c904e`.
- 32 focused backend and USB tests passed, including corrupt-frame retry, retry exhaustion, native preview preservation, bounded large previews, and EXIF orientation.
- Six web workflow tests and the production TypeScript/Vite build passed.
- Android analysis and all 18 tests passed. Preview APK 0.4.1+5 built successfully: `artifacts/Balut-Android-0.4.1-preview.apk`, SHA-256 `f33c09b084c67de259c7d237802daf8189c71710cc60c1281079ddc47ebcd620`. Android v2 signature verification passed. It uses the debug preview signing key; physical Android installation is still pending.
- Database rows match the pre-tuning backup exactly in every table except the expected `box_workspace` configuration change. Accounts and saved prediction records are unchanged.
- Original working firmware and bridge are preserved under `deployment/private/camera-backup/usb-qvga-20261017`. The pre-tuning database is `deployment/backups/before-camera-quality-20261017.db`.

Evidence and all measured trials are under `output/camera-quality-20261017`, including `verification.json`, `vga90-921600-final.json`, `live-verification.json`, and `web-preview-quality.png`. The earlier speed trial is retained in `qvga90-921600.json`, `verification-speed-profile.json`, `live-fast-verification.json`, and `web-preview-fast.png`.

## Remaining physical checks

The user has no egg available for this session. Software settings and empty views cannot confirm physical focus on an egg or classification accuracy. Automatic analysis remains disabled, with the old reference cleared. When an egg is available, position the fixed camera and normal candling light, inspect the egg in the live view, then remove it and save a fresh empty reference before enabling automatic analysis. These camera changes do not validate biological age estimates or physical egg detection.

The separate spinner remains on its user-confirmed continuous rotation firmware. No spinner command or firmware change was made during camera tuning. Android physical installation remains pending until a phone is available.
