-- 031 — Vuelos que el piloto no pasa al CAD de ANAC (2026-10-21).
--
-- En el panel "Pasar al CAD" (ver la bitácora del frontend, 2026-10-21) el piloto puede
-- sacar de la lista un vuelo que no va al CAD:
--   'foliado'  — ya está en un libro foliado antes del CAD (el CAD pide sólo lo posterior);
--   'ignorado' — no lo quiere pasar (un simulador, o uno que carga a mano).
-- Es una marca, como `cad_vuelo_id` (029): no toca el cobro, la auditoría ni los vencimientos.
-- Null es "pendiente", y volver a null lo devuelve a la lista.

alter table public.flights add column if not exists cad_omitido text;
alter table public.flights drop constraint if exists flights_cad_omitido_check;
alter table public.flights add constraint flights_cad_omitido_check check (cad_omitido in ('foliado', 'ignorado'));

comment on column public.flights.cad_omitido is
  'Por qué el vuelo no se pasa al CAD de ANAC: foliado (antes del CAD) o ignorado. Null: pendiente.';
