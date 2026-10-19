# Faster camera preview and removal response

The target is the public EggGrade IoT workspace and its running USB capture computer.

The camera connector previously read and transferred two complete JPEGs for every preview, discarding the first, then waited for the cloud upload before acquiring again. The replacement continuously acquires checksum-validated full-resolution images on one camera thread, discards only the initial queued sensor frame, and keeps only the newest waiting image during uploads. Stale queued images are rejected. Corrupt images are discarded rather than uploaded. Camera acquisition remains exclusive during the existing three-angle motor hold sequence; that sequence still uses fresh held views and resumes rotation before upload.

A full-scene match to the confirmed empty reference now rearms normal capture on the first matching frame after removal. The weaker holder-shape match still needs two consecutive frames. Reconnects still require two empty matches; a new reference still needs three fresh stable frames and explicit confirmation that the box is empty. Connected cloud status polls every 500 ms, including the removal state, instead of returning to 1500 ms polling after a result.

## Physical measurements

The identified camera remained at 800x600, 921600 baud, and the existing JPEG settings. All accepted timing samples passed CRC and full JPEG decode. No firmware, exposure, model, capture threshold, or motor configuration was changed.

| Path | Measured acquisition time |
| --- | --- |
| Previous two-JPEG preview | 3.625, 4.609, 4.625 seconds; median 4.609 seconds |
| Continuous single-JPEG preview | 2.313, 2.172, 2.234, 2.078, 2.063, 2.406 seconds; median 2.203 seconds |
| Newest preview after a simulated five-second upload wait | Available immediately; no acquisition wait |
| Observed updates reaching the live cloud row | 2.285, 2.299, 2.330 seconds apart |

An initial timing attempt rejected a corrupt USB frame. A subsequent complete timing run had no rejected baseline frames. These results do not establish that the electrical or driver cause of intermittent corruption is repaired. This camera still produces individual JPEG snapshots, so these measurements do not support a zero-latency or video-frame-rate claim.

## Calibration and verification

The user confirmed an empty box. Its previous reference did not match the actual empty image and caused an unnecessary capture. A fresh confirmed reference restored `waiting`. Later the camera direction changed substantially; the user confirmed moving it and subsequently fixing it in place while empty. A new reference was requested after that confirmation. References are never learned from arbitrary occupied frames.

Regression coverage includes immediate full-match rearming, retaining two-frame fallback and reconnect checks, continuous acquisition through upload waits, dropping older queued images, CRC-error recovery, exclusive three-view camera access, durable prediction recovery, and existing authentication boundaries. The final isolated API suite passed 235 tests. The web build and 55 web tests passed. After the second confirmed reference settled, live state returned to `waiting`, calibrated and connected. Physical removal-to-ready acceptance must use that fixed camera position and the deployed code; a software replay alone is insufficient.

Local measurements and live reference checks are saved under `output/camera-response-20261019/`. They are excluded from the public repository.

## Final live acceptance and restart recovery

The user tested the deployed page and reported: "Ready returns quickly; preview feels better." The observation window did not independently record a result-to-removal cycle, so there is no measured end-to-end removal latency claim.

The final audit caught a stopped connector after an authentication/clock rejection. Fresh signed probes passed authentication; the original rejection was not reproduced and its cause remains unconfirmed. Windows reports an unsynchronized time service, and the attempt to resynchronize returned access denied. The device signature and clock validation were retained.

Restarting the connector exposed a reproducible separate issue: the identified camera port opened but never answered `CAPTURE`. The Python opener did not perform the application reset and ready handshake already used by the browser. A camera-only RTS reset, with DTR held false, reached `BALUT_USB_READY` in 5.250 seconds and produced a CRC-checked, fully decoded 800x600 JPEG. The shared Python opener now performs that same startup sequence, waits at most 16 seconds, and closes the port on timeout or sensor startup failure. It does not command the spinner or rewrite firmware.

With the corrected opener running on the capture laptop, the final check observed 19 distinct cloud frames over 46.358 seconds. The median interval between observed frame updates was 2.339 seconds. The last state was `waiting`, enabled and calibrated, with no reconnect-empty requirement, pending capture, or error. The connector remained running, with no further authentication rejection during that check.

After integrating the concurrent signup release, the API suite passed 242 tests, the web suite passed 57 tests, and the production web build passed. Public JavaScript and CSS bytes matched that build; readiness and session checks returned 200, and unauthenticated box status remained protected with 401. The measured preview remains snapshot-based; the exclusive three-angle capture still takes longer than an ordinary preview.
