-- Leman Brut : durcissement de la sécurité (à exécuter après schema.sql).
-- Peut être relancé sans risque.

-- 1. Aucune adresse e-mail dans les tables de l'application.
--    (Supabase Auth garde l'e-mail pour la connexion et le mot de passe oublié, rien d'autre.)
create or replace function handle_new_user() returns trigger language plpgsql security definer set search_path = public as $$
declare p text;
begin
  p := left(coalesce(nullif(trim(new.raw_user_meta_data ->> 'pseudo'), ''), 'joueur-' || left(new.id::text, 8)), 30);
  if lower(p) = 'iscalis' then raise exception 'Ce pseudo est réservé'; end if;
  insert into profiles (id, pseudo, approved, is_admin) values (new.id, p, false, false);
  return new;
end $$;
alter table profiles drop column if exists email;

-- 2. Double authentification (2FA).
--    Un compte qui l'a activée doit avoir saisi son code pour accéder aux données.
--    L'administrateur doit TOUJOURS l'avoir activée et saisie : sinon, pas de pouvoirs d'administration.
create or replace function mfa_ok() returns boolean language sql stable security definer set search_path = public as $$
  select coalesce(auth.jwt() ->> 'aal', '') = 'aal2'
      or not exists (select 1 from auth.mfa_factors where user_id = auth.uid() and status = 'verified')
$$;
create or replace function is_admin() returns boolean language sql stable security definer set search_path = public as $$
  select coalesce(auth.jwt() ->> 'aal', '') = 'aal2'
     and exists (select 1 from profiles where id = auth.uid() and is_admin and approved)
$$;
create or replace function is_approved() returns boolean language sql stable security definer set search_path = public as $$
  select mfa_ok() and exists (select 1 from profiles where id = auth.uid() and approved)
$$;
create or replace function is_member(t uuid) returns boolean language sql stable security definer set search_path = public as $$
  select is_admin() or (mfa_ok() and exists (select 1 from team_members where team_id = t and user_id = auth.uid() and status = 'active'))
$$;
create or replace function can_manage(t uuid) returns boolean language sql stable security definer set search_path = public as $$
  select is_admin() or (mfa_ok() and exists (select 1 from team_members where team_id = t and user_id = auth.uid() and status = 'active' and role in ('owner', 'captain')))
$$;
create or replace function is_owner(t uuid) returns boolean language sql stable security definer set search_path = public as $$
  select is_admin() or (mfa_ok() and exists (select 1 from team_members where team_id = t and user_id = auth.uid() and status = 'active' and role = 'owner'))
$$;
create or replace function shares_team(u uuid) returns boolean language sql stable security definer set search_path = public as $$
  select mfa_ok() and exists (
    select 1 from team_members a join team_members b on a.team_id = b.team_id
    where a.user_id = auth.uid() and a.status = 'active' and b.user_id = u)
$$;

-- Le pseudo de l'administrateur reste fixe (vérifié sur la colonne, pas sur la session).
create or replace function set_pseudo(new_pseudo text) returns void language plpgsql security definer set search_path = public as $$
declare p text := left(trim(coalesce(new_pseudo, '')), 30);
begin
  if auth.uid() is null or not is_approved() then raise exception 'Non autorisé'; end if;
  if exists (select 1 from profiles where id = auth.uid() and is_admin) then raise exception 'Le pseudo de l''administrateur ne peut pas être modifié'; end if;
  if length(p) < 2 then raise exception 'Pseudo trop court (2 caractères minimum)'; end if;
  if lower(p) = 'iscalis' then raise exception 'Ce pseudo est réservé'; end if;
  if exists (select 1 from profiles where lower(pseudo) = lower(p) and id <> auth.uid()) then raise exception 'Ce pseudo est déjà pris'; end if;
  update profiles set pseudo = p where id = auth.uid();
end $$;

-- 3. Ménage automatique : événements de plus de 30 jours, et comptes jamais validés après 30 jours.
create or replace function purge_old_events() returns int language plpgsql security definer set search_path = public as $$
declare r record; n int := 0;
begin
  if not is_approved() then return 0; end if;
  for r in select team_id, id from lb_docs
           where k = 'event' and del = false and (body ->> 'date') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' and (body ->> 'date')::date < current_date - 30 loop
    delete from lb_docs where team_id = r.team_id and (
      (k = 'event' and id = r.id) or (k = 'list' and body ->> 'eventId' = r.id) or (k = 'rate' and id like r.id || '|%'));
    n := n + 1;
  end loop;
  delete from auth.users u using profiles p
   where p.id = u.id and not p.approved and not p.is_admin and p.created_at < now() - interval '30 days';
  return n;
end $$;

-- 4. Droits au plus juste.
--    Personne sans compte (anon) ne peut appeler quoi que ce soit.
revoke execute on all functions in schema public from public, anon, authenticated;
alter default privileges in schema public revoke execute on functions from public, anon, authenticated;
grant execute on function mfa_ok(), is_admin(), is_approved(), is_member(uuid), can_manage(uuid), is_owner(uuid),
  shares_team(uuid), doc_ok(uuid, text, text), set_pseudo(text), purge_old_events() to authenticated;
--    Les fonctions déclenchées automatiquement (handle_new_user, handle_new_team, lb_docs_guard) ne sont appelables par personne.

revoke all on profiles, teams, team_members, lb_docs from anon, public;
revoke all on profiles, teams, team_members, lb_docs from authenticated;
grant select on profiles, teams, team_members, lb_docs to authenticated;
grant update (approved) on profiles to authenticated;            -- l'admin valide les comptes ; rien d'autre n'est modifiable
grant insert, delete on teams to authenticated;
grant update (name) on teams to authenticated;
grant insert, delete on team_members to authenticated;
grant update (role, status) on team_members to authenticated;
grant insert, update on lb_docs to authenticated;                -- suppression = marquage « del », jamais d'effacement direct

-- 5. Garde-fous de forme appliqués aussi aux données existantes.
alter table lb_docs validate constraint lb_docs_safe;
alter table teams validate constraint teams_name_safe;
alter table profiles validate constraint profiles_pseudo_safe;

notify pgrst, 'reload schema';
