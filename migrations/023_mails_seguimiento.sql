-- 023 — Seguimiento propio de los mails: envíos, aperturas y clics (2026-10-02).
--
-- Federico quiere saber si los mails se abren y qué links se tocan, medido por Vector y
-- no por el proveedor: de nueve pilotos que recibieron el recordatorio del alta, seis no
-- volvieron, y no había forma de saber si lo habían visto.
--
-- `mail_envios`: un renglón por mail que salió. El id lo genera el frontend antes de
-- mandar, porque va adentro de los links del mail.
-- `mail_eventos`: una apertura (la imagen de 1×1 que se pide al abrirlo) o un clic (la
-- redirección por la que pasan los links). `destino` es a dónde iba el link, sin query
-- string: la ruta de Vector o el dominio de afuera.
--
-- **Qué no es:** una apertura no prueba que alguien lo leyó (Apple Mail baja las imágenes
-- solo), y un clic puede ser el filtro de un correo corporativo. Son indicios, y el panel
-- lo dice.
--
-- **Sólo el service role las toca.** RLS prendido y sin políticas, y los permisos por
-- defecto del proyecto (que les dan todo a `anon` y `authenticated`) revocados a mano:
-- la trampa de la migración a sa-east-1.
--
-- Borrar la cuenta borra sus envíos y, con ellos, sus eventos.

create table if not exists public.mail_envios (
  id uuid primary key,
  user_id uuid references auth.users (id) on delete cascade,
  tipo text not null check (tipo in ('primer-vuelo', 'resumen-mensual', 'briefing', 'novedades')),
  -- Qué edición: el mes del resumen o la tanda de novedades. NULL donde no aplica.
  clave text,
  enviado_at timestamptz not null default now()
);

create index if not exists mail_envios_user_idx on public.mail_envios (user_id);
create index if not exists mail_envios_tipo_clave_idx on public.mail_envios (tipo, clave);

create table if not exists public.mail_eventos (
  id bigint generated always as identity primary key,
  envio_id uuid not null references public.mail_envios (id) on delete cascade,
  tipo text not null check (tipo in ('apertura', 'clic')),
  destino text,
  creado_at timestamptz not null default now()
);

create index if not exists mail_eventos_envio_idx on public.mail_eventos (envio_id);

alter table public.mail_envios enable row level security;
alter table public.mail_eventos enable row level security;

revoke all on table public.mail_envios from anon, authenticated;
revoke all on table public.mail_eventos from anon, authenticated;
revoke all on sequence public.mail_eventos_id_seq from anon, authenticated;

comment on table public.mail_envios is 'Un renglón por mail enviado. Sólo service role.';
comment on table public.mail_eventos is 'Aperturas y clics de los mails. Indicios, no certezas. Sólo service role.';
