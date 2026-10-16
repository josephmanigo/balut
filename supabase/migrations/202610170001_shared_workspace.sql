-- Standalone schema for the current single-account model workbench.
-- The older research schema is separate and is not required by this migration.
begin;

create table if not exists public.balut_account (
    id integer primary key check (id = 1),
    username text not null unique check (username ~ '^[a-z0-9][a-z0-9_.-]{2,31}$'),
    password_hash text not null check (password_hash ~ '^scrypt\$131072\$8\$1\$[0-9a-f]{32}\$[0-9a-f]{64}$'),
    created_at timestamptz not null default now()
);

create table if not exists public.balut_predictions (
    id uuid primary key,
    actor_id text not null,
    request_key text not null,
    request_hash text not null check (request_hash ~ '^[0-9a-f]{64}$'),
    image_sha256 text not null check (image_sha256 ~ '^[0-9a-f]{64}$'),
    response jsonb not null,
    created_at timestamptz not null,
    unique (actor_id, request_key),
    check (response->>'predictionId' = id::text),
    check (response->>'imageSha256' = image_sha256)
);
create index if not exists balut_predictions_created on public.balut_predictions(created_at desc, id desc);

create table if not exists public.balut_prediction_audit (
    prediction_id uuid primary key references public.balut_predictions(id),
    actor_id text not null,
    recorded_at timestamptz not null default now()
);

alter table public.balut_account enable row level security;
alter table public.balut_predictions enable row level security;
alter table public.balut_prediction_audit enable row level security;
revoke all on public.balut_account, public.balut_predictions, public.balut_prediction_audit from public, anon, authenticated;
revoke all on public.balut_account, public.balut_predictions, public.balut_prediction_audit from service_role;
grant select, insert on public.balut_account, public.balut_predictions, public.balut_prediction_audit to service_role;

create or replace function public.balut_record_prediction(p_response jsonb, p_actor text, p_key text, p_hash text)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
    saved public.balut_predictions;
    new_id uuid := (p_response->>'predictionId')::uuid;
    image_hash text := p_response->>'imageSha256';
begin
    if p_actor is null or length(p_actor) not between 1 and 160
       or p_key is null or length(p_key) not between 1 and 200
       or p_hash is null or p_hash !~ '^[0-9a-f]{64}$'
       or image_hash is null or image_hash !~ '^[0-9a-f]{64}$'
       or new_id is null or p_response->>'createdAt' is null
       or p_response->>'modelId' is null or p_response->>'modelReleaseId' is null then
        raise exception 'Invalid prediction' using errcode = '22023';
    end if;
    -- Serializes retries across processes; insert and audit are one transaction.
    perform pg_advisory_xact_lock(hashtextextended(p_actor || ':' || p_key, 0));
    select * into saved from public.balut_predictions where actor_id = p_actor and request_key = p_key;
    if found then
        if saved.request_hash <> p_hash then
            raise exception 'Idempotency conflict' using errcode = '23505';
        end if;
        return saved.response;
    end if;
    if not exists (select 1 from storage.objects where bucket_id = 'balut-evidence'
                   and name = left(image_hash, 2) || '/' || image_hash || '.jpg') then
        raise exception 'Evidence must be stored before its prediction' using errcode = '22023';
    end if;
    insert into public.balut_predictions values
        (new_id, p_actor, p_key, p_hash, image_hash, p_response, (p_response->>'createdAt')::timestamptz);
    insert into public.balut_prediction_audit(prediction_id, actor_id) values (new_id, p_actor);
    return p_response;
end;
$$;
revoke all on function public.balut_record_prediction(jsonb, text, text, text) from public, anon, authenticated;
grant execute on function public.balut_record_prediction(jsonb, text, text, text) to service_role;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('balut-evidence', 'balut-evidence', false, 10485760, array['image/jpeg'])
on conflict (id) do nothing;
-- No anonymous or authenticated Storage policies: only the trusted backend has access.
notify pgrst, 'reload schema';
commit;
