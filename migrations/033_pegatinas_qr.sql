-- 033 — Las pegatinas con QR: códigos, escaneos y de qué pegatina vino cada cuenta (2026-10-23).
--
-- Federico imprime muchas pegatinas iguales, cada una con su código (`/q/K7P2`), y después
-- las asigna a un lugar ("Cartelera SADF") escaneándola él mismo. Quiere saber cuántos la
-- escanearon y cuántas cuentas nuevas salieron de cada una.
--
-- `qr_codigos`: un renglón por pegatina impresa. `etiqueta` es dónde se pegó; NULL hasta
-- que se asigna. `lote` agrupa las que se imprimieron juntas.
-- `qr_escaneos`: un renglón por escaneo. Sin IP, sin navegador y sin cuenta: sólo cuándo y
-- si quien escaneó ya tenía sesión en Vector.
-- `profiles.origen_qr`: la pegatina de la que vino una cuenta, si se creó dentro de los 30
-- días del escaneo (lo decide el backend, `services/qr.py`). Nunca se pisa.
--
-- **Sólo el service role toca las dos tablas**, como `mail_eventos` (023): RLS prendido, sin
-- políticas y los permisos por defecto revocados a mano.

create table if not exists public.qr_codigos (
  codigo text primary key check (codigo ~ '^[A-Z0-9]{4,8}$'),
  etiqueta text check (char_length(etiqueta) <= 80),
  lote text check (char_length(lote) <= 40),
  creado_at timestamptz not null default now(),
  asignado_at timestamptz
);

create table if not exists public.qr_escaneos (
  id bigint generated always as identity primary key,
  codigo text not null references public.qr_codigos (codigo) on delete cascade,
  con_sesion boolean not null default false,
  creado_at timestamptz not null default now()
);

create index if not exists qr_escaneos_codigo_idx on public.qr_escaneos (codigo);

alter table public.profiles add column if not exists origen_qr text references public.qr_codigos (codigo) on delete set null;

alter table public.qr_codigos enable row level security;
alter table public.qr_escaneos enable row level security;

revoke all on table public.qr_codigos from anon, authenticated;
revoke all on table public.qr_escaneos from anon, authenticated;
revoke all on sequence public.qr_escaneos_id_seq from anon, authenticated;

comment on table public.qr_codigos is 'Las pegatinas con QR impresas, y dónde se pegó cada una. Sólo service role.';
comment on table public.qr_escaneos is 'Cada escaneo de una pegatina: cuándo y si había sesión. Sin datos de quien escanea. Sólo service role.';
comment on column public.profiles.origen_qr is 'La pegatina con QR de la que vino la cuenta (dentro de los 30 días del escaneo).';
