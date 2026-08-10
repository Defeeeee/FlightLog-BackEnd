-- S1 del plan 08 — métricas que define el piloto.
--
-- PCATracker está atado a un único camino (PPA → PCA) con los mínimos escritos en
-- el código. Esto permite que cada piloto arme las suyas sin que nadie hardcodee
-- otra regulación.
--
-- Los filtros van en columnas y no en un jsonb: son un conjunto cerrado y chico, y
-- una columna se puede indexar, validar y leer desde SQL.
--
-- Aplicada en producción el 2026-08-06.
create table public.custom_stats (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references public.profiles(id) on delete cascade,
  name          text not null,
  metric        text not null check (metric in ('horas', 'aterrizajes', 'vuelos')),

  aircraft_id   uuid references public.aircraft(id) on delete set null,
  clase         text,
  purpose       text,
  airport       text,
  window_days   integer check (window_days is null or window_days > 0),

  target        numeric check (target is null or target > 0),

  -- El regex se evalúa en el cliente. Acá sólo se guarda, con el mismo tope de
  -- largo que aplica el frontend: la base no debe aceptar lo que la UI rechaza.
  regex_field   text check (regex_field is null or regex_field in ('route', 'purpose', 'remarks')),
  regex_pattern text check (regex_pattern is null or length(regex_pattern) <= 200),

  position      integer not null default 0,
  created_at    timestamptz not null default now()
);

create index custom_stats_user_id_idx on public.custom_stats (user_id, position);

alter table public.custom_stats enable row level security;

create policy custom_stats_owner on public.custom_stats
  for all
  using (user_id = auth.uid())
  with check (user_id = auth.uid());
