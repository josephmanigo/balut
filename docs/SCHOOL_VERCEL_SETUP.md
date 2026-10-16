# Balut school defense: Vercel + the USB box

The website runs on Vercel. The Windows laptop runs the trained model, saves records, and reads the camera over USB. Both USB cables stay connected to that laptop. A phone or another computer can open the Vercel website while that laptop and its connector remain running.

```text
Phone / laptop browser → Vercel website → encrypted temporary tunnel
                                             ↓
                                Windows laptop: AI + USB camera
```

## 1. Prepare the school laptop before defense day

1. Use Windows 10/11 **x64**. Copy `Balut-School-Box-20261017.zip` onto the laptop, right-click → **Extract All** to a local folder, for example `C:\BalutSchool`. Run files from the extracted folder. Do not move that folder after first setup; its private profile stores absolute paths. For a different location, extract a fresh copy.
2. Plug in both box USB cables directly. The camera cable carries images; the other cable powers the existing continuous spinner. The firmware is already in the box. No Arduino IDE, Codex, or separate Python installation is needed.
3. Double-click **Start School Box.cmd**. It opens [the local workbench](http://127.0.0.1:8765/). The first run creates a fresh private profile and database. Create a username and a password of at least 12 characters on that page. The current PC's account, passwords, and history are deliberately excluded from this kit.
4. If the camera adapter is missing, run **Install USB Drivers.cmd**, approve Windows' administrator prompt, then unplug/reconnect the USB cables and retry. It installs the included signed FTDI and CP210x drivers. If Python/ONNX reports a missing Microsoft DLL, run `deployment\drivers\vcredist\vc_redist.x64.exe`, then retry. The Microsoft runtime installer may also require administrator approval.
5. Check the live view. With the holder **empty**, camera fixed, and normal candling light on, check the empty-box confirmation and click **Save empty view & start**. Then place one egg and keep hands clear. Remove it before the next egg. If you do not have an egg, leave analysis paused; do not treat empty-holder captures as validation.

The USB camera address is **`http://127.0.0.1:8767`**. The launcher fills it in. Even on the Vercel page, keep this address: it is used by the school laptop's connector, not contacted directly by the phone.

## 2. Create the Vercel project

1. Extract **Balut-Vercel-Source-20261017.zip**. Create a **new, separate Git repository containing the contents of the extracted `BalutVercel` folder**, then import that repository into Vercel. Do not upload the whole development folder or the school kit.
2. Use **Vite** as the framework and leave the project Root Directory at the repository root. `vercel.json` supplies `npm ci`, `npm run build`, output `apps/web/dist`, and the API rewrite. Do not select `apps/web` as Root Directory; the API function is in the repository's root `api` folder.
3. On the school laptop, first create the local account as above, then double-click **Start Vercel Connector.cmd**. This starts the local box and an outbound encrypted tunnel. No router port forwarding is needed. Keep the laptop awake and connected to the internet.
4. Open the generated **Vercel Connection.txt** in the school folder. In Vercel → Project → Settings → Environment Variables, add the following **server-only** variables for **Production**:

   | Variable | Value |
   |---|---|
   | `BALUT_BOX_URL` | The `https://...trycloudflare.com` address from `Vercel Connection.txt` |
   | `BALUT_BOX_KEY` | Run **Copy Vercel Key.cmd**, then paste the copied value here |

   Never prefix these names with `VITE_`. Never put the key in frontend code, Git, a screenshot, or chat. Clear the clipboard after pasting. Enable Preview too only if you intend preview deployments to access the box.
5. **Redeploy** the Vercel project after saving variables. Open its production URL and sign in with the account created on the school laptop. Verify the live preview, a result, and History before the defense. Account creation is available only on the local page; the public connector blocks it.

Vercel's Node function keeps the connector key off the browser. The local gateway permits only sign-in, automatic-camera controls, model information, and history. It does not expose the local administrator token, registration, arbitrary LAN addresses, or the raw USB bridge.

## 3. Each school session

1. Connect both USB cables, internet, and laptop power. Keep Windows awake.
2. Run **Start Vercel Connector.cmd**. If its tunnel has restarted, the temporary URL changes. Update `BALUT_BOX_URL` in Vercel and **redeploy** before opening the production website. The key stays the same for that extracted kit.
3. Sign in, check the preview, then save a new empty view whenever the box, camera, lighting, or service has changed. Test with known-age eggs before presenting classification results.
4. After the session, run **Stop School Box.cmd**. This closes the laptop service and public tunnel. To stop the autonomous spinner, disconnect its power. The app does not command the motor.

If school Wi-Fi blocks the tunnel, try the prepared hotspot. If the cloud connection fails, run **Start School Box.cmd** and present from [the same laptop's local page](http://127.0.0.1:8765/); this fallback needs no internet once the included Windows prerequisites are installed. A phone's `127.0.0.1` points at the phone itself, so this fallback is laptop-only.

## What to verify before defense day

- Rehearse using the **actual other laptop** and the same box/cables. Confirm both USB adapters, the camera preview, continuous spinner, login, known-age egg captures, saved history, and the Vercel production page.
- The camera preserves the current 640×480 USB source, rotation, and slight framing adjustment. The displayed/analysed image is 456×640 after rotation/crop. This hardware does not provide a verified 60 FPS stream.
- The model gives **appearance estimates**: Day 16, Day 18, suspected Reject, or an unclassified recapture request. It does not prove incubation age or food safety. The current release remains `SOURCE_LABEL_SHADOW_ONLY`; prospective accuracy on physical eggs in this box has not been validated.
- Cloudflare Quick Tunnels are for testing, provide no uptime guarantee, and change hostname on restart. This is suitable for a rehearsed defense demo with the local fallback. A permanent service should use a stable named tunnel and a separate deployment review.
- Public Vercel deployment and testing on the actual school laptop still need to be completed. The prepared kit is not evidence those steps have passed. The earlier Android APK uses a different local address; this kit does not rebuild or verify that APK. Use the Vercel browser page on phones.

## Troubleshooting

| Problem | Next step |
|---|---|
| Camera unavailable / adapter missing | Check the camera USB cable; install included drivers; reconnect; close other programs using that camera COM port. Any COM number is accepted for this identified camera adapter. |
| Port already used | Stop other Balut copies. Run only one extracted school kit at a time. |
| Missing Microsoft DLL | Install the included signed `vc_redist.x64.exe`, then retry. |
| Vercel says connector not configured | Check both environment variable names, Production scope, and redeploy. |
| Vercel says box offline | Keep laptop awake; check internet and tunnel log; update changed URL and redeploy. |
| Sign-in expired | Sign in again. Service restarts clear sessions but preserve the local account and records. |
| Preview works but no correct result | Check normal lighting, focus, egg position, and empty-view calibration. An unclear image may request recapture. Do not claim accuracy from an empty box. |

Logs are in `deployment\logs`. Credentials and account data are in `deployment\private` and `deployment\runtime`; keep the extracted kit private after first use. The distributed ZIP contains neither.

## Sources and included components

- [Vercel Node.js functions](https://vercel.com/docs/functions/runtimes/node-js) and [rewrites](https://vercel.com/docs/rewrites).
- [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/): temporary hostname and testing limitations.
- [ONNX Runtime installation requirements](https://onnxruntime.ai/docs/install/) and [Microsoft VC++ runtime](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist?view=msvc-170).
- [Astral portable Python builds](https://docs.astral.sh/uv/concepts/python-versions/): included Python 3.12.15 x64 with pinned dependencies. Python and package licenses are retained in the runtime.
- [FTDI](https://ftdichip.com/drivers/) and [Silicon Labs CP210x](https://www.silabs.com/software-and-tools/usb-to-uart-bridge-vcp-drivers). This same-box handoff includes the signed FTDI driver package exported from this PC, CP210x package, and vendor license files. Use the official vendor/Windows Update route if Windows declines installation.
- cloudflared 2026.10.1, official Windows x64 release. Binary SHA-256: `4d2490e74082c5d48dbfedaf92576fa5bd1702379ab88eb7faa0cfbe8dc891b6`. Its license and source metadata are included.

Each ZIP includes `file-hashes.json`; it covers every payload file, excluding that inventory itself. Keep a clean original ZIP for moving to a new laptop.
