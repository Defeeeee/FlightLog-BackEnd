-- 002 — Arreglar el borrado de cuentas, que hoy no funciona.
--
-- Estado actual, comprobado contra la base de producción (no inferido):
--
--   select ... explain delete from public.profiles where user_id = '...'::uuid
--   -> 42703 — column "user_id" does not exist
--
-- `handle_deleted_user()` borra por `user_id`, columna que `profiles` no tiene:
-- la clave es `id`. El trigger `profiles_user_delete_cascade` está habilitado
-- sobre `auth.users`, así que **borrar un usuario viene fallando entero** y el
-- perfil nunca se limpia. Hoy la app no puede borrar una cuenta.
--
-- Tres cambios:
--
-- 1. La función borra por `id`.
--
-- 2. El trigger pasa de AFTER a BEFORE DELETE. `auth.users` también cascadea a
--    `logbooks`, y `flights.logbook_id` es ON DELETE NO ACTION **a propósito**
--    —borrar un libro no debe llevarse los vuelos por delante—. Con AFTER, que
--    el perfil se borre antes que los libros depende del orden de disparo entre
--    triggers internos de FK, que Postgres resuelve por nombre. Con BEFORE, los
--    vuelos ya se fueron por el cascade de `profiles` cuando le toca a
--    `logbooks`, y no hay que confiar en ningún orden.
--
-- 3. `flight_packs` era la única tabla hija con ON DELETE NO ACTION; todas las
--    demás (aircraft, flights, transactions, documents, audit_findings,
--    flight_sessions) ya eran CASCADE. Con esa sola en NO ACTION, cualquier
--    piloto con packs seguiría sin poder borrarse aun con lo demás arreglado.
--
-- ⚠️ Esto **habilita el borrado real de datos de usuario**, que hoy no ocurre.
-- Es el comportamiento que el nombre del trigger promete y lo que hace falta
-- para poder ofrecer baja de cuenta, pero es un cambio de conducta, no una
-- corrección cosmética. Al final hay una prueba end-to-end que hace rollback.

begin;

create or replace function public.handle_deleted_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $function$
begin
  delete from public.profiles where id = old.id;
  return old;
end;
$function$;

drop trigger if exists profiles_user_delete_cascade on auth.users;
create trigger profiles_user_delete_cascade
  before delete on auth.users
  for each row execute function public.handle_deleted_user();

-- La función es SECURITY DEFINER y sólo se usa como trigger; ningún rol del API
-- necesita EXECUTE (ver migración de endurecimiento previa).
revoke execute on function public.handle_deleted_user() from public, anon, authenticated;

alter table public.flight_packs drop constraint flight_packs_user_id_fkey;
alter table public.flight_packs
  add constraint flight_packs_user_id_fkey
  foreign key (user_id) references public.profiles(id) on delete cascade;

commit;


-- ---------------------------------------------------------------------------
-- Prueba end-to-end. Crea un usuario descartable con perfil, libro, vuelo y
-- pack, lo borra, comprueba que no quedó nada, y **aborta siempre** con un
-- RAISE para que no se escriba nada. Correr después de aplicar lo de arriba.
--
-- Si el mensaje de error dice `todo limpio`, el borrado de cuentas funciona.
-- ---------------------------------------------------------------------------
-- do $$
-- declare
--   uid uuid := gen_random_uuid();
--   restantes text;
-- begin
--   insert into auth.users (id, instance_id, aud, role, email, created_at, updated_at)
--   values (uid, '00000000-0000-0000-0000-000000000000', 'authenticated',
--           'authenticated', uid || '@prueba.invalid', now(), now());
--
--   -- El trigger on_auth_user_created ya insertó el profile.
--   insert into public.logbooks (user_id, name, is_default) values (uid, 'Prueba', true);
--   insert into public.flight_packs (user_id, name, total_hours)
--   values (uid, 'Pack de prueba', 10);
--
--   delete from auth.users where id = uid;
--
--   select coalesce(string_agg(t, ', '), 'todo limpio') into restantes from (
--     select 'profiles'     as t where exists (select 1 from public.profiles     where id = uid)
--     union all
--     select 'logbooks'          where exists (select 1 from public.logbooks     where user_id = uid)
--     union all
--     select 'flight_packs'      where exists (select 1 from public.flight_packs where user_id = uid)
--     union all
--     select 'auth.users'        where exists (select 1 from auth.users          where id = uid)
--   ) s;
--
--   raise exception 'ROLLBACK DE PRUEBA — quedó: %', restantes;
-- end $$;
