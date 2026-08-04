-- Múltiples libros de vuelo (T2.8 / Tier 6 del plan del frontend).
--
-- Se aplica con el MCP de Supabase. Este archivo queda versionado para que la
-- migración sea auditable: el repo no tiene carpeta de migraciones porque el SQL
-- se venía aplicando a mano, y eso deja el esquema sin historia.
--
-- ORDEN OBLIGATORIO: la tabla, el backfill y recién después el NOT NULL. Correr
-- el paso 4 antes del 3 deja vuelos huérfanos y rompe el dashboard.

-- ---------------------------------------------------------------------------
-- 1. Tabla
-- ---------------------------------------------------------------------------
create table if not exists public.logbooks (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  name text not null,
  description text,
  is_default boolean not null default false,
  created_at timestamptz not null default now(),

  -- Saldo inicial. NO es un total suelto a propósito: guardar sólo "500 horas"
  -- dejaría la matriz ANAC mostrando 500 h y 0 de PIC, el PCA Tracker diciendo
  -- que no se cumple ningún requisito, y el Resumen mintiendo en cada tarjeta.
  -- Trae el mismo desglose que un vuelo para que las agregaciones sigan siendo
  -- verdaderas.
  opening_landings      integer not null default 0,
  opening_pic_day_loc   numeric not null default 0,
  opening_pic_day_tra   numeric not null default 0,
  opening_pic_night_loc numeric not null default 0,
  opening_pic_night_tra numeric not null default 0,
  opening_sic_day_loc   numeric not null default 0,
  opening_sic_day_tra   numeric not null default 0,
  opening_sic_night_loc numeric not null default 0,
  opening_sic_night_tra numeric not null default 0,
  opening_imc_pil       numeric not null default 0,
  opening_imc_cop       numeric not null default 0,
  opening_capota        numeric not null default 0,

  constraint logbooks_opening_no_negativo check (
    opening_landings >= 0
    and opening_pic_day_loc >= 0 and opening_pic_day_tra >= 0
    and opening_pic_night_loc >= 0 and opening_pic_night_tra >= 0
    and opening_sic_day_loc >= 0 and opening_sic_day_tra >= 0
    and opening_sic_night_loc >= 0 and opening_sic_night_tra >= 0
    and opening_imc_pil >= 0 and opening_imc_cop >= 0 and opening_capota >= 0
  )
);

create index if not exists logbooks_user_id_idx on public.logbooks (user_id);

-- Un solo libro por defecto por piloto. Índice parcial: la restricción sólo
-- aplica a las filas marcadas.
create unique index if not exists logbooks_un_default_por_usuario
  on public.logbooks (user_id) where is_default;

-- ---------------------------------------------------------------------------
-- 2. RLS — mismo patrón que `documents` y `audit_findings`
-- ---------------------------------------------------------------------------
alter table public.logbooks enable row level security;

create policy "logbooks_select_propios" on public.logbooks
  for select using (auth.uid() = user_id);
create policy "logbooks_insert_propios" on public.logbooks
  for insert with check (auth.uid() = user_id);
create policy "logbooks_update_propios" on public.logbooks
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "logbooks_delete_propios" on public.logbooks
  for delete using (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- 3. Columna en vuelos + backfill
-- ---------------------------------------------------------------------------
-- `on delete no action` es deliberado y NO debe pasarse a cascade: borrar un
-- libro no puede llevarse los vuelos puestos. El backend rechaza el borrado si
-- el libro tiene vuelos; esto es la red de seguridad si alguien borra por SQL.
alter table public.flights
  add column if not exists logbook_id uuid references public.logbooks(id) on delete no action;

create index if not exists flights_logbook_id_idx on public.flights (logbook_id);

-- Un libro por defecto para cada piloto que ya tenga vuelos.
insert into public.logbooks (user_id, name, is_default)
select distinct f.user_id, 'Mi libro', true
from public.flights f
where not exists (
  select 1 from public.logbooks l where l.user_id = f.user_id
);

-- Todos los vuelos existentes van a ese libro. Sin esto, cualquier usuario que
-- ya tenía datos abre la app y ve la bitácora vacía.
update public.flights f
set logbook_id = l.id
from public.logbooks l
where l.user_id = f.user_id
  and l.is_default
  and f.logbook_id is null;

-- ---------------------------------------------------------------------------
-- 4. VERIFICAR ANTES DE SEGUIR
-- ---------------------------------------------------------------------------
-- Tiene que devolver 0. Si no, NO aplicar el NOT NULL de abajo.
--   select count(*) from public.flights where logbook_id is null;
--
-- alter table public.flights alter column logbook_id set not null;
