-- 018 — La red social: el @ de cada piloto y a quién sigue.
--
-- ---------------------------------------------------------------------------
-- Por qué dos tablas nuevas y no columnas en `profiles`
-- ---------------------------------------------------------------------------
--
-- `profiles` tiene RLS de "cada uno ve lo suyo", y así tiene que seguir: ahí viven el
-- WhatsApp, la clave de API y el acceso a Jeppesen. Buscar pilotos exige leer el @ y
-- el nombre **de otros**, así que lo que se publica vive aparte, en una tabla que es
-- pública por construcción: sólo tiene lo que el piloto eligió mostrar al crear su @.
-- Tener una fila acá **es** haberse sumado a la red; sin fila, no existe para nadie.
--
-- Las horas no se guardan en ninguna tabla pública. Las calcula el backend al servir
-- un perfil (`GET /publico/pilotos/{handle}`), después de decidir si el que mira
-- puede verlas, y sólo salen agregadas: ninguna fila de `flights` cruza la API.
--
-- ---------------------------------------------------------------------------
-- La privacidad se cumple dos veces
-- ---------------------------------------------------------------------------
--
-- El backend decide quién ve qué, y además el RLS de abajo lo impide en la base: un
-- `insert` en `seguimientos` como 'aceptado' hacia un perfil privado lo rechaza la
-- política aunque el código tenga un bug. Cuatro políticas explícitas por tabla, y no
-- una `for all`, por la misma razón que en la 009: la 006 existió porque a `profiles`
-- le faltaba la de `insert` y nadie lo vio.

create table public.perfiles_publicos (
  -- `profiles` y no `auth.users`: el borrado de cuenta ya borra `profiles` (ver 002),
  -- y desde ahí esto cae en cascada junto con todos los seguimientos.
  user_id         uuid primary key references public.profiles(id) on delete cascade,
  -- Minúsculas, 3 a 20 caracteres, empieza y termina con letra o número, sin dos
  -- puntos seguidos. Las palabras reservadas se validan en el backend
  -- (`src/services/social.py`): cambian más seguido que un CHECK.
  handle          text not null unique
                    check (handle ~ '^[a-z0-9][a-z0-9._]{1,18}[a-z0-9]$' and handle !~ '\.\.'),
  nombre_visible  text not null check (char_length(btrim(nombre_visible)) between 1 and 60),
  licencia        text check (char_length(licencia) <= 20),
  bio             text check (char_length(bio) <= 160),
  -- Público por defecto, por decisión de Federico (2026-09-22): crear el @ es el
  -- consentimiento, y el formulario dice qué se publica antes de confirmar.
  visibilidad     text not null default 'publico' check (visibilidad in ('publico', 'privado')),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create table public.seguimientos (
  seguidor     uuid not null references public.perfiles_publicos(user_id) on delete cascade,
  seguido      uuid not null references public.perfiles_publicos(user_id) on delete cascade,
  -- A un perfil público se lo sigue directo ('aceptado'); a uno privado, con una
  -- solicitud ('pendiente') que el seguido acepta o borra.
  estado       text not null check (estado in ('pendiente', 'aceptado')),
  created_at   timestamptz not null default now(),
  aceptado_at  timestamptz,
  primary key (seguidor, seguido),
  check (seguidor <> seguido)
);

-- Contar seguidores y listar solicitudes pendientes, las dos consultas por seguido.
create index seguimientos_seguido_estado_idx on public.seguimientos (seguido, estado);

-- ---------------------------------------------------------------------------
-- RLS
-- ---------------------------------------------------------------------------

alter table public.perfiles_publicos enable row level security;

-- Público de verdad: `anon` incluido, porque el perfil se abre con el link sin cuenta.
-- No hay nada en esta tabla que el piloto no haya elegido publicar.
create policy "perfiles_publicos_select_todos" on public.perfiles_publicos
  for select to anon, authenticated using (true);
create policy "perfiles_publicos_insert_propio" on public.perfiles_publicos
  for insert to authenticated with check (auth.uid() = user_id);
create policy "perfiles_publicos_update_propio" on public.perfiles_publicos
  for update to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "perfiles_publicos_delete_propio" on public.perfiles_publicos
  for delete to authenticated using (auth.uid() = user_id);

alter table public.seguimientos enable row level security;

-- Cada uno ve sólo los seguimientos en los que es parte. Los contadores de un perfil
-- ajeno los arma el backend con service role, y salen como números.
create policy "seguimientos_select_partes" on public.seguimientos
  for select to authenticated using (auth.uid() = seguidor or auth.uid() = seguido);
-- Se sigue sólo en nombre propio, y 'aceptado' de entrada sólo si el seguido es
-- público. Hacia un privado, lo único que se puede crear es una solicitud.
create policy "seguimientos_insert_seguidor" on public.seguimientos
  for insert to authenticated with check (
    auth.uid() = seguidor
    and (
      estado = 'pendiente'
      or exists (
        select 1 from public.perfiles_publicos p
        where p.user_id = seguido and p.visibilidad = 'publico'
      )
    )
  );
-- Aceptar es del seguido. Y sólo puede tocar el estado: con permiso sobre la fila
-- entera, podría reescribir `seguidor` y fabricarse seguidores con filas ajenas.
create policy "seguimientos_update_seguido" on public.seguimientos
  for update to authenticated using (auth.uid() = seguido) with check (auth.uid() = seguido);
revoke update on public.seguimientos from anon, authenticated;
grant update (estado, aceptado_at) on public.seguimientos to authenticated;
-- Dejar de seguir, cancelar una solicitud, rechazarla o sacar a un seguidor: es un
-- delete de cualquiera de las dos partes.
create policy "seguimientos_delete_partes" on public.seguimientos
  for delete to authenticated using (auth.uid() = seguidor or auth.uid() = seguido);

-- ---------------------------------------------------------------------------
-- updated_at
-- ---------------------------------------------------------------------------

create or replace function public.perfiles_publicos_touch()
returns trigger
language plpgsql
set search_path to ''
as $function$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$function$;

create trigger perfiles_publicos_touch_trigger
  before update on public.perfiles_publicos
  for each row execute function public.perfiles_publicos_touch();
