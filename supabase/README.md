# Supabase remote schema

For the current app's shared username/password, model History, and images, use
`migrations/202610170001_shared_workspace.sql` and
[the shared workspace guide](../docs/SUPABASE_SETUP.md). That migration is
standalone and requires no browser Supabase credentials. The older schema
described below belongs to the separate research/synchronization scaffold.

The migration creates the synchronized research records, private evidence
bucket, explicit roles, RLS, append-only evidence/review/audit triggers, model
release constraints, and device/inspection scope helpers.

Important authority boundary:

- Browser and Flutter clients receive only the public project URL and anon key.
- The service-role key belongs only to the trusted laptop synchronization
  worker or a controlled deployment environment.
- ESP32 firmware never contains a Supabase credential.
- No cloud table or function starts motion or illumination.
- Evidence object paths begin with the inspection UUID so the storage read
  policy can apply the same inspection scope.

The migration has not been applied because no Supabase project or credentials
were supplied. Before applying it:

1. Review it in a disposable local Supabase environment.
2. Add an initial admin through an audited bootstrap process.
3. Exercise every role matrix case and storage path.
4. Confirm anonymous, unassigned, operator, reviewer, admin, and service-role
   behavior with automated tests.
5. Never expose the service-role key in Vite, Flutter, or firmware variables.

The sync worker is intentionally not allowed to fabricate a model release or
turn a synthetic inspection into physical evidence.
