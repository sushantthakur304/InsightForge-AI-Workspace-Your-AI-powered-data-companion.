-- InsightForge production foundation for Supabase.
-- Apply with `supabase db push` or the Supabase SQL editor before setting
-- INSIGHTFORGE_STORAGE_BACKEND=supabase in the Streamlit deployment.

create extension if not exists pgcrypto;

do $$
begin
  create type public.workspace_role as enum ('owner', 'admin', 'editor', 'viewer');
exception
  when duplicate_object then null;
end $$;

create table if not exists public.profiles (
  user_id text primary key,
  email text,
  display_name text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.workspaces (
  id uuid primary key default gen_random_uuid(),
  name text not null check (char_length(trim(name)) between 1 and 120),
  owner_id text not null references public.profiles(user_id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.workspace_members (
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  user_id text not null references public.profiles(user_id) on delete cascade,
  role public.workspace_role not null default 'viewer',
  created_at timestamptz not null default now(),
  primary key (workspace_id, user_id)
);

create table if not exists public.workspace_invites (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  email text not null,
  role public.workspace_role not null default 'viewer',
  invited_by text not null references public.profiles(user_id),
  expires_at timestamptz not null default now() + interval '14 days',
  accepted_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists public.projects (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  name text not null,
  description text,
  created_by text not null references public.profiles(user_id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.datasets (
  id uuid primary key,
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  project_id uuid references public.projects(id) on delete set null,
  created_by text not null references public.profiles(user_id),
  file_name text not null,
  file_type text not null,
  size_bytes bigint not null check (size_bytes >= 0),
  row_count bigint not null default 0 check (row_count >= 0),
  column_count integer not null default 0 check (column_count >= 0),
  available_sheets jsonb not null default '[]'::jsonb,
  selected_sheets jsonb not null default '[]'::jsonb,
  active_sheet text not null default '',
  combined boolean not null default false,
  storage_key text not null unique,
  context jsonb not null default '{}'::jsonb,
  processing_status text not null default 'ready' check (processing_status in ('queued', 'processing', 'ready', 'failed')),
  last_loaded_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.dataset_profiles (
  id uuid primary key default gen_random_uuid(),
  dataset_id uuid not null references public.datasets(id) on delete cascade,
  profile jsonb not null,
  generated_at timestamptz not null default now(),
  generated_by text references public.profiles(user_id)
);

create table if not exists public.analysis_runs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  project_id uuid references public.projects(id) on delete set null,
  created_by text not null references public.profiles(user_id),
  project_name text,
  file_name text not null,
  row_count bigint not null check (row_count >= 0),
  column_count integer not null check (column_count >= 0),
  quality_score numeric not null,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.validation_policy_templates (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid references public.workspaces(id) on delete cascade,
  name text not null,
  industry text,
  rules jsonb not null,
  created_by text references public.profiles(user_id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.external_reference_checks (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  label text not null,
  source_url text not null check (source_url like 'https://%'),
  target_column text not null,
  items_path text,
  value_field text not null default 'id',
  enabled boolean not null default true,
  created_by text not null references public.profiles(user_id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.scheduled_refreshes (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  dataset_id uuid references public.datasets(id) on delete cascade,
  source_url text not null check (source_url like 'https://%'),
  schedule_cron text not null,
  enabled boolean not null default true,
  last_run_at timestamptz,
  next_run_at timestamptz,
  created_by text not null references public.profiles(user_id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.background_jobs (
  id uuid primary key default gen_random_uuid(),
  workspace_id uuid not null references public.workspaces(id) on delete cascade,
  created_by text not null references public.profiles(user_id),
  job_type text not null check (job_type in ('profile_dataset', 'refresh_dataset', 'reference_check')),
  payload jsonb not null default '{}'::jsonb,
  status text not null default 'queued' check (status in ('queued', 'running', 'succeeded', 'failed')),
  scheduled_for timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  locked_by text,
  error_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists datasets_workspace_created_idx on public.datasets (workspace_id, created_at desc);
create index if not exists analysis_runs_workspace_created_idx on public.analysis_runs (workspace_id, created_at desc);
create index if not exists background_jobs_claim_idx on public.background_jobs (status, scheduled_for, created_at);
create index if not exists scheduled_refreshes_due_idx on public.scheduled_refreshes (enabled, next_run_at);

create or replace function public.is_workspace_member(
  p_workspace_id uuid,
  p_roles public.workspace_role[] default array['owner', 'admin', 'editor', 'viewer']::public.workspace_role[]
)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.workspace_members member
    where member.workspace_id = p_workspace_id
      and member.user_id = (auth.jwt() ->> 'sub')
      and member.role = any(p_roles)
  );
$$;

create or replace function public.object_workspace_id(p_object_name text)
returns uuid
language plpgsql
immutable
as $$
begin
  return nullif(split_part(p_object_name, '/', 1), '')::uuid;
exception when invalid_text_representation then
  return null;
end;
$$;

create or replace function public.ensure_personal_workspace(
  p_user_id text,
  p_email text,
  p_display_name text
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_workspace_id uuid;
begin
  insert into public.profiles (user_id, email, display_name)
  values (p_user_id, p_email, p_display_name)
  on conflict (user_id) do update
  set email = excluded.email,
      display_name = coalesce(excluded.display_name, public.profiles.display_name),
      updated_at = now();

  select workspace_id into v_workspace_id
  from public.workspace_members
  where user_id = p_user_id
  order by created_at
  limit 1;

  if v_workspace_id is null then
    insert into public.workspaces (name, owner_id)
    values (coalesce(nullif(p_display_name, ''), nullif(p_email, ''), 'My') || '''s workspace', p_user_id)
    returning id into v_workspace_id;

    insert into public.workspace_members (workspace_id, user_id, role)
    values (v_workspace_id, p_user_id, 'owner');
  end if;

  return jsonb_build_object('workspace_id', v_workspace_id);
end;
$$;

create or replace function public.list_user_workspaces(p_user_id text)
returns table (id uuid, name text, role public.workspace_role)
language sql
stable
security definer
set search_path = public
as $$
  select workspace.id, workspace.name, member.role
  from public.workspace_members member
  join public.workspaces workspace on workspace.id = member.workspace_id
  where member.user_id = p_user_id
  order by workspace.created_at;
$$;

create or replace function public.claim_next_background_job(p_worker_id text)
returns table (id uuid, workspace_id uuid, job_type text, payload jsonb)
language plpgsql
security definer
set search_path = public
as $$
begin
  return query
  with candidate as (
    select job.id
    from public.background_jobs job
    where job.status = 'queued' and job.scheduled_for <= now()
    order by job.scheduled_for, job.created_at
    for update skip locked
    limit 1
  )
  update public.background_jobs job
  set status = 'running', started_at = now(), locked_by = p_worker_id, updated_at = now()
  from candidate
  where job.id = candidate.id
  returning job.id, job.workspace_id, job.job_type, job.payload;
end;
$$;

-- The application uses service-only RPC functions after it has verified the
-- Streamlit OIDC identity. Browser clients use the RLS policies below.
revoke all on function public.ensure_personal_workspace(text, text, text) from public, anon, authenticated;
revoke all on function public.list_user_workspaces(text) from public, anon, authenticated;
revoke all on function public.claim_next_background_job(text) from public, anon, authenticated;
grant execute on function public.ensure_personal_workspace(text, text, text) to service_role;
grant execute on function public.list_user_workspaces(text) to service_role;
grant execute on function public.claim_next_background_job(text) to service_role;

alter table public.profiles enable row level security;
alter table public.workspaces enable row level security;
alter table public.workspace_members enable row level security;
alter table public.workspace_invites enable row level security;
alter table public.projects enable row level security;
alter table public.datasets enable row level security;
alter table public.dataset_profiles enable row level security;
alter table public.analysis_runs enable row level security;
alter table public.validation_policy_templates enable row level security;
alter table public.external_reference_checks enable row level security;
alter table public.scheduled_refreshes enable row level security;
alter table public.background_jobs enable row level security;

-- RLS is not a replacement for privilege grants. Remove the broad defaults
-- from exposed tables, then grant only the operations protected by policies.
revoke all on table public.profiles, public.workspaces, public.workspace_members,
  public.workspace_invites, public.projects, public.datasets, public.dataset_profiles,
  public.analysis_runs, public.validation_policy_templates, public.external_reference_checks,
  public.scheduled_refreshes, public.background_jobs from anon, authenticated;
grant select, insert, update, delete on table public.workspaces, public.workspace_members,
  public.workspace_invites, public.projects, public.datasets, public.dataset_profiles,
  public.analysis_runs, public.validation_policy_templates, public.external_reference_checks,
  public.scheduled_refreshes, public.background_jobs to authenticated;

create policy "members can view workspaces" on public.workspaces for select using (public.is_workspace_member(id));
create policy "owners can update workspaces" on public.workspaces for update using (public.is_workspace_member(id, array['owner', 'admin']::public.workspace_role[]));
create policy "members can view members" on public.workspace_members for select using (public.is_workspace_member(workspace_id));
create policy "admins manage members" on public.workspace_members for all using (public.is_workspace_member(workspace_id, array['owner', 'admin']::public.workspace_role[])) with check (public.is_workspace_member(workspace_id, array['owner', 'admin']::public.workspace_role[]));

create policy "members view datasets" on public.datasets for select using (public.is_workspace_member(workspace_id));
create policy "editors create datasets" on public.datasets for insert with check (public.is_workspace_member(workspace_id, array['owner', 'admin', 'editor']::public.workspace_role[]));
create policy "editors update datasets" on public.datasets for update using (public.is_workspace_member(workspace_id, array['owner', 'admin', 'editor']::public.workspace_role[]));
create policy "admins remove datasets" on public.datasets for delete using (public.is_workspace_member(workspace_id, array['owner', 'admin']::public.workspace_role[]));
create policy "members view dataset profiles" on public.dataset_profiles for select using (
  exists (select 1 from public.datasets dataset where dataset.id = dataset_id and public.is_workspace_member(dataset.workspace_id))
);

create policy "members view projects" on public.projects for select using (public.is_workspace_member(workspace_id));
create policy "editors manage projects" on public.projects for all using (public.is_workspace_member(workspace_id, array['owner', 'admin', 'editor']::public.workspace_role[])) with check (public.is_workspace_member(workspace_id, array['owner', 'admin', 'editor']::public.workspace_role[]));
create policy "members view history" on public.analysis_runs for select using (public.is_workspace_member(workspace_id));
create policy "editors create history" on public.analysis_runs for insert with check (public.is_workspace_member(workspace_id, array['owner', 'admin', 'editor']::public.workspace_role[]));
create policy "members view policy templates" on public.validation_policy_templates for select using (workspace_id is null or public.is_workspace_member(workspace_id));
create policy "editors manage policy templates" on public.validation_policy_templates for all using (public.is_workspace_member(workspace_id, array['owner', 'admin', 'editor']::public.workspace_role[])) with check (public.is_workspace_member(workspace_id, array['owner', 'admin', 'editor']::public.workspace_role[]));
create policy "members view reference checks" on public.external_reference_checks for select using (public.is_workspace_member(workspace_id));
create policy "admins manage reference checks" on public.external_reference_checks for all using (public.is_workspace_member(workspace_id, array['owner', 'admin']::public.workspace_role[])) with check (public.is_workspace_member(workspace_id, array['owner', 'admin']::public.workspace_role[]));
create policy "members view refreshes" on public.scheduled_refreshes for select using (public.is_workspace_member(workspace_id));
create policy "admins manage refreshes" on public.scheduled_refreshes for all using (public.is_workspace_member(workspace_id, array['owner', 'admin']::public.workspace_role[])) with check (public.is_workspace_member(workspace_id, array['owner', 'admin']::public.workspace_role[]));
create policy "members view jobs" on public.background_jobs for select using (public.is_workspace_member(workspace_id));
create policy "editors enqueue jobs" on public.background_jobs for insert with check (public.is_workspace_member(workspace_id, array['owner', 'admin', 'editor']::public.workspace_role[]));

insert into storage.buckets (id, name, public)
values ('dataset-files', 'dataset-files', false)
on conflict (id) do update set public = false;

create policy "members read private dataset objects" on storage.objects for select using (
  bucket_id = 'dataset-files' and public.is_workspace_member(public.object_workspace_id(name))
);
create policy "editors create private dataset objects" on storage.objects for insert with check (
  bucket_id = 'dataset-files' and public.is_workspace_member(public.object_workspace_id(name), array['owner', 'admin', 'editor']::public.workspace_role[])
);
create policy "admins delete private dataset objects" on storage.objects for delete using (
  bucket_id = 'dataset-files' and public.is_workspace_member(public.object_workspace_id(name), array['owner', 'admin']::public.workspace_role[])
);
