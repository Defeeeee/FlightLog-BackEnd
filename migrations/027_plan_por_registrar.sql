-- 027 — El mail "¿Cargamos tu vuelo?" de un plan de vuelo ya volado (2026-10-20).
--
-- Federico pidió un mail una hora y media después de la llegada estimada de un plan
-- presentado, para que el piloto vaya a cargar el vuelo. Uno por plan: `recordatorio_at`
-- es cuándo salió, y el barrido no vuelve a elegir un plan que lo tiene. La hora la decide
-- el frontend (`lib/plan-cierre.ts`, la misma cuenta que el "¿Ya volaste?" del inicio).
--
-- `mail_envios.tipo` suma `plan-por-registrar`, para que el panel lo mida como los otros.

alter table public.planes_de_vuelo add column if not exists recordatorio_at timestamptz;
comment on column public.planes_de_vuelo.recordatorio_at is
  'Cuándo salió el mail para cargar el vuelo de este plan. Uno por plan.';

alter table public.mail_envios drop constraint if exists mail_envios_tipo_check;
alter table public.mail_envios add constraint mail_envios_tipo_check
  check (tipo in ('primer-vuelo', 'resumen-mensual', 'briefing', 'novedades', 'plan-por-registrar'));
