-- 019 — La red con contenido: foto de perfil, publicaciones, aplausos y comentarios.
--
-- ---------------------------------------------------------------------------
-- La regla, una sola vez
-- ---------------------------------------------------------------------------
--
-- **Una publicación la ve quien puede ver el perfil de su autor**: cualquiera si el
-- perfil es público; si es privado, el dueño y sus seguidores aceptados. Esa regla vive
-- en `puede_ver_autor()` y la usan las políticas de las cuatro tablas —las de fotos,
-- aplausos y comentarios la heredan preguntando por la publicación, cuyo RLS ya la
-- aplica—. El backend consulta con el cliente de quien mira (o el anónimo), así que un
-- bug en el código no puede mostrar lo que la base no deja ver.
--
-- `security invoker` a propósito: la función corre con los permisos de quien pregunta.
-- Un anónimo no puede leer `seguimientos`, y no lo necesita: sin `auth.uid()` no sigue a
-- nadie. No hay nada que escalar.
--
-- ---------------------------------------------------------------------------
-- Las fotos
-- ---------------------------------------------------------------------------
--
-- Dos buckets y ninguna política de storage: sólo escribe y lee el service role, desde el
-- backend, que re-codifica cada foto con Pillow (sin EXIF ni ubicación) antes de subirla.
--
-- - `avatares` es **público**: la foto de perfil se ve donde se ve el @, que ya es
--   público. Nombres aleatorios, sin el user_id.
-- - `publicaciones` es **privado**: una foto de un perfil privado no puede quedar a un
--   link de distancia de cualquiera. Se sirve con URLs firmadas que el backend genera
--   recién después de que el RLS dejó pasar la fila.
--
-- **Borrar una cuenta no borra archivos del storage**: el trigger de la 002 borra filas y
-- no puede llamar a la API de storage. `scripts/limpiar_storage.py` barre los huérfanos.

alter table public.perfiles_publicos
  add column if not exists avatar_path text,
  -- Hasta cuándo vio el piloto su Actividad. Lo posterior es el punto rojo.
  add column if not exists actividad_vista_at timestamptz not null default now();

create table public.publicaciones (
  id          uuid primary key default gen_random_uuid(),
  autor       uuid not null references public.perfiles_publicos(user_id) on delete cascade,
  texto       text check (char_length(texto) <= 1000),
  -- La copia de lo que el piloto eligió mostrar de un vuelo al publicar: ruta, duración,
  -- tipo de avión, fecha. Nunca la matrícula. Una copia y no un join a `flights`, porque
  -- `flights` es privada y porque editar el vuelo después no tiene que cambiar lo que ya
  -- se publicó.
  vuelo       jsonb,
  -- De qué vuelo salió, para el autor. No se le devuelve a nadie más.
  vuelo_id    uuid references public.flights(id) on delete set null,
  created_at  timestamptz not null default now()
);
create index publicaciones_autor_fecha_idx on public.publicaciones (autor, created_at desc);

create table public.publicacion_fotos (
  id              uuid primary key default gen_random_uuid(),
  publicacion_id  uuid not null references public.publicaciones(id) on delete cascade,
  path            text not null unique,
  ancho           int not null check (ancho > 0),
  alto            int not null check (alto > 0),
  orden           smallint not null default 0 check (orden between 0 and 3),
  created_at      timestamptz not null default now()
);
create index publicacion_fotos_publicacion_idx on public.publicacion_fotos (publicacion_id, orden);

create table public.aplausos (
  publicacion_id  uuid not null references public.publicaciones(id) on delete cascade,
  user_id         uuid not null references public.perfiles_publicos(user_id) on delete cascade,
  created_at      timestamptz not null default now(),
  primary key (publicacion_id, user_id)
);
create index aplausos_user_idx on public.aplausos (user_id);

create table public.comentarios (
  id              uuid primary key default gen_random_uuid(),
  publicacion_id  uuid not null references public.publicaciones(id) on delete cascade,
  autor           uuid not null references public.perfiles_publicos(user_id) on delete cascade,
  texto           text not null check (char_length(btrim(texto)) between 1 and 500),
  created_at      timestamptz not null default now()
);
create index comentarios_publicacion_idx on public.comentarios (publicacion_id, created_at);

-- ---------------------------------------------------------------------------
-- La regla de visibilidad
-- ---------------------------------------------------------------------------

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
  );
$function$;

-- ---------------------------------------------------------------------------
-- RLS
-- ---------------------------------------------------------------------------

