-- Leman Brut : comptes, équipes et données partagées.
-- À exécuter une fois dans Supabase > SQL Editor > Run.

-- Nettoyage de l'ancienne table de test (première version, sans comptes), si elle existe.
do $$ begin
  if exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'lb_docs' and column_name = 'team')
     and not exists (select 1 from information_schema.columns where table_schema = 'public' and table_name = 'lb_docs' and column_name = 'team_id') then
    drop table lb_docs;
  end if;
end $$;

create table if not exists profiles (
  id uuid primary key references auth.users on delete cascade,
  email text not null,
  pseudo text not null,
  approved boolean not null default false,
  is_admin boolean not null default false,
  created_at timestamptz not null default now()
);
create unique index if not exists profiles_pseudo_uq on profiles (lower(pseudo));

create table if not exists teams (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  created_by uuid not null references profiles (id),
  created_at timestamptz not null default now()
);
create unique index if not exists teams_name_uq on teams (lower(name));

create table if not exists team_members (
  team_id uuid not null references teams (id) on delete cascade,
  user_id uuid not null references profiles (id) on delete cascade,
  role text not null default 'member' check (role in ('owner', 'captain', 'member')),
  status text not null default 'pending' check (status in ('pending', 'active')),
  primary key (team_id, user_id)
);

create table if not exists lb_docs (
  team_id uuid not null references teams (id) on delete cascade,
  k text not null,
  id text not null,
  body jsonb,
  u bigint not null,
  del boolean not null default false,
  primary key (team_id, k, id)
);

-- Fonctions d'aide (security definer : évitent les boucles de règles)
create or replace function is_admin() returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from profiles where id = auth.uid() and is_admin and approved)
$$;
create or replace function is_approved() returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from profiles where id = auth.uid() and approved)
$$;
create or replace function is_member(t uuid) returns boolean language sql stable security definer set search_path = public as $$
  select is_admin() or exists (select 1 from team_members where team_id = t and user_id = auth.uid() and status = 'active')
$$;
create or replace function can_manage(t uuid) returns boolean language sql stable security definer set search_path = public as $$
  select is_admin() or exists (select 1 from team_members where team_id = t and user_id = auth.uid() and status = 'active' and role in ('owner', 'captain'))
$$;
create or replace function is_owner(t uuid) returns boolean language sql stable security definer set search_path = public as $$
  select is_admin() or exists (select 1 from team_members where team_id = t and user_id = auth.uid() and status = 'active' and role = 'owner')
$$;
create or replace function shares_team(u uuid) returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from team_members a join team_members b on a.team_id = b.team_id
    where a.user_id = auth.uid() and a.status = 'active' and b.user_id = u)
$$;

-- Création automatique du profil. Le compte matthieu.seynaeve.pro@hotmail.com devient
-- l'administrateur « Iscalis » (il doit confirmer cette adresse par e-mail pour se connecter).
create or replace function handle_new_user() returns trigger language plpgsql security definer set search_path = public as $$
declare p text; adm boolean;
begin
  adm := lower(new.email) = 'matthieu.seynaeve.pro@hotmail.com';
  p := coalesce(nullif(trim(new.raw_user_meta_data ->> 'pseudo'), ''), split_part(new.email, '@', 1));
  if adm then p := 'Iscalis';
  elsif lower(p) = 'iscalis' then raise exception 'Ce pseudo est réservé';
  end if;
  insert into profiles (id, email, pseudo, approved, is_admin) values (new.id, new.email, left(p, 30), adm, adm);
  return new;
end $$;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users for each row execute function handle_new_user();

-- Le créateur d'une équipe en devient automatiquement le responsable.
create or replace function handle_new_team() returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into team_members (team_id, user_id, role, status) values (new.id, new.created_by, 'owner', 'active');
  return new;
end $$;
drop trigger if exists on_team_created on teams;
create trigger on_team_created after insert on teams for each row execute function handle_new_team();

