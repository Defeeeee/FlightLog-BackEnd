-- 034 — Los recorridos ADS-B de los aviones del Hangar, etapa 1: medir (2026-10-23).
--
-- Los livianos de escuela transmiten la matrícula como indicativo (`LVS114`) aunque no
-- figuren en las bases de códigos ADS-B (medido el 2026-10-23 contra adsb.lol). El historial
-- de días anteriores no se puede pedir: adsb.lol lo bloquea a programas, y el de ADS-B
-- Exchange es pago. Así que Vector graba lo que ve en vivo (`grabador_adsb.py`), sólo de los
-- aviones que están en algún Hangar, para después proponer los horarios reales al registrar
-- un vuelo. Esta etapa sólo graba: nada se muestra todavía.
--
-- `adsb_aviones`: el código ADS-B (24 bits, hex) de cada matrícula, aprendido la primera vez
-- que se la ve. Por matrícula y no por fila de `aircraft`: el mismo avión de escuela está en
-- el Hangar de varios pilotos.
-- `adsb_posiciones`: cada posición vista. Los datos son de adsb.lol (ODbL). Se borran a los
-- 30 días (lo hace el grabador): lo que sirva de un vuelo se va a copiar al vuelo.
--
-- **Sólo el service role**, como las tablas de mails y de pegatinas.

create table if not exists public.adsb_aviones (
  matricula text primary key check (matricula ~ '^[A-Z0-9]{2,10}$'),
  hex text not null check (hex ~ '^[0-9a-f]{6}$'),
  visto_at timestamptz not null default now()
);

create table if not exists public.adsb_posiciones (
  id bigint generated always as identity primary key,
  matricula text not null,
  hex text not null,
  visto_at timestamptz not null,
  lat double precision not null,
  lon double precision not null,
  -- Pies, barométrica; NULL en tierra.
  altitud integer,
  -- Nudos sobre el terreno.
  velocidad real,
  en_tierra boolean not null default false
);

create index if not exists adsb_posiciones_matricula_idx on public.adsb_posiciones (matricula, visto_at);
create index if not exists adsb_posiciones_visto_idx on public.adsb_posiciones (visto_at);

alter table public.adsb_aviones enable row level security;
alter table public.adsb_posiciones enable row level security;

revoke all on table public.adsb_aviones from anon, authenticated;
revoke all on table public.adsb_posiciones from anon, authenticated;
revoke all on sequence public.adsb_posiciones_id_seq from anon, authenticated;

comment on table public.adsb_aviones is 'El código ADS-B de cada matrícula de algún Hangar, aprendido al verla. Sólo service role.';
comment on table public.adsb_posiciones is 'Posiciones ADS-B (adsb.lol, ODbL) de los aviones de algún Hangar. Se borran a los 30 días. Sólo service role.';
