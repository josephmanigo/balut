# Balut: Vercel website and AI, Supabase records

Vercel runs the website and the existing ONNX model. Supabase stores the existing
account, hashed browser sessions, history, private evidence images and camera state.
The USB laptop sends signed camera frames. It must stay connected only while
capturing; viewing history and signing in do not depend on that laptop.

## Deploy from GitHub

1. Import `josephmanigo/balut`, branch `main`, root directory `./`.
2. Use the **FastAPI** framework preset. Leave the **Install Command** override
   disabled so Vercel installs Python dependencies from `requirements.txt` and
   optimizes the function bundle. Keep the build command from `vercel.json`; it
   installs Node dependencies, builds the website, and assembles the hash-checked
   model chunks. A custom install command disables Vercel's bundle optimization.
3. Add these variables to **Production**, with no `VITE_` prefix:

   | Name | Value |
   | --- | --- |
   | `SUPABASE_URL` | Your project's HTTPS URL |
   | `SUPABASE_SECRET_KEY` | The project's server secret, beginning `sb_secret_` |
   | `BALUT_DEVICE_SHARED_SECRET` | The generated secret in the protected camera profile |

   On the prepared laptop, run `python scripts/prepare_vercel_env.py` with the
   serving Python environment. Import the resulting `deployment/private/vercel.env`
   into Vercel's environment-variable form. That file is private: never commit it,
   put it in a public archive, or paste it into chat. No OpenAI API key is used.

4. Keep Vercel's **system environment variables enabled**. The backend uses
   `VERCEL_PROJECT_PRODUCTION_URL` to accept only the project's public production
   address. An explicit `BALUT_CLOUD_ORIGIN=https://name.vercel.app` can override it
   if needed. Preview URLs are intentionally not accepted as alternate origins.
5. Deploy, then visit the production domain. `/ready` must return status 200,
   `serviceReady: true`, and one loaded model. Sign in with the existing Balut
   username and password and confirm the same History on another device.

The local admin token is generated internally and is never accepted for cloud
requests. Supabase secrets stay in the Python backend. Anonymous and authenticated
Supabase API clients cannot read the Balut tables or evidence bucket.

## Connect the USB box directly from the website

On the computer attached to the camera, open the deployed website in Chrome or
Edge, sign in with the existing account, and open **Analyze**. Click
**Connect USB camera** and select the box camera's FTDI USB serial port in the
browser picker. The website reads the existing camera protocol and uploads JPEGs
using the signed-in browser session. No ZIP, Python, camera profile, device secret,
or Supabase key needs to be copied to this computer. Windows still needs to detect
the USB serial adapter; check the data cable and driver if the picker is empty.

After the browser saves permission for that computer and website, the page checks
authorized camera ports on sign-in and when USB is plugged in, and connects
automatically when exactly one matching adapter is available. A new computer,
revoked permission, or a cleared browser profile requires the USB picker again.
Manual Disconnect remains paused until Connect is clicked again or the page is
reopened. The browser cannot silently grant first-use USB permission.

Keep the website tab open and the computer awake and online. Other signed-in
phones and laptops can view the same camera and history. Remove the egg, wait
for three fresh frames, confirm the box is empty, and save the empty view.
Keep the camera and lighting fixed. After placing one egg, a steady scene change
triggers one saved analysis. Remove the egg before placing the next one.

Each browser connection starts a new camera session. On opening USB, the browser resets only the
camera into its application and waits up to 16 seconds for `BALUT_USB_READY`.
Boot output is discarded before requesting a JPEG; an unfinished startup never
reaches analysis. The camera firmware is not rewritten.

Every new connection requires a fresh empty
view before automatic analysis. JPEG size, dimensions, USB CRC, session, origin,
rate, idempotency, and shared camera lease checks remain enforced. Closing the
page or signing out stops its USB capture. No motor or lighting commands are sent.

The existing `Connect Cloud Box.cmd` remains an alternative for a prepared laptop.
It uses `deployment/private/cloud-device.json`; copy only this device profile if
moving that connector to another laptop. Never copy the Supabase server secret.

Capture runs inside each frame-upload request; there is no cloud background loop.
A database lease prevents two Vercel instances from changing capture state at the
same time. Durable pending images and event keys recover interrupted analysis.
A camera gap longer than 12 seconds requires a fresh empty reference. Requests
are limited to 120 seconds; the lease expires after 150 seconds if a worker dies.
No motor or lighting commands are sent.

## Phones and other laptops

Open the production URL in any phone or laptop browser. No project files are
required for viewing the website. The existing Android app also supports a
custom HTTPS server address in its connection settings; set it to the same
production URL and sign in again. Its older camera-setup copy may still show a
camera address, but use the fixed USB connector address `http://127.0.0.1:8767`
there. Browser camera setup provides the current cloud instructions.

## Persistence and limits

The migrated account password is unchanged. Browser login sessions last eight
hours and logout revokes that session across instances. The workspace remains
one shared account, matching the original app; it is not a multi-tenant service.
Login attempts are limited across instances to ten per minute.

Internet and available provider quotas are required. Every accepted prediction
requires cloud storage to succeed; there is no silent local-only fallback.
Session loss, a Vercel restart, or changing laptops does not delete stored history.
Supabase account deletion, manual data deletion, quota limits and provider outages
remain external conditions; keep the protected SQLite migration backup.

The pinned model remains a research appearance classifier. Software validation
does not establish physical egg accuracy, incubation age, food safety or physical
camera acceptance. A successful provider build alone does not prove login,
inference or shared history on the live site.