-- Règles d'accès
alter table profiles enable row level security;
alter table teams enable row level security;
alter table team_members enable row level security;
alter table lb_docs enable row level security;

drop policy if exists p_sel on profiles;
create policy p_sel on profiles for select to authenticated using (id = auth.uid() or is_admin() or shares_team(id));
drop policy if exists p_upd on profiles;
create policy p_upd on profiles for update to authenticated using (is_admin()) with check (is_admin());

drop policy if exists t_sel on teams;
create policy t_sel on teams for select to authenticated using (is_approved());
drop policy if exists t_ins on teams;
create policy t_ins on teams for insert to authenticated with check (is_approved() and created_by = auth.uid());
drop policy if exists t_upd on teams;
create policy t_upd on teams for update to authenticated using (can_manage(id)) with check (can_manage(id));
drop policy if exists t_del on teams;
create policy t_del on teams for delete to authenticated using (is_owner(id));

drop policy if exists m_sel on team_members;
create policy m_sel on team_members for select to authenticated using (user_id = auth.uid() or is_member(team_id));
drop policy if exists m_ins on team_members;
create policy m_ins on team_members for insert to authenticated
  with check (is_admin() or (user_id = auth.uid() and role = 'member' and status = 'pending' and is_approved()));
drop policy if exists m_upd on team_members;
create policy m_upd on team_members for update to authenticated
  using (can_manage(team_id) and (role <> 'owner' or is_owner(team_id)))
  with check (can_manage(team_id) and (role <> 'owner' or is_owner(team_id)));
drop policy if exists m_del on team_members;
create policy m_del on team_members for delete to authenticated
  using (is_admin() or (user_id = auth.uid() and role <> 'owner') or (can_manage(team_id) and role <> 'owner'));

drop policy if exists d_sel on lb_docs;
create policy d_sel on lb_docs for select to authenticated using (is_member(team_id));
-- Qui peut écrire quoi : seuls les capitaines créent/modifient les événements ;
-- chaque joueur dépose sa propre liste (id « <son id>.xxx ») et note ses propres matchs (id « …|…|<son id> »).
create or replace function doc_ok(t uuid, kind text, did text) returns boolean language sql stable security definer set search_path = public as $$
  select is_member(t) and case kind
    when 'event' then can_manage(t)
    when 'list' then can_manage(t) or split_part(did, '.', 1) = auth.uid()::text
    when 'rate' then can_manage(t) or split_part(did, '|', 3) = auth.uid()::text
    else true end
$$;
drop policy if exists d_ins on lb_docs;
create policy d_ins on lb_docs for insert to authenticated with check (doc_ok(team_id, k, id));
drop policy if exists d_upd on lb_docs;
create policy d_upd on lb_docs for update to authenticated using (doc_ok(team_id, k, id)) with check (doc_ok(team_id, k, id));

-- Droits : uniquement les comptes connectés (les règles ci-dessus filtrent ensuite ligne par ligne)
revoke all on profiles, teams, team_members, lb_docs from anon;
grant usage on schema public to authenticated;
grant select, insert, update, delete on profiles, teams, team_members, lb_docs to authenticated;
grant execute on function is_admin(), is_approved(), is_member(uuid), can_manage(uuid), is_owner(uuid), shares_team(uuid), doc_ok(uuid, text, text) to authenticated;

-- Comptes créés avant l'exécution de ce script : on leur crée leur profil maintenant.
insert into profiles (id, email, pseudo, approved, is_admin)
select u.id, u.email,
  case when lower(u.email) = 'matthieu.seynaeve.pro@hotmail.com' then 'Iscalis'
       else left(coalesce(nullif(trim(u.raw_user_meta_data ->> 'pseudo'), ''), split_part(u.email, '@', 1)), 30) end,
  lower(u.email) = 'matthieu.seynaeve.pro@hotmail.com',
  lower(u.email) = 'matthieu.seynaeve.pro@hotmail.com'
from auth.users u
where not exists (select 1 from profiles p where p.id = u.id)
on conflict do nothing;

notify pgrst, 'reload schema';
