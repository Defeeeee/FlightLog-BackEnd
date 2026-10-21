-- 032 — La autoridad certificante de cada vuelo, para el CAD de ANAC (2026-10-21).
--
-- El CAD pide, en cada vuelo, quién lo certifica: un ítem de su lista
-- (`GetAutoridadesListItem`: instructor de vuelo, jefe de aeródromo, otros…) y el nombre y
-- apellido de esa persona (Res. ANAC 470/2025, Anexo I, punto 8). El piloto la puede cargar
-- al registrar el vuelo, y el panel "Pasar al CAD" la usa en vez de pedirla de nuevo.
-- Opcional, y una marca del libro como `cad_vuelo_id` (029): no toca el cobro.

alter table public.flights add column if not exists cad_autoridad_id smallint;
alter table public.flights add column if not exists cad_autoridad_nombre text;
alter table public.flights drop constraint if exists flights_cad_autoridad_nombre_largo;
alter table public.flights add constraint flights_cad_autoridad_nombre_largo check (char_length(cad_autoridad_nombre) <= 120);

comment on column public.flights.cad_autoridad_id is 'La autoridad certificante del vuelo: el id de la lista del CAD de ANAC.';
comment on column public.flights.cad_autoridad_nombre is 'El nombre y apellido de quien certifica el vuelo en el CAD.';
