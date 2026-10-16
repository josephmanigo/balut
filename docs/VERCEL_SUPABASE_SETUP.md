# Balut: Vercel website and AI, Supabase records

Vercel runs the website and the existing ONNX model. Supabase stores the existing
account, hashed browser sessions, history, private evidence images and camera state.
The USB laptop sends signed camera frames. It must stay connected only while
capturing; viewing history and signing in do not depend on that laptop.

## Deploy from GitHub

1. Import `josephmanigo/balut`, branch `main`, root directory `./`.
2. Use the **FastAPI** framework preset. Keep the commands from `vercel.json`.
   The install command installs both Node and Python dependencies. The build
   assembles the hash-checked model chunks and builds the website.
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

## Connect the USB box

Use `Connect Cloud Box.cmd` on the laptop attached to the camera. On first use it
asks for the deployed HTTPS `vercel.app` URL. It reads the device secret from
`deployment/private/cloud-device.json`. Copy only this device profile to another
capture laptop; do not copy the Supabase secret or Vercel environment file.

Leave the connector running, open Analyze on any signed-in device, remove the egg,
wait for three fresh frames, confirm the box is empty, and save the empty view.
Keep the camera and lighting fixed. After placing one egg, a steady scene change
triggers one saved analysis. Remove the egg before placing the next one.

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