alter table public.publicaciones enable row level security;
create policy "publicaciones_select_visibles" on public.publicaciones
  for select to anon, authenticated using (public.puede_ver_autor(autor));
create policy "publicaciones_insert_propias" on public.publicaciones
  for insert to authenticated with check (auth.uid() = autor);
create policy "publicaciones_delete_propias" on public.publicaciones
  for delete to authenticated using (auth.uid() = autor);
-- Sin update: una publicación no se edita. Se borra y se vuelve a publicar.

alter table public.publicacion_fotos enable row level security;
-- "Existe la publicación" ya aplica su RLS: si no la podés ver, no ves sus fotos.
create policy "publicacion_fotos_select_visibles" on public.publicacion_fotos
  for select to anon, authenticated using (
    exists (select 1 from public.publicaciones p where p.id = publicacion_id)
  );
create policy "publicacion_fotos_insert_propias" on public.publicacion_fotos
  for insert to authenticated with check (
    exists (select 1 from public.publicaciones p where p.id = publicacion_id and p.autor = auth.uid())
  );
create policy "publicacion_fotos_delete_propias" on public.publicacion_fotos
  for delete to authenticated using (
    exists (select 1 from public.publicaciones p where p.id = publicacion_id and p.autor = auth.uid())
  );

alter table public.aplausos enable row level security;
create policy "aplausos_select_visibles" on public.aplausos
  for select to anon, authenticated using (
    exists (select 1 from public.publicaciones p where p.id = publicacion_id)
  );
-- Se aplaude en nombre propio y sólo lo que se puede ver.
create policy "aplausos_insert_propios" on public.aplausos
  for insert to authenticated with check (
    auth.uid() = user_id
    and exists (select 1 from public.publicaciones p where p.id = publicacion_id)
  );
create policy "aplausos_delete_propios" on public.aplausos
  for delete to authenticated using (auth.uid() = user_id);

alter table public.comentarios enable row level security;
create policy "comentarios_select_visibles" on public.comentarios
  for select to anon, authenticated using (
    exists (select 1 from public.publicaciones p where p.id = publicacion_id)
  );
create policy "comentarios_insert_propios" on public.comentarios
  for insert to authenticated with check (
    auth.uid() = autor
    and exists (select 1 from public.publicaciones p where p.id = publicacion_id)
  );
-- Borra su autor, o el de la publicación: es su espacio.
create policy "comentarios_delete_autor_o_dueno" on public.comentarios
  for delete to authenticated using (
    auth.uid() = autor
    or exists (select 1 from public.publicaciones p where p.id = publicacion_id and p.autor = auth.uid())
  );
-- Sin update: un comentario no se edita.

-- ---------------------------------------------------------------------------
-- El resumen del layout, en un solo viaje
-- ---------------------------------------------------------------------------
--
-- El layout del dashboard lo pide en **cada** pantalla. Armado con consultas sueltas
-- eran cinco viajes a us-east-1 (~160 ms cada uno); así es uno, en paralelo con los que
-- el layout ya hacía. Sin fila en `perfiles_publicos`, no devuelve nada.

create or replace function public.resumen_social()
returns table (handle text, avatar_path text, solicitudes_pendientes int, actividad_nueva int)
language sql
stable
security invoker
set search_path = ''
as $function$
  with yo as (
    select p.user_id, p.handle, p.avatar_path, p.actividad_vista_at
    from public.perfiles_publicos p
    where p.user_id = auth.uid()
  )
  select
    yo.handle,
    yo.avatar_path,
    (select count(*) from public.seguimientos s
       where s.seguido = yo.user_id and s.estado = 'pendiente')::int,
    (
      (select count(*) from public.seguimientos s
         where s.seguido = yo.user_id and s.estado = 'aceptado'
           and coalesce(s.aceptado_at, s.created_at) > yo.actividad_vista_at)
      + (select count(*) from public.aplausos a
           join public.publicaciones pu on pu.id = a.publicacion_id
         where pu.autor = yo.user_id and a.user_id <> yo.user_id
           and a.created_at > yo.actividad_vista_at)
      + (select count(*) from public.comentarios c
           join public.publicaciones pu on pu.id = c.publicacion_id
         where pu.autor = yo.user_id and c.autor <> yo.user_id
           and c.created_at > yo.actividad_vista_at)
    )::int
  from yo;
$function$;

-- ---------------------------------------------------------------------------
-- Storage
-- ---------------------------------------------------------------------------

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values
  ('avatares', 'avatares', true, 2097152, array['image/webp']),
  ('publicaciones', 'publicaciones', false, 5242880, array['image/webp'])
on conflict (id) do nothing;
