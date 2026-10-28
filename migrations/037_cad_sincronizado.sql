-- 037 — El CAD se sincroniza solo (2026-10-28).
--
-- Para quien conectó su cuenta de ANAC (036), Vector compara sus vuelos con los del CAD al
-- abrir la app, como mucho cada 12 horas (`POST /cad/sincronizar`): desmarca lo que se borró
-- allá, marca lo que se cargó a mano y es el mismo vuelo, y guarda el estado de cada uno.
--
-- `cad_conexiones.sincronizado_at`: la última vez, para no entrar a ANAC de más (ANAC ya
-- bloqueó la IP del VPS una vez; ahora se sale por el proxy de amenaba).
-- `flights.cad_estado`: el estado del vuelo en el CAD, tal como lo escribe el CAD
-- ("PENDIENTE DE DDJJ", …). Null si no se sabe. Lo muestra la Bitácora y el inicio recuerda
-- los pendientes de declarar.

alter table public.cad_conexiones add column if not exists sincronizado_at timestamptz;
alter table public.flights add column if not exists cad_estado text check (char_length(cad_estado) <= 60);
comment on column public.flights.cad_estado is 'El estado del vuelo en el CAD de ANAC ("PENDIENTE DE DDJJ", …), de la última sincronización.';
