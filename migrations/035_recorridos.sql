-- 035 — El recorrido real de cada vuelo, de ADS-B (2026-10-24, etapa 2).
--
-- El grabador (034) guarda las posiciones de los aviones de los Hangares y las borra a los
-- 30 días. Cuando un piloto abre un vuelo suyo, el backend busca el tramo de su avión entre su
-- despegue y su aterrizaje (`services/adsb.py`), y lo copia acá: el recorrido queda con el
-- vuelo aunque las posiciones se borren.
--
-- **Tabla aparte y no una columna de `flights`**: varias lecturas de `flights` piden todas
-- las columnas (el inicio, la bitácora, la auditoría, el copiloto), y unos KB por vuelo
-- viajarían en cada una.
--
-- **Sólo el service role**, como las otras tablas de ADS-B: el backend comprueba primero, con
-- el cliente del piloto, que el vuelo es suyo. Borrar el vuelo borra su recorrido.

create table if not exists public.vuelo_recorridos (
  flight_id uuid primary key references public.flights (id) on delete cascade,
  user_id uuid not null references auth.users (id) on delete cascade,
  -- `{"t0": epoch, "p": [[segundos desde t0, lat, lon, altitud, velocidad], ...], "fuente": "adsb.fi"}`
  recorrido jsonb not null,
  creado_at timestamptz not null default now()
);

alter table public.vuelo_recorridos enable row level security;
revoke all on table public.vuelo_recorridos from anon, authenticated;

comment on table public.vuelo_recorridos is 'El recorrido ADS-B de un vuelo, copiado de adsb_posiciones al reconocerlo. Sólo service role.';
