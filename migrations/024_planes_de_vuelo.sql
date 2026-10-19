-- 024 — El plan de vuelo: planes guardados, el perfil del avión para el plan y la firma (2026-10-19).
--
-- Hasta acá el plan de vuelo para EANA se armaba en el planificador y no se guardaba:
-- cada vez se volvía a tipear todo. Federico usa FPL.AR (28 planes en dos meses, casi
-- todos repetidos: SADF local, SADF–SAAK, SADM–SRDL), y lo que le ahorra tiempo es
-- "duplicar" y un perfil del avión que llena casi todo el formulario.
--
-- Tres cosas:
--
-- 1. `planes_de_vuelo`: un plan por fila. `formulario` es el estado completo del
--    formulario (casillas 7 a 19, la oficina ARO elegida), tal como lo edita el
--    frontend; las columnas sueltas (`salida`, `destino`, `matricula`, `dof`, `eobt`)
--    son una copia para la lista, para no traer el formulario entero de 50 planes.
--
--    **Un plan de vuelo no es un vuelo**, igual que `planned_flights` (migración 009):
--    ninguna función de agregación lee esta tabla. Se presenta antes de volar, y el
--    vuelo puede no ocurrir nunca.
--
-- 2. `aircraft.plan_vuelo`: lo que no cambia entre vuelos de un mismo avión —equipo
--    (casilla 10), NAV/PBN/PER/OPR (18), color, ELT, una observación fija (19)—. Antes
--    vivía en el navegador del piloto y se perdía al cambiar de teléfono.
--
-- 3. `firmas_plan_vuelo`: la firma del piloto, un PNG. En una tabla aparte y no en
--    `profiles` porque el perfil se lee en cada pantalla del dashboard, y una firma son
--    decenas de KB que sólo hacen falta al armar el PDF del plan.
--
-- RLS con las cuatro políticas explícitas, como en la 009: cada piloto ve y toca sólo lo
-- suyo. `anon` no tiene nada que hacer acá.

alter table public.aircraft add column if not exists plan_vuelo jsonb;

comment on column public.aircraft.plan_vuelo is
  'Lo fijo del avión para el plan de vuelo: casilla 10, NAV/PBN/PER/OPR, color, ELT, observación fija. NULL = no cargado.';


create table if not exists public.planes_de_vuelo (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references public.profiles(id) on delete cascade,
  -- `set null`: dar de baja el avión no borra los planes del piloto.
  aircraft_id   uuid references public.aircraft(id) on delete set null,

  formulario    jsonb not null,
  -- El frontend dice si le falta algo: la validación de cada casilla vive allá, pura y testeada.
  completo      boolean not null default false,

  -- Copia para la lista.
  salida        text,
  destino       text,
  matricula     text,
  dof           date,
  eobt          text,

  -- Cuándo se bajó o se compartió el PDF por última vez.
  descargado_at timestamptz,
  -- Las demoras (DLA) avisadas: [{ "eobt": "1930", "dof": "2026-10-20", "creada": "…" }].
  demoras       jsonb not null default '[]'::jsonb,

  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),

  constraint planes_de_vuelo_formulario_tamano check (pg_column_size(formulario) < 65536)
);

create index if not exists planes_de_vuelo_user_updated_idx
  on public.planes_de_vuelo (user_id, updated_at desc);

alter table public.planes_de_vuelo enable row level security;

create policy "planes_de_vuelo_select_propios" on public.planes_de_vuelo
  for select using (auth.uid() = user_id);
create policy "planes_de_vuelo_insert_propios" on public.planes_de_vuelo
  for insert with check (auth.uid() = user_id);
create policy "planes_de_vuelo_update_propios" on public.planes_de_vuelo
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "planes_de_vuelo_delete_propios" on public.planes_de_vuelo
  for delete using (auth.uid() = user_id);

create or replace function public.planes_de_vuelo_touch()
returns trigger
language plpgsql
set search_path to ''
as $function$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$function$;

drop trigger if exists planes_de_vuelo_touch_trigger on public.planes_de_vuelo;
create trigger planes_de_vuelo_touch_trigger
  before update on public.planes_de_vuelo
  for each row execute function public.planes_de_vuelo_touch();

revoke all on table public.planes_de_vuelo from anon;

comment on table public.planes_de_vuelo is
  'Planes de vuelo (FPL) del piloto. NO son vuelos: ninguna agregación de horas lee esta tabla.';


create table if not exists public.firmas_plan_vuelo (
  user_id     uuid primary key references public.profiles(id) on delete cascade,
  -- data URL de un PNG con fondo transparente.
  png         text not null check (png like 'data:image/png;base64,%' and length(png) < 300000),
  updated_at  timestamptz not null default now()
);

alter table public.firmas_plan_vuelo enable row level security;

create policy "firmas_plan_vuelo_select_propia" on public.firmas_plan_vuelo
  for select using (auth.uid() = user_id);
create policy "firmas_plan_vuelo_insert_propia" on public.firmas_plan_vuelo
  for insert with check (auth.uid() = user_id);
create policy "firmas_plan_vuelo_update_propia" on public.firmas_plan_vuelo
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "firmas_plan_vuelo_delete_propia" on public.firmas_plan_vuelo
  for delete using (auth.uid() = user_id);

revoke all on table public.firmas_plan_vuelo from anon;

comment on table public.firmas_plan_vuelo is 'La firma del piloto para el plan de vuelo (PNG). Sólo la propia.';


-- ---------------------------------------------------------------------------
-- Verificación.
-- ---------------------------------------------------------------------------
-- select polname from pg_policy where polrelid = 'public.planes_de_vuelo'::regclass order by 1;
--   -- esperado: las cuatro
-- select polname from pg_policy where polrelid = 'public.firmas_plan_vuelo'::regclass order by 1;
--   -- esperado: las cuatro
-- select column_name from information_schema.columns
--   where table_schema = 'public' and table_name = 'aircraft' and column_name = 'plan_vuelo';
