-- 038 — Cuándo leyó Vector el CAD del piloto por última vez (2026-10-29).
--
-- Desde la 2.36.0 el CAD lo lee el navegador del piloto (la extensión o el marcador) y el
-- backend recibe la lista (`POST /cad/conciliar`). El estado de cada vuelo (`flights.cad_estado`,
-- 037) es el de esa lectura: la Bitácora y el inicio dicen de cuándo es, y recomiendan
-- actualizarlo si pasaron días. `cad_conexiones.sincronizado_at` era sólo del modo "desde
-- Vector", que quedó apagado.

alter table public.profiles add column if not exists cad_leido_at timestamptz;
comment on column public.profiles.cad_leido_at is 'La última vez que Vector leyó el CAD de ANAC del piloto (extensión o marcador).';
