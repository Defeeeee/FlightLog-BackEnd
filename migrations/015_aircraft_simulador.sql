-- 015 — El simulador es una aeronave más, marcada como tal.
--
-- El piloto anota sus sesiones de simulador en el libro igual que un vuelo: fecha,
-- horarios, el equipo (LV-ASG, tipo C172) y las horas en la columna de **piloto en
-- instrucción terrestre**. Vector tiene esa columna desde siempre —`sim_pil_en_inst`—
-- pero no tenía forma de saber que LV-ASG no vuela.
--
-- ---------------------------------------------------------------------------
-- Por qué una marca en `aircraft` y no un tipo de vuelo aparte
-- ---------------------------------------------------------------------------
--
-- Porque es lo que el piloto ya hace en papel: el simulador ocupa una fila del libro,
-- con su equipo en la columna de aeronave. Un "tipo de entrada" elegido antes del
-- formulario —como hace FlightDeck— obligaría a decidir dos veces lo mismo: primero el
-- tipo y después la aeronave, que ya lo dice.
--
-- Y sobre todo: la marca vive donde **no se puede olvidar**. Se carga una vez al dar de
-- alta el equipo, y a partir de ahí cada fila que lo use queda marcada sola. Un
-- selector por vuelo se olvida, y una hora de simulador contada como hora de vuelo es
-- un requisito inflado en el tracker de la licencia.
--
-- ---------------------------------------------------------------------------
-- Qué cambia una fila marcada
-- ---------------------------------------------------------------------------
--
-- **No suma a la experiencia total.** Es la razón de ser de esta columna: las 200 h de
-- 61.620 son horas de vuelo, y una sesión de simulador no lo es. Hoy `duration`
-- alimenta ese medidor sin distinguir, así que sin esta marca cada sesión inflaría el
-- requisito más grande del tracker — el error que manda a alguien a presentarse antes
-- de tiempo.
--
-- Las horas **sí** cuentan para instrumentos, con el tope de 5 h que ya aplica
-- `pca-progress.ts` sobre el acumulado.
--
-- ---------------------------------------------------------------------------
-- `NOT NULL DEFAULT false`, a diferencia de la 014
-- ---------------------------------------------------------------------------
--
-- Acá el default **no** es inventar un dato. En la 014 un `cruise_tas_kt` de 110 habría
-- sido una velocidad que nadie cargó, indistinguible de una real. Esto es distinto: una
-- aeronave que ya existe en la base **es un avión**, porque hasta hoy no había otra
-- cosa que cargar. `false` es el hecho, no una suposición.
--
-- Y siendo booleano, un null obligaría a que cada lector decidiera qué hacer con "no
-- sé si vuela", que es una pregunta que no tiene buena respuesta.

ALTER TABLE public.aircraft
  ADD COLUMN IF NOT EXISTS is_simulator boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN public.aircraft.is_simulator IS
  'true = dispositivo de entrenamiento (FSTD), no aeronave. Sus horas van a la columna '
  'de instrucción terrestre y NO cuentan como experiencia de vuelo en 61.620.';
