# Balut at school: website and USB camera

The current deployment runs the AI on Vercel and saves the shared account,
history, images, sessions and camera state in Supabase. The computer connected to
the camera reads its USB images through the website. Bring the box, both USB data
and power cables, a charger, and a computer with internet and Chrome or Edge.

## First use on a school computer

1. Plug in both box USB cables and turn on normal candling light. Windows must
   detect the camera's FTDI USB serial adapter. The other board powers the
   existing spinner; the website sends no motor or lighting commands.
2. Open [Balut AIoT](https://balutaiot.vercel.app), sign in with the existing
   account, and open **Analyze**.
3. Click **Connect USB camera** and select the camera's FTDI USB serial port.
   The browser requires this permission on each new computer/browser profile.
   No project ZIP, Python, camera profile or secret needs to be copied.
4. Wait for the camera preview. Remove the egg and keep the camera and lighting
   fixed. The box checks its saved empty view and shows **Ready for an egg.**
   There is no save-empty-view or start button in the cloud website.
5. Place one egg and keep hands clear. Wait for the saved result, then remove
   the egg before the next one. Confirm the result appears in **History**.
   Capture uses two steady changed frames, or three changed frames if the holder
   keeps rotating. It does not wait indefinitely for rotation to stop. Network
   transfer and AI analysis add time after capture. Image quality checks can
   still request another view.

## Later use

With USB permission saved, the signed-in page automatically checks the available
camera on startup and when USB is connected. Exactly one matching adapter must
be available. Keep this tab open and the computer awake and online. A fresh
connection checks the saved empty view automatically. Three fresh matching frames
return the box to Ready without a setup click. The current box already has a
confirmed empty view stored in Supabase, shared across computers. Manual Pause
stays paused until Resume is clicked. Manual Disconnect pauses reconnection
until Connect is clicked or the page is reopened.

Keep camera position and normal candling light unchanged. A replacement camera,
changed framing, or changed lighting needs a new confirmed reference during box
maintenance. A missing reference displays **Camera calibration needed**; the app
never assumes that an arbitrary still image is empty. The authenticated
`POST /api/v1/box/reference` maintenance endpoint remains available and requires
`emptyConfirmed: true` after a person checks the physical box. The earlier local
LAN interface retains its calibration controls. Neither is part of normal cloud
operation.

Phones and other laptops can open the same website, sign in, and view the camera
and shared history. Only the computer physically connected to the camera captures
images. First-use USB permission and a missing OS driver cannot be silently
skipped by the website.

The capture computer shows each CRC-checked USB frame directly, before cloud
upload or AI processing completes. Only the newest waiting frame is retained
for the next upload, with one upload at a time; shared viewers still use cloud
previews. This removes network and inference waits from the local preview, but
does not change the camera's measured 1.750–2.359 seconds per JPEG. This serial
camera does not provide 60 FPS. A 60 FPS goal requires a different camera and
video transport; software interpolation is not additional captured detail.

## If the camera is not listed

Check the USB data cable and Windows Device Manager. Close any serial monitor or
other program using the camera port. If the FTDI driver is missing, use Windows
Update or the signed driver provided in the school kit, subject to the school's
administrator permissions. School device policies can also block Web Serial.
Use a permitted computer and a working internet connection; a phone hotspot can
provide internet if school Wi-Fi is unavailable.

The existing desktop Connect Cloud Box.cmd is an alternative on a prepared
computer. It requires deployment/private/cloud-device.json and can keep the
camera running without the website tab. Keep that file private and never copy
the Supabase secret to a school computer.

## Optional local fallback for a prepared kit

The full Balut-School-Cloud-20261017.zip includes a Windows x64 Python runtime,
local AI, USB drivers and a separate offline workbench. Extract it completely,
connect the box, and run **Start School Box.cmd**. Use the local page at
[127.0.0.1:8765](http://127.0.0.1:8765/). Its local account and records are separate
from the Supabase account and cloud history. It does not make the public website
work offline. Use only one program to read the camera USB port at a time.

## Verification boundary

Browser protocol and authenticated upload tests are software evidence. Rehearse
on the actual school computer with the box before presenting. Confirm USB
permission, a live preview, empty-view calibration, a real capture, saved history
and viewing from a phone. Model outputs remain research appearance estimates;
physical egg accuracy and food safety are not established by deployment or tests.

[Web Serial browser behavior](https://developer.chrome.com/docs/capabilities/serial)
explains the required first-use picker and access to previously authorized ports.
