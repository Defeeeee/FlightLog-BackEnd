-- 028 — Las horas de antes de un alumno piloto, con el desglose de la PPA (2026-10-20).
--
-- El alta ofrece arrancar con los totales en vez de cargar vuelo por vuelo (de 16 cuentas,
-- una sola cargó vuelos). Un piloto copia la fila de totales de su libro de papel en las
-- columnas `opening_*`, que son las del libro. El alumno no lleva libro: sus horas se cuentan
-- contra RAAC 61.520(a) —doble mando, solo diurno, solo de travesía, instrucción nocturna,
-- aterrizajes nocturnos, la travesía de 150 NM— y ese desglose no entra en las columnas del
-- libro. Va acá, aparte:
--
--   { "doble_mando": 18.5, "solo": 4.0, "solo_travesia": 1.0,
--     "instruccion_nocturna": 0, "aterrizajes_nocturnos": 0, "travesia_larga": false }
--
-- Aparte y no en `opening_*` también por la regla de Federico (migración 022): las horas
-- de alumno no cuentan una vez rendida la PPA. Lo que vive acá sólo lo lee el alumno.

alter table public.logbooks add column if not exists apertura_ppa jsonb;
alter table public.logbooks drop constraint if exists logbooks_apertura_ppa_objeto;
alter table public.logbooks add constraint logbooks_apertura_ppa_objeto
  check (apertura_ppa is null or (jsonb_typeof(apertura_ppa) = 'object' and pg_column_size(apertura_ppa) < 2000));

comment on column public.logbooks.apertura_ppa is
  'Horas de antes de un alumno piloto, con el desglose de RAAC 61.520(a). Sólo para alumnos.';
