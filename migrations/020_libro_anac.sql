-- 020 — Lo que pide el libro de vuelo en papel y Vector no guardaba.
--
-- El frontend arma el libro en PDF con la hoja de siempre (la del Adjunto A de la Res.
-- ANAC 147/2013, que es la de los libros en papel y la que usa el Libro de Vuelo
-- Electrónico del CAD). Los datos de cada vuelo ya existían; faltaban:
--
-- - **La potencia de la aeronave** ("Potencia: la total en el caso de ser multimotor",
--   Res. ANAC 470/2025, Anexo I, punto 5). En caballos de fuerza (HP).
-- - **El número de licencia** del titular, en el encabezado ("LICENCIA ... Nº").
-- - **El legajo** que asigna la Dirección de Licencias al Personal de ANAC ("LEGAJO Nº").
-- - **Cuántos renglones tiene la hoja** del libro de cada piloto. La hoja del Adjunto A
--   tiene 15, pero los libros que se venden no son todos iguales, y el PDF tiene que
--   cortar donde corta el libro de papel.
-- - **"Cerrar la hoja" en un vuelo.** En el libro de papel a veces se cierra una hoja
--   antes de llenarla (para foliar, para certificar), y lo que queda en blanco se tacha
--   con una sola diagonal. El vuelo marcado es el último renglón de su hoja.
--
-- La potencia, la licencia y el legajo son opcionales y **sin default**: un dato que el
-- piloto no cargó queda en blanco en la hoja, para completar a mano, en vez de
-- inventarse. Los topes son de cordura, no de norma.

alter table public.aircraft
  add column if not exists potencia_hp integer
    check (potencia_hp is null or (potencia_hp > 0 and potencia_hp <= 100000));

alter table public.profiles
  add column if not exists licencia_numero text
    check (licencia_numero is null or char_length(licencia_numero) <= 30),
  add column if not exists legajo text
    check (legajo is null or char_length(legajo) <= 30);

alter table public.logbooks
  add column if not exists renglones_por_hoja integer not null default 15
    check (renglones_por_hoja between 5 and 40);

-- Un default constante: Postgres lo agrega sin reescribir la tabla.
alter table public.flights
  add column if not exists cierra_hoja boolean not null default false;
