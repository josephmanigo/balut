# Shared EggGrade IoT account, history, and images

The backend can store its existing single workspace account and completed model
predictions in Supabase Postgres, with images in the private `balut-evidence`
bucket. A Render restart no longer removes these records when this mode is
configured. Browsers and phones use the same deployed EggGrade IoT URL and existing
username/password. They do not receive any Supabase secret.

This preserves the existing username and scrypt password hash; it does not
replace login with Supabase Auth or add multiple unrelated user accounts.
Browser sessions expire after a backend restart; sign in again to see the same
history. Camera calibration and unfinished camera state stay with the backend
and must be reset after a restart. The separate research simulator tables are
outside this shared model-workbench migration.

## Create the project

1. Create a new Supabase project in your own organization. Select a free project
   if available; do not upgrade or accept charges as part of this setup.
2. Apply `supabase/migrations/202610170001_shared_workspace.sql` in its SQL editor
   or through the authenticated Supabase integration. This migration is
   standalone; do not apply the older research schema for this workbench.
3. Confirm the three `balut_*` tables have RLS enabled and no `anon` or
   `authenticated` table grants. Confirm `balut-evidence` is private.
4. Obtain the project HTTPS URL and a server-only secret key from the project's
   API settings. Keep the key out of Git, chat, screenshots, frontend variables,
   mobile apps, and distributed ZIP files.

## Preserve this PC's account and history

Store the following JSON locally as `deployment/private/supabase.json`. The
existing private directory is protected by the Windows profile setup. Supply
real values locally, never in chat:

```json
{
  "url": "https://YOUR-PROJECT.supabase.co",
  "secret_key": "YOUR-SERVER-ONLY-SECRET-KEY"
}
```

Stop the current EggGrade IoT backend before the final copy, so it cannot create new
records during migration. Run from the repository root:

```powershell
.\.venv-serving\Scripts\python.exe scripts\migrate_supabase.py
.\.venv-serving\Scripts\python.exe scripts\migrate_supabase.py --apply
```

Without `--apply`, the tool makes a consistent protected SQLite backup and checks
every record's idempotency metadata and image hash. With `--apply`, it copies the
existing account, uploads each image before its record, and reads everything
back for verification. It preserves prediction IDs and dates. Rerunning after
an interruption is safe. A different existing cloud account or conflicting
record stops migration instead of replacing it. The original SQLite database
is not edited. Retain the backup and images until the full cloud rehearsal passes.

## Connect the hosted backend

Set these **server-only** Render environment variables, then deploy the updated
source:

| Variable | Value |
|---|---|
| `SUPABASE_URL` | Your project HTTPS origin, without a trailing slash |
| `SUPABASE_SECRET_KEY` | The project's secret key |

Keep the existing Render username/password-hash/admin/device settings. Once the
shared account exists, it takes precedence over the bootstrap account settings.
Never prefix either Supabase variable with `VITE_`. Missing one variable blocks
startup; an inaccessible database or public evidence bucket fails readiness.
If neither variable is set, the existing SQLite mode remains active and the UI
continues to label Render history as temporary.

Use the same website URL on every laptop and phone. The existing USB connector
still uploads to Render. Browser clients need no local files and no Supabase
credentials. The current Android APK must target that same backend to see the
same records; the phone browser already uses the website URL.

An owner-controlled local backend can read the same protected `supabase.json`
next to its Windows profile. Do not distribute this administrative secret with
the school kit. Ordinary users should access the hosted backend instead.

## Verify before relying on it

1. Confirm migration verified every source record and image, and sign in using
   the original account from two separate browser sessions.
2. Confirm both sessions see the same prediction IDs and timestamps.
3. Analyze an egg, verify its record exists in Supabase and its image is private,
   then restart Render. Sign in again and check both old and new history.
4. Interrupt Supabase access in a test environment. History/readiness must fail
   visibly, and no new result may be reported as successfully saved locally.
5. Keep a separate backup policy. Cloud persistence protects against Render
   filesystem resets; it does not prevent account deletion, operator mistakes,
   quotas, or provider outages.

Implementation uses the installed HTTP client, Supabase's REST API and private
Storage. No new runtime dependency is required. See [API keys](https://supabase.com/docs/guides/getting-started/api-keys),
[database functions](https://supabase.com/docs/guides/database/functions), and
[Storage access control](https://supabase.com/docs/guides/storage/security/access-control).
