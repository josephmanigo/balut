begin;

create extension if not exists pgcrypto;

create type public.app_role as enum ('OPERATOR', 'REVIEWER', 'ADMIN');
create type public.inspection_outcome as enum (
  'DAY_16_LIKE',
  'DAY_18_LIKE',
  'REJECT_SUSPECT',
  'REVIEW_RECAPTURE'
);
create type public.inspection_state as enum (
  'CREATED',
  'CAPTURING',
  'EVALUATING',
  'COMPLETED',
  'SAFE_STOPPED',
  'UPLOAD_PENDING',
  'REVIEW_REQUIRED'
);
create type public.human_disposition as enum (
  'CONFIRMED_DAY_16',
  'CONFIRMED_DAY_18',
  'CONFIRMED_REJECT_SUSPECT',
  'RECAPTURE_REQUIRED',
  'UNRESOLVED'
);

create table public.user_roles (
  user_id uuid not null references auth.users(id) on delete cascade,
  role public.app_role not null,
  created_at timestamptz not null default now(),
  primary key (user_id, role)
);

create table public.devices (
  device_id text primary key,
  display_name text not null,
  credential_fingerprint text not null unique,
  firmware_version text,
  active_model_release_id uuid,
  created_at timestamptz not null default now(),
  disabled_at timestamptz
);

