# Render free demo: website + AI + USB camera

This is the selected deployment target. Vercel and public laptop tunnels are not required.

For a shared account and persistent history/images, complete
[the Supabase setup](SUPABASE_SETUP.md) before deploying the current blueprint.
The two Supabase variables keep records outside Render's temporary filesystem.
The temporary-history warnings below describe deployments without Supabase.

```text
Camera USB → Windows laptop connector → signed HTTPS frames → Render AI + website
                                                                ↑
                                                     Phone / laptop browser
```

Keep both USB cables plugged into the box laptop. It needs internet while the camera is used. The spinner keeps using its existing firmware; the web app does not command the motor. The camera does not need the school's Wi-Fi password because the laptop uploads its USB frames.

## Free plan limits you accepted

- Render's free web service can sleep after 15 minutes without inbound traffic. Open the website and wait for startup before a demonstration.
- Its local files are erased on restarts, redeployments and sleep. **Without Supabase, history and saved evidence are temporary.** With Supabase configured, completed results, images, and the account persist there; local camera calibration still resets. The website labels the active storage mode.
- Your account is recreated from protected environment settings after a reset. Sessions expire on restart; sign in again and save a new empty view.
- Free compute is limited to 512 MB RAM and shared CPU. Local software tests do not prove that this exact model stays within Render's memory and startup limits. Verify the live deployment's logs and metrics before the defense. No paid resource is configured by the supplied blueprint.
- The model remains `SOURCE_LABEL_SHADOW_ONLY`: Day 16, Day 18, suspected Reject, or unclassified recapture. It does not prove age or food safety. Testing with known-age physical eggs in this box is still required.

## 1. Prepare your account on the Windows box laptop

1. Extract `Balut-School-Box-20261017.zip` to a local folder, such as `C:\BalutSchool`. Use the extracted files, not files inside the ZIP.
2. Run **Prepare Render Account.cmd**. Choose a username and a password of 12–128 characters. Password entry stays hidden. Do this once; do not generate a different camera secret on the second laptop without updating Render too.
3. The helper creates protected `deployment\private\render-env.txt` and `render-device.json`. Open `render-env.txt` locally when entering settings in Render. It contains four values: username, salted password hash, a separate administrator credential, and camera signing secret. The plaintext password is not saved. Do not put these files in Git, upload them with the source ZIP, or send them in chat.

No Python installation or Arduino IDE is required. The kit contains Python, the model and dependencies. If an adapter is missing, run **Install USB Drivers.cmd**. If a Microsoft DLL is missing, install the included `deployment\drivers\vcredist\vc_redist.x64.exe`.

## 2. Create the Render service

1. Extract `Balut-Render-Source-20261017.zip`. Create a new private GitHub repository containing the contents of its `BalutRender` folder. Upload the extracted files, including the model chunks. Do not upload the ZIP itself or the development workspace. All model chunks are below 25 MB for GitHub's browser upload limit.
2. In Render, create a new **Blueprint**, connect that repository, and use `render.yaml`. It defines **one free Docker web service**, one worker and readiness checks. No database or disk charge is configured.
3. Enter the four environment values from the protected local file exactly:

   | Name | What it contains |
   |---|---|
   | `BALUT_OPERATOR_USERNAME` | Your chosen username |
   | `BALUT_OPERATOR_PASSWORD_HASH` | The complete generated `scrypt$...` value |
   | `BALUT_LOCAL_ADMIN_TOKEN` | A separate generated secret; public administrator-token login is disabled |
   | `BALUT_DEVICE_SHARED_SECRET` | The signing secret matching the laptop connector |

4. Deploy. The Docker build reconstructs the model from chunks and verifies its sealed SHA-256, builds the website, installs the pinned API dependencies, and starts one server. Render supplies `RENDER_EXTERNAL_URL` and `PORT` automatically. Do not invent a localhost value for either.
5. Open the assigned `https://...onrender.com` address. Sign in with your chosen username and original password. Public account registration is blocked. If startup fails, inspect Render's build/deploy logs; do not switch to a paid plan unless you choose to accept that cost.

An alternative manual service must use Docker runtime, Free plan, this repository's Dockerfile, `/ready` as the health check, and the same four environment values. The frontend is served by the API from the same address; no CORS or separate Vercel URL is needed.

## 3. Connect the USB box

1. Connect both USB cables. Close other applications using the camera COM port. Stop any running local camera bridge with **Stop School Box.cmd** from that same kit. Only one program can open the camera adapter.
2. Run **Connect Render Box.cmd**. On first run, paste your `https://...onrender.com` website address. The connector stores it privately and uploads fresh signed camera frames over HTTPS. Keep its window open. Press Ctrl+C to stop and release the camera. Do not use a URL from a different Render service.
3. Open your Render website from the laptop or phone and sign in. The preview should say **Camera connected**. The laptop needs internet, but a phone viewing the public page can use a different internet connection.
4. Keep the camera fixed and normal candling light on. Empty the holder. Confirm the empty view, then select **Save empty view & start**. Place one egg and keep hands clear. Remove it before the next one.

The camera address shown in Box setup remains `http://127.0.0.1:8767` as the connector's fixed identity. Render does not contact that laptop address; signed uploads supply the frames. Changing it to a random LAN address cannot make the cloud server access your school network.

The connector identifies this box's FTDI adapter on any COM number, reconnects after a USB interruption, and never sends motor commands. The server rejects altered signatures, old timestamps, duplicate keys with different bytes, invalid JPEGs, excessive frame rates and stale frames. After a long camera interruption, it pauses analysis and requires a new empty view. Sync Windows time if the camera authentication reports a clock error.

## 4. Rehearse before the defense

1. Verify the actual Render URL, sign-in, live preview, normal lighting, and known-age egg results on the **actual school laptop**.
2. Confirm a result appears once, stays in History while the server runs, and the next egg requires removal of the previous egg.
3. Unplug/reconnect the camera to check recovery and the new empty-view requirement. Confirm the spinner's continuous rotation separately.
4. Keep the laptop awake and online. Start the Render service before presenting; free startup can take time.
5. Keep the local offline fallback ready: stop the Render connector with Ctrl+C, run **Start School Box.cmd**, and use `http://127.0.0.1:8765/` on that laptop. It uses a separate local account and database. Cloud history is not automatically copied to it.

If preparing on this PC but demonstrating on another laptop, privately transfer the same `render-device.json` into the other kit's `deployment\private` folder. Keep your environment settings protected as well. Do not copy the entire current PC profile or database. Running the account helper on the destination protects its private directory; preserve the original matching device settings.

## Evidence boundary

The source and Windows artifacts are prepared software. A passing local test, ZIP checksum or build does not prove a successful Linux Docker build, Render deployment, camera transport over school Wi-Fi, or physical-egg accuracy. Complete those checks before claiming deployment acceptance. The existing native Android APK is not rebuilt for Render by this package; use the browser page on phones.

## Primary documentation

- [Render FastAPI deployment](https://render.com/docs/deploy-fastapi), [Docker services](https://render.com/docs/docker), [Blueprint configuration](https://render.com/docs/blueprint-spec).
- [Render free limits](https://render.com/docs/free), [compute plans](https://render.com/docs/compute-plans), [environment variables](https://render.com/docs/environment-variables), [health checks](https://render.com/docs/health-checks).

The `file-hashes.json` in each ZIP inventories all payload files. Private credentials and operating data are excluded. Keep a clean ZIP for moving to another laptop.
