-- 021 — Cuidar la red antes de promocionarla: bloquear, reportar y los avisos push.
--
-- ---------------------------------------------------------------------------
-- Bloquear
-- ---------------------------------------------------------------------------
--
-- Bloquear a alguien es que **ninguno de los dos vea lo del otro** y que el bloqueado no
-- pueda volver a seguir. Vive en la base, como el resto de la visibilidad de la red
-- (018 y 019): el backend consulta con el cliente de quien mira, así que el bloqueo vale
-- aunque una pantalla se olvide de filtrarlo.
--
-- - `puede_ver_autor()` suma las dos direcciones: no veo lo de quien me bloqueó, ni lo de
--   quien bloqueé. Eso alcanza a publicaciones, fotos, aplausos y comentarios.
-- - Los comentarios del bloqueado en publicaciones de terceros tampoco se ven. **La
--   excepción son las publicaciones propias**: su autor ve todos los comentarios, porque
--   si no, no podría borrar los del que bloqueó.
-- - Seguir a quien te bloqueó —o a quien bloqueaste— no se puede. Al bloquear, el
--   backend borra los seguimientos en las dos direcciones.
--
-- **El bloqueado no puede saber quién lo bloqueó**: la fila es del que bloquea y el RLS
-- sólo se la muestra a él. Para que las políticas igual puedan preguntarlo, está
-- `me_bloqueo()`, `security definer`, que contesta sólo por el que pregunta.
--
-- ---------------------------------------------------------------------------
-- Reportar
-- ---------------------------------------------------------------------------
--
-- Un reporte se escribe y no se lee: no hay política de `select`. Lo revisa quien
-- administra, con el service role, y el backend le manda un aviso push al escribirse.
--
-- ---------------------------------------------------------------------------
-- Avisos push
-- ---------------------------------------------------------------------------
--
-- Una fila por navegador suscripto (`endpoint` es único). El piloto maneja las suyas;
-- el backend las lee con el service role para mandarle un aviso a otro.

create table public.bloqueos (
  bloqueador  uuid not null references auth.users (id) on delete cascade,
  bloqueado   uuid not null references auth.users (id) on delete cascade,
  created_at  timestamptz not null default now(),
  primary key (bloqueador, bloqueado),
  check (bloqueador <> bloqueado)
);
create index bloqueos_bloqueado_idx on public.bloqueos (bloqueado);

alter table public.bloqueos enable row level security;
create policy "bloqueos_select_propios" on public.bloqueos
  for select to authenticated using (auth.uid() = bloqueador);
create policy "bloqueos_insert_propios" on public.bloqueos
  for insert to authenticated with check (auth.uid() = bloqueador);
create policy "bloqueos_delete_propios" on public.bloqueos
  for delete to authenticated using (auth.uid() = bloqueador);

-- ¿Me bloqueó este piloto? Contesta sólo por `auth.uid()`: no sirve para averiguar los
-- bloqueos de otros. Un anónimo no está bloqueado por nadie.
create or replace function public.me_bloqueo(p_otro uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $function$
  select auth.uid() is not null and exists (
    select 1 from public.bloqueos b
    where b.bloqueador = p_otro and b.bloqueado = auth.uid()
  );
$function$;
revoke all on function public.me_bloqueo(uuid) from public;
grant execute on function public.me_bloqueo(uuid) to anon, authenticated;

-- La regla de visibilidad de la 019, con los bloqueos en las dos direcciones.
create or replace function public.puede_ver_autor(p_autor uuid)
returns boolean
language sql
stable
security invoker
set search_path = ''
as $function$
  select exists (
    select 1 from public.perfiles_publicos p
    where p.user_id = p_autor
      and (
        p.visibilidad = 'publico'
        or p.user_id = auth.uid()
        or exists (
          select 1 from public.seguimientos s
          where s.seguidor = auth.uid() and s.seguido = p.user_id and s.estado = 'aceptado'
        )
      )
      and not public.me_bloqueo(p.user_id)
      and not exists (
        select 1 from public.bloqueos b
        where b.bloqueador = auth.uid() and b.bloqueado = p.user_id
      )
  );
$function$;

drop policy "comentarios_select_visibles" on public.comentarios;
create policy "comentarios_select_visibles" on public.comentarios
  for select to anon, authenticated using (
    exists (select 1 from public.publicaciones p where p.id = publicacion_id)
    and (
      -- En lo propio se ve todo: si no, el autor no podría borrar lo del que bloqueó.
      exists (select 1 from public.publicaciones p where p.id = publicacion_id and p.autor = auth.uid())
      or (
        not public.me_bloqueo(autor)
        and not exists (
          select 1 from public.bloqueos b
          where b.bloqueador = auth.uid() and b.bloqueado = autor
        )
      )
    )
  );

drop policy "seguimientos_insert_seguidor" on public.seguimientos;
create policy "seguimientos_insert_seguidor" on public.seguimientos
  for insert to authenticated with check (
    auth.uid() = seguidor
    and not public.me_bloqueo(seguido)
    and not exists (
      select 1 from public.bloqueos b
      where b.bloqueador = auth.uid() and b.bloqueado = seguido
    )
    and (
      estado = 'pendiente'
      or exists (
        select 1 from public.perfiles_publicos p
        where p.user_id = seguido and p.visibilidad = 'publico'
      )
    )
  );

create table public.reportes (
  id           uuid primary key default gen_random_uuid(),
  -- `set null`: si el que reportó borra su cuenta, el reporte sigue valiendo.
  denunciante  uuid default auth.uid() references auth.users (id) on delete set null,
  tipo         text not null check (tipo in ('perfil', 'publicacion', 'comentario')),
  objetivo     text not null check (char_length(objetivo) between 1 and 100),
  motivo       text not null check (char_length(motivo) between 1 and 500),
  created_at   timestamptz not null default now(),
  revisado_at  timestamptz
);
create index reportes_pendientes_idx on public.reportes (created_at) where revisado_at is null;

alter table public.reportes enable row level security;
create policy "reportes_insert_propios" on public.reportes
  for insert to authenticated with check (auth.uid() = denunciante);

create table public.suscripciones_push (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
  endpoint    text not null unique check (endpoint like 'https://%' and char_length(endpoint) <= 1000),
  p256dh      text not null check (char_length(p256dh) <= 200),
  auth        text not null check (char_length(auth) <= 100),
  created_at  timestamptz not null default now()
);
create index suscripciones_push_user_idx on public.suscripciones_push (user_id);

alter table public.suscripciones_push enable row level security;
create policy "suscripciones_push_select_propias" on public.suscripciones_push
  for select to authenticated using (auth.uid() = user_id);
create policy "suscripciones_push_insert_propias" on public.suscripciones_push
  for insert to authenticated with check (auth.uid() = user_id);
create policy "suscripciones_push_delete_propias" on public.suscripciones_push
  for delete to authenticated using (auth.uid() = user_id);
