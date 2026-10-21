-- 029 — Qué vuelos ya están en el CAD de ANAC (2026-10-21).
--
-- Desde el 1/11/2025 cada vuelo se declara en el Casillero Aeronáutico Digital (Res. ANAC
-- 470/2025). Vector los pasa desde el navegador del piloto, con su sesión del CAD (ver la
-- bitácora del frontend, 2026-10-21): el CAD contesta con el id del vuelo creado, y acá se
-- guarda para no volver a mandarlo.
--
-- `cad_vuelo_id`: el `vueloTripulanteID` del CAD. `cad_cargado_at`: cuándo se anotó, con la
-- hora del servidor. Son marcas, como `cierra_hoja` (migración 020): cambiarlas no toca el
-- cobro, la auditoría ni los vencimientos.

alter table public.flights add column if not exists cad_vuelo_id bigint;
alter table public.flights add column if not exists cad_cargado_at timestamptz;

comment on column public.flights.cad_vuelo_id is
  'El id del vuelo en el CAD de ANAC (vueloTripulanteID), si ya se pasó.';
comment on column public.flights.cad_cargado_at is 'Cuándo se anotó que el vuelo está en el CAD.';
