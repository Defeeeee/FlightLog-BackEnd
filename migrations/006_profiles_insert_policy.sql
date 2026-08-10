-- 006 — Perfiles huérfanos: el auto-alta estaba muerto por RLS.
--
-- Síntoma medido contra producción (no inferido): 5 de 15 usuarios de
-- `auth.users` no tienen fila en `profiles`, con cero vuelos, libros, aeronaves,
-- documentos y packs, y `deleted_at` en null. No son cuentas borradas: es gente
-- que se registró y nunca pudo usar la app. Uno de ellos volvió a entrar dos
-- meses después de registrarse y encontró lo mismo.
--
-- Hay dos defensas para que un usuario tenga perfil, y las dos fallaban:
--
-- 1. El trigger `on_auth_user_created` -> `handle_new_user()`. Cubre las altas
--    nuevas (todos los usuarios posteriores al 2026-05-27 tienen perfil), pero
--    no puede reparar hacia atrás.
--
-- 2. El auto-alta de `ProfilesController.get_profiles`, que existe justamente
--    para curar este caso al siguiente login. **Estaba muerto.** Corre con el
--    cliente del usuario, y `profiles` tiene RLS activo con policies de SELECT
--    y UPDATE pero **ninguna de INSERT**. Comprobado simulando el insert con
--    `role=authenticated` y el claim `sub` del usuario huérfano:
--
--      NEGADO -> new row violates row-level security policy for table "profiles"
--
--    El `except` del controlador se tragaba el error en un `print` y devolvía
--    lista vacía, así que el piloto veía un dashboard roto sin ningún error.
--
-- Tres cambios:
--
-- 1. Policy de INSERT. No agrega ninguna capacidad nueva: el `with check`
--    ata la fila a `auth.uid() = id`, y un usuario ya podía cambiar su propio
--    nombre por UPDATE. Lo único que habilita es crear la fila propia faltante.
--
-- 2. `handle_new_user()` aprende a leer los nombres de OAuth. Hoy sólo mira
--    `first_name`/`last_name`, que Google no manda: manda `full_name`/`name`.
--    Un alta con Google caía a los defaults y se llamaba "New Pilot".
--
-- 3. Backfill de los 5 huérfanos, con la misma regla de nombres.

begin;

-- 1 ------------------------------------------------------------------------
-- Sin esto, el auto-alta del backend no puede escribir y el usuario queda
-- huérfano para siempre.
drop policy if exists "Users can insert own profile" on public.profiles;
create policy "Users can insert own profile"
  on public.profiles
  for insert
  to authenticated
  with check (auth.uid() = id);

-- 2 ------------------------------------------------------------------------
-- `first_name`/`last_name` son las claves que manda la API de Litestar en
-- options.data; `full_name`/`name` son las de Google. Si el nombre viene en una
-- sola palabra, el apellido queda en el default en vez de repetir el nombre.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $function$
declare
  entero       text;
  parsed_first text;
  parsed_last  text;
begin
  entero := nullif(trim(coalesce(new.raw_user_meta_data->>'full_name',
                                 new.raw_user_meta_data->>'name', '')), '');

  parsed_first := coalesce(
    nullif(trim(new.raw_user_meta_data->>'first_name'), ''),
    nullif(split_part(entero, ' ', 1), ''),
    'New');

  parsed_last := coalesce(
    nullif(trim(new.raw_user_meta_data->>'last_name'), ''),
    -- Sin espacio, position() da 0 y el substr arranca pasado el final: ''.
    nullif(trim(substr(entero, coalesce(nullif(position(' ' in entero), 0),
                                        length(entero) + 1))), ''),
    'Pilot');

  insert into public.profiles (id, first_name, last_name, license_type)
  values (new.id, parsed_first, parsed_last, '-')
  on conflict (id) do nothing;

  return new;
end;
$function$;

-- La función es SECURITY DEFINER y sólo se usa como trigger; ningún rol del API
-- necesita EXECUTE (ver 002 y el endurecimiento previo).
revoke execute on function public.handle_new_user() from public, anon, authenticated;

-- 3 ------------------------------------------------------------------------
-- Misma regla de nombres que arriba, aplicada a los que ya quedaron afuera.
insert into public.profiles (id, first_name, last_name, license_type)
select u.id,
       coalesce(nullif(trim(u.raw_user_meta_data->>'first_name'), ''),
                nullif(split_part(n.entero, ' ', 1), ''),
                'New'),
       coalesce(nullif(trim(u.raw_user_meta_data->>'last_name'), ''),
                nullif(trim(substr(n.entero,
                        coalesce(nullif(position(' ' in n.entero), 0),
                                 length(n.entero) + 1))), ''),
                'Pilot'),
       '-'
from auth.users u
cross join lateral (
  select nullif(trim(coalesce(u.raw_user_meta_data->>'full_name',
                              u.raw_user_meta_data->>'name', '')), '') as entero
) n
left join public.profiles p on p.id = u.id
where p.id is null
on conflict (id) do nothing;

commit;


-- ---------------------------------------------------------------------------
-- Verificación. Las tres tienen que dar 0 / 15 / PERMITIDO.
-- ---------------------------------------------------------------------------
-- select count(*) as huerfanos_restantes
--   from auth.users u left join public.profiles p on p.id = u.id
--   where p.id is null;
--
-- select count(*) as perfiles from public.profiles;
--
-- create or replace function pg_temp.probar_insert(uid uuid) returns text as $$
-- declare msg text;
-- begin
--   perform set_config('role', 'authenticated', true);
--   perform set_config('request.jwt.claims',
--     json_build_object('sub', uid, 'role', 'authenticated')::text, true);
--   begin
--     insert into public.profiles (id, first_name, last_name, license_type)
--     values (uid, 'Test', 'Pilot', '-');
--     return 'PERMITIDO';
--   exception when others then
--     get stacked diagnostics msg = MESSAGE_TEXT;
--     return 'NEGADO -> ' || msg;
--   end;
-- end $$ language plpgsql;
