-- 017 — Idempotencia de los briefings por correo.
--
-- El cron de envíos se ejecuta y dispara emails. Sin embargo, si por algún motivo
-- temporal hay un reintento del lado del frontend o un timeout, no teníamos forma
-- de saber si el mail ya había salido. 
-- Esta columna previene el reenvío de un briefing ya procesado, actuando como
-- marca permanente para la notificación.

ALTER TABLE public.planned_flights
  ADD COLUMN IF NOT EXISTS briefing_sent_at timestamp with time zone;

COMMENT ON COLUMN public.planned_flights.briefing_sent_at IS
  'Marca de tiempo de cuándo el cron de briefing diario mandó el correo. Previene dobles envíos si el cron reintenta.';
