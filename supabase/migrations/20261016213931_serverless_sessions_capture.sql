-- Backend-only sessions and one leased camera state shared by Vercel instances.
create table public.balut_sessions (
  token_hash text primary key check (token_hash ~ '^[0-9a-f]{64}$'),
  username text not null,
  expires_at timestamptz not null
);
create index balut_sessions_expiry on public.balut_sessions (expires_at);
create table public.balut_login_attempts (
  id smallint primary key check (id = 1),
  attempts timestamptz[] not null default '{}'
);
insert into public.balut_login_attempts (id) values (1);
create table public.balut_camera (
  id smallint primary key check (id = 1),
  value jsonb not null default '{}',
  lease_token uuid,
  lease_until timestamptz
);
insert into public.balut_camera (id) values (1);
alter table public.balut_sessions enable row level security;
alter table public.balut_login_attempts enable row level security;
alter table public.balut_camera enable row level security;
revoke all on public.balut_sessions, public.balut_login_attempts, public.balut_camera from public, anon, authenticated;
grant select, insert, delete on public.balut_sessions to service_role;
grant select, update on public.balut_login_attempts, public.balut_camera to service_role;

create function public.balut_login_attempt() returns boolean
language plpgsql security invoker set search_path = '' as $$
declare recent timestamptz[];
begin
  select attempts into recent from public.balut_login_attempts where id = 1 for update;
  select coalesce(array_agg(t), '{}') into recent from unnest(recent) t
    where t > clock_timestamp() - interval '1 minute';
  if cardinality(recent) >= 10 then return false; end if;
  update public.balut_login_attempts set attempts = array_append(recent, clock_timestamp()) where id = 1;
  return true;
end;
$$;

create function public.balut_create_session(p_hash text, p_username text) returns void
language plpgsql security invoker set search_path = '' as $$
begin
  perform pg_advisory_xact_lock(61920381);
  if not exists (select 1 from public.balut_account where id = 1 and username = p_username) then
    raise exception 'Account unavailable';
  end if;
  delete from public.balut_sessions where expires_at <= clock_timestamp();
  delete from public.balut_sessions where token_hash in (
    select token_hash from public.balut_sessions order by expires_at desc offset 63
  );
  insert into public.balut_sessions values (p_hash, p_username, clock_timestamp() + interval '8 hours');
end;
$$;

create function public.balut_claim_camera(p_token uuid) returns jsonb
language plpgsql security invoker set search_path = '' as $$
declare snapshot jsonb;
begin
  update public.balut_camera set lease_token = p_token, lease_until = clock_timestamp() + interval '150 seconds'
    where id = 1 and (lease_until is null or lease_until < clock_timestamp()) returning value into snapshot;
  return snapshot;
end;
$$;

create function public.balut_save_camera(p_token uuid, p_value jsonb, p_release boolean) returns boolean
language plpgsql security invoker set search_path = '' as $$
begin
  if jsonb_typeof(p_value) <> 'object' or octet_length(p_value::text) > 1000000 then
    raise exception 'Invalid camera state';
  end if;
  update public.balut_camera set value = p_value,
    lease_token = case when p_release then null else lease_token end,
    lease_until = case when p_release then null else lease_until end
    where id = 1 and lease_token = p_token and lease_until > clock_timestamp();
  return found;
end;
$$;
revoke all on function public.balut_login_attempt(), public.balut_create_session(text,text),
  public.balut_claim_camera(uuid), public.balut_save_camera(uuid,jsonb,boolean) from public, anon, authenticated;
grant execute on function public.balut_login_attempt(), public.balut_create_session(text,text),
  public.balut_claim_camera(uuid), public.balut_save_camera(uuid,jsonb,boolean) to service_role;
