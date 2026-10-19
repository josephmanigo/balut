# USB box LCD

The identified ESP32 spinner also drives the user's XFP1116-07AY 128x64 OLED.
Wiring: GND to GND, VCC to 3V3, SDA to D25, SCL to D26. The firmware uses U8g2's
SH1106 constructor, compatible with CH1116 displays using an internal charge pump.
It probes I2C addresses 0x3c and 0x3d. The display shows `EGGGRADE IOT`, the current
result or capture state, and a research reminder for classifications.

Install Arduino library `U8g2@2.36.19`. Build `firmware/spinner/ControlledSpinner` with Arduino ESP32 3.3.12 and FQBN
`esp32:esp32:esp32:FlashMode=dio,FlashFreq=40`. Preserve the verified original
flash backup and current application before installing. Write only the application
at `0x10000` after checking the controller MAC and unchanged boot records.
Do not run the original first-install flasher against an already upgraded board.

Use `Connect Cloud Box.cmd` on the prepared laptop with both USB adapters connected.
The Vercel upload response includes an allowlisted `displayLabel` for the signed
USB connector. The connector sends it to the existing spinner serial port.
Browser-only USB capture does not drive this LCD.

- `Day 16`, `Day 18`, or `Reject`: current saved, accepted classification.
- `Unclassified`: uncertain, recapture, paused, missing, or unknown result.
- `Place egg`, `Analyzing...`, or `Save empty view`: current capture state.
- `Offline`: network/USB failure, stopped connector, or 150 seconds without a display update.

The display never substitutes the raw model guess for an abstained result. It
clears the previous egg label when the box rearms. These labels remain research
estimates; `Reject` is not food-safety or sellability proof.

OLED writes run on the other ESP32 core. Motor pins, phase order, 10 RPM setting,
three-view capture, and bounded hold/resume protocol remain unchanged. A missing
LCD does not prevent capture. `LCD <16-hex nonce> <code>` acknowledges the queued
display code; `LCDSTAT <nonce>` reports the last written code and LCD availability.
`BALUT_OLED_INIT` reports initialization status and address. The firmware retries
missing OLED connections every second. A software acknowledgement cannot prove
visible pixels or contrast.

If initialization reports `MISSING`, recheck ground, 3V3, SDA/SCL, and connectors.
Keep the user's 3.3 V wiring. OLED pixels emit light; there is no separate backlight.

Driver references: [module family](https://www.opldisplaytec.com/product/68.html)
and [U8g2 maintainer's CH1116 guidance](https://github.com/olikraus/u8g2/discussions/2031).