create table public.device_assignments (
  device_id text not null references public.devices(device_id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (device_id, user_id)
);

create table public.incubation_batches (
  batch_id uuid primary key,
  supplier text,
  incubator_id text,
  incubator_entry_at timestamptz not null,
  breed_line text,
  protocol_version text not null,
  notes text,
  created_at timestamptz not null default now()
);

create table public.physical_eggs (
  physical_egg_id uuid primary key,
  batch_id uuid not null references public.incubation_batches(batch_id),
  external_label text not null,
  registered_at timestamptz not null default now(),
  unique (batch_id, external_label)
);

create table public.model_releases (
  model_release_id uuid primary key,
  release_name text not null unique,
  model_sha256 text not null check (model_sha256 ~ '^[0-9a-f]{64}$'),
  input_width integer not null check (input_width in (96, 128)),
  input_height integer not null check (input_height in (96, 128)),
  color_order text not null check (color_order = 'RGB'),
  normalization text not null,
  class_order jsonb not null check (class_order = '["DAY_16_LIKE","DAY_18_LIKE","REJECT_SUSPECT"]'::jsonb),
  quantization jsonb not null,
  quality_gate_version text not null,
  threshold_version text not null,
  dataset_manifest_sha256 text not null check (dataset_manifest_sha256 ~ '^[0-9a-f]{64}$'),
  validation_report_sha256 text not null check (validation_report_sha256 ~ '^[0-9a-f]{64}$'),
  firmware_min text not null,
  firmware_max text not null,
  rollback_model_id uuid references public.model_releases(model_release_id),
  created_at timestamptz not null,
  approved_at timestamptz,
  approved_by uuid references auth.users(id),
  check ((approved_at is null) = (approved_by is null))
);

alter table public.devices
  add constraint devices_active_model_fk
  foreign key (active_model_release_id) references public.model_releases(model_release_id);

create table public.inspections (
  inspection_id uuid primary key,
  device_id text not null references public.devices(device_id),
  batch_id uuid references public.incubation_batches(batch_id),
  physical_egg_id uuid references public.physical_eggs(physical_egg_id),
  state public.inspection_state not null,
  started_at timestamptz not null,
  completed_at timestamptz,
  recorded_elapsed_hours numeric(8,2),
  expected_view_count smallint not null default 8 check (expected_view_count = 8),
  valid_view_count smallint not null check (valid_view_count between 0 and 8),
  firmware_version text not null,
  model_release_id uuid references public.model_releases(model_release_id),
  threshold_version text not null,
  schema_version text not null,
  canonical_record_sha256 text not null check (canonical_record_sha256 ~ '^[0-9a-f]{64}$'),
  evidence_mode text not null check (evidence_mode in ('PHYSICAL_DEVICE', 'SYNTHETIC_DEMO_ONLY')),
  device_timestamp timestamptz not null,
  laptop_received_at timestamptz not null,
  created_at timestamptz not null default now(),
  check ((batch_id is null and physical_egg_id is null) or (batch_id is not null and physical_egg_id is not null))
);

create table public.view_frames (
  frame_id uuid primary key,
  inspection_id uuid not null references public.inspections(inspection_id) on delete restrict,
  view_index smallint not null check (view_index between 0 and 7),
  target_angle_degrees numeric(6,2) not null check (target_angle_degrees >= 0 and target_angle_degrees < 360),
  object_path text not null,
  image_sha256 text not null check (image_sha256 ~ '^[0-9a-f]{64}$'),
  byte_size bigint not null check (byte_size > 0),
  width integer not null check (width > 0),
  height integer not null check (height > 0),
  quality_flags jsonb not null default '[]'::jsonb,
  probabilities jsonb not null,
  valid boolean not null,
  capture_authority text not null,
  created_at timestamptz not null,
  unique (inspection_id, view_index),
  unique (inspection_id, image_sha256)
);

create table public.machine_results (
  inspection_id uuid primary key references public.inspections(inspection_id) on delete restrict,
  outcome public.inspection_outcome not null,
  confidence numeric(7,6) not null check (confidence between 0 and 1),
  class_margin numeric(7,6) not null check (class_margin between 0 and 1),
  view_agreement numeric(7,6) not null check (view_agreement between 0 and 1),
  aggregate_probabilities jsonb not null,
  machine_flags jsonb not null default '[]'::jsonb,
  explanation text not null,
  decision_authority text not null,
  created_at timestamptz not null
);

create table public.human_reviews (
  review_id uuid primary key,
  inspection_id uuid not null references public.inspections(inspection_id) on delete restrict,
  reviewer_id uuid not null references auth.users(id),
  disposition public.human_disposition not null,
  reason_codes jsonb not null default '[]'::jsonb,
  note text not null default '',
  blinded_to_machine_result boolean not null default false,
  created_at timestamptz not null default now()
);

create table public.device_health_events (
  health_event_id uuid primary key,
  device_id text not null references public.devices(device_id),
  event_type text not null,
  severity text not null check (severity in ('INFO', 'WARNING', 'FAULT')),
  context jsonb not null default '{}'::jsonb,
  device_timestamp timestamptz not null,
  created_at timestamptz not null default now()
);

create table public.audit_events (
  audit_event_id uuid primary key,
  sequence_number bigint generated by default as identity unique,
  actor_type text not null,
  actor_id text not null,
  action text not null,
  entity_type text not null,
  entity_id text not null,
  context jsonb not null default '{}'::jsonb,
  previous_event_sha256 text,
  event_sha256 text not null unique check (event_sha256 ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null
);

create index inspections_device_created_idx on public.inspections(device_id, created_at desc);
create index inspections_batch_created_idx on public.inspections(batch_id, created_at desc);
create index frames_inspection_idx on public.view_frames(inspection_id, view_index);
create index reviews_inspection_idx on public.human_reviews(inspection_id, created_at);
create index health_device_idx on public.device_health_events(device_id, created_at desc);
create index audit_entity_idx on public.audit_events(entity_type, entity_id, created_at);

create or replace function public.has_role(required_role public.app_role)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.user_roles
    where user_id = auth.uid() and role = required_role
  );
$$;

create or replace function public.can_access_device(requested_device_id text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select public.has_role('ADMIN'::public.app_role)
    or public.has_role('REVIEWER'::public.app_role)
    or exists (
      select 1 from public.device_assignments
      where user_id = auth.uid() and device_id = requested_device_id
    );
$$;

create or replace function public.can_access_inspection(requested_inspection_id uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.inspections
    where inspection_id = requested_inspection_id
      and public.can_access_device(device_id)
  );
$$;

create or replace function public.reject_immutable_mutation()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  raise exception 'immutable evidence records may not be updated or deleted';
end;
$$;

create trigger view_frames_immutable before update or delete on public.view_frames
for each row execute function public.reject_immutable_mutation();
create trigger machine_results_immutable before update or delete on public.machine_results
for each row execute function public.reject_immutable_mutation();
create trigger human_reviews_immutable before update or delete on public.human_reviews
for each row execute function public.reject_immutable_mutation();
create trigger audit_events_immutable before update or delete on public.audit_events
for each row execute function public.reject_immutable_mutation();

alter table public.user_roles enable row level security;
alter table public.devices enable row level security;
alter table public.device_assignments enable row level security;
alter table public.incubation_batches enable row level security;
alter table public.physical_eggs enable row level security;
alter table public.model_releases enable row level security;
alter table public.inspections enable row level security;
alter table public.view_frames enable row level security;
alter table public.machine_results enable row level security;
alter table public.human_reviews enable row level security;
alter table public.device_health_events enable row level security;
alter table public.audit_events enable row level security;

create policy "users see their own roles" on public.user_roles for select
using (user_id = auth.uid() or public.has_role('ADMIN'));
create policy "admins manage roles" on public.user_roles for all
using (public.has_role('ADMIN')) with check (public.has_role('ADMIN'));

create policy "assigned users see devices" on public.devices for select
using (public.can_access_device(device_id));
create policy "admins manage devices" on public.devices for all
using (public.has_role('ADMIN')) with check (public.has_role('ADMIN'));

create policy "users see their assignments" on public.device_assignments for select
using (user_id = auth.uid() or public.has_role('ADMIN'));
create policy "admins manage assignments" on public.device_assignments for all
using (public.has_role('ADMIN')) with check (public.has_role('ADMIN'));

create policy "authenticated users read batches" on public.incubation_batches for select
using (auth.uid() is not null);
create policy "admins manage batches" on public.incubation_batches for all
using (public.has_role('ADMIN')) with check (public.has_role('ADMIN'));
create policy "authenticated users read eggs" on public.physical_eggs for select
using (auth.uid() is not null);
create policy "admins manage eggs" on public.physical_eggs for all
using (public.has_role('ADMIN')) with check (public.has_role('ADMIN'));

create policy "authenticated users read approved releases" on public.model_releases for select
using (auth.uid() is not null and approved_at is not null);
create policy "admins manage model releases" on public.model_releases for all
using (public.has_role('ADMIN')) with check (public.has_role('ADMIN'));

create policy "scoped users read inspections" on public.inspections for select
using (public.can_access_device(device_id));
create policy "scoped users read frames" on public.view_frames for select
using (public.can_access_inspection(inspection_id));
create policy "scoped users read machine results" on public.machine_results for select
using (public.can_access_inspection(inspection_id));
create policy "scoped users read reviews" on public.human_reviews for select
using (public.can_access_inspection(inspection_id));
create policy "reviewers append dispositions" on public.human_reviews for insert
with check (
  reviewer_id = auth.uid()
  and (public.has_role('REVIEWER') or public.has_role('ADMIN'))
  and public.can_access_inspection(inspection_id)
);
create policy "scoped users read device health" on public.device_health_events for select
using (public.can_access_device(device_id));
create policy "admins read audit" on public.audit_events for select
using (public.has_role('ADMIN'));

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('balut-evidence', 'balut-evidence', false, 10485760, array['image/jpeg'])
on conflict (id) do update set public = false;

create policy "scoped users read evidence objects" on storage.objects for select
using (
  bucket_id = 'balut-evidence'
  and public.can_access_inspection(((storage.foldername(name))[1])::uuid)
);

commit;
