-- 036 — Pasar al CAD desde Vector: la cuenta de ANAC guardada, y el simulador del CAD de cada equipo (2026-10-28).
--
-- Hasta ahora los vuelos llegaban al CAD sólo con el marcador, desde la sesión del piloto en
-- su navegador: Vector nunca veía la contraseña de ANAC. Federico decidió ofrecer también el
-- modo "desde Vector": el piloto que quiere (y anda en el teléfono, donde el marcador no
-- sirve) guarda su usuario y contraseña de ANAC, y el backend entra al CAD por él.
--
-- `cad_conexiones`: una fila por piloto conectado. La contraseña va **cifrada** con una clave
-- que vive sólo en el `.env` del backend (`CAD_CLAVE_CIFRADO`, Fernet): ni la base ni el
-- frontend la ven en claro. `estado` es 'ok' o 'rechazada' (ANAC no la aceptó: no se vuelve a
-- probar hasta que el piloto la escriba de nuevo, para no bloquearle la cuenta).
-- **Sólo el service role la toca**, como `qr_codigos` (033): RLS prendido, sin políticas y los
-- permisos por defecto revocados a mano. Se borra con la cuenta y con "Desconectar".
--
-- `aircraft.cad_simulador`: para un equipo marcado como simulador, cuál es en la lista del CAD
-- (`GetSimuladoresListItem`), su clase (ATD, BATD…) y el modelo que el CAD le asocia. Se elige
-- una vez en el panel. La valida el modelo del backend.

create table if not exists public.cad_conexiones (
  user_id uuid primary key references auth.users (id) on delete cascade,
  usuario text not null check (char_length(usuario) between 1 and 120),
  clave_cifrada text not null,
  estado text not null default 'ok' check (estado in ('ok', 'rechazada')),
  error text check (char_length(error) <= 300),
  conectado_at timestamptz not null default now(),
  usado_at timestamptz
);

alter table public.cad_conexiones enable row level security;
revoke all on table public.cad_conexiones from anon, authenticated;

comment on table public.cad_conexiones is 'La cuenta de ANAC de quien eligió pasar al CAD desde Vector. Contraseña cifrada (CAD_CLAVE_CIFRADO). Sólo service role.';
comment on column public.cad_conexiones.estado is 'ok, o rechazada: ANAC no aceptó la contraseña y no se reintenta hasta que el piloto la escriba de nuevo.';

alter table public.aircraft add column if not exists cad_simulador jsonb;
comment on column public.aircraft.cad_simulador is 'Si es simulador: {id, nombre, clase, modeloId, modelo} del CAD de ANAC.';
