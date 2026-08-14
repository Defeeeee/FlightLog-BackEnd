-- 010 — Horarios tentativos en los vuelos programados.
--
-- Un plan sin hora sirve para el calendario pero no para completarlo: `logFlight`
-- exige `takeoff` y `landing`, así que el piloto igual tenía que tipearlos a mano
-- al confirmar. Con la hora guardada, el prefill llega con todo puesto y confirmar
-- un vuelo pasa a ser realmente un botón.
--
-- ---------------------------------------------------------------------------
-- UTC, y no es un detalle
-- ---------------------------------------------------------------------------
-- `flights.takeoff` y `flights.landing` se guardan como `${date}T${HH:mm}:00Z` —
-- **UTC**— y el motor de auditoría los lee así para detectar superposiciones. El
-- formulario de vuelo tiene un interruptor local/UTC que cambia **sólo lo que se
-- muestra**; los campos ocultos postean UTC siempre. Su propio comentario avisa
-- que invertir eso *"movería todos los vuelos tres horas y rompería en silencio la
-- detección de superposiciones"*.
--
-- Estas dos columnas siguen la misma regla: **lo que se guarda acá es UTC.** El
-- calendario ofrece el mismo interruptor para mostrarlas en hora local, y la
-- conversión vive en un solo lugar del frontend (`src/lib/horarios.ts`, con tests)
-- en vez de repetida en cada formulario.
--
-- Las dos son nullable: un plan a diez días puede ser "el sábado vuelo" y nada
-- más, y esa sigue siendo la forma mínima de programar.
--
-- Sin CHECK de que `landing_time > takeoff_time`: un vuelo que cruza medianoche
-- tiene el aterrizaje "antes" del despegue en hora de reloj, y la restricción
-- rechazaría un plan perfectamente válido. La duración real la calcula el
-- formulario al completarlo, que es donde están las dos fechas.

alter table public.planned_flights
  add column if not exists takeoff_time time,
  add column if not exists landing_time  time;

comment on column public.planned_flights.takeoff_time is
  'Hora tentativa de despegue, en UTC — misma convención que flights.takeoff. NULL si el plan todavía no tiene hora.';
comment on column public.planned_flights.landing_time is
  'Hora tentativa de aterrizaje, en UTC. NULL si no se estimó.';


-- ---------------------------------------------------------------------------
-- Verificación.
-- ---------------------------------------------------------------------------
-- select column_name, data_type, is_nullable from information_schema.columns
--   where table_schema='public' and table_name='planned_flights'
--     and column_name in ('takeoff_time','landing_time');
--   -- esperado: dos filas, "time without time zone", YES
--
-- Y la invariante de siempre, después de programar con hora:
-- select count(*) from public.flights;
--   -- esperado: sin cambios. Un plan con hora sigue sin ser un vuelo.
