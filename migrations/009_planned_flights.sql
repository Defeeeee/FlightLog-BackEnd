-- C0 del plan 11 — vuelos programados.
--
-- El piloto anota lo que va a volar **antes** de volarlo. Después el dashboard le
-- pregunta si lo voló, y completar el registro pasa a ser una confirmación en vez
-- de una carga de datos hecha de memoria tres días más tarde.
--
-- ---------------------------------------------------------------------------
-- Por qué una tabla aparte y no una columna `status` en `flights`
-- ---------------------------------------------------------------------------
-- Un vuelo programado es una **intención**. Un vuelo es el **registro legal de algo
-- que ocurrió**. Meterlos en la misma tabla obligaría a que *cada* consulta que ya
-- existe —`summary.ts`, `anacMatrix`, el motor de auditoría, `pilot-status`, los
-- totales del dashboard, el export CSV, el PDF del backend— sume un filtro nuevo.
--
-- **Un solo filtro olvidado le infla las horas a alguien en un documento
-- regulatorio**, y ese error no se ve: el número simplemente queda más alto.
--
-- Y hay un tercer motivo, más concreto que los dos anteriores: **`POST /flights`
-- tiene efectos**. `create_flight` llama a `_sync_flight_transaction`, que en modo
-- balance le **cobra la hora al saldo del piloto**, y después recalcula la
-- auditoría. Un plan viviendo en `flights` cobraría plata por un vuelo que no
-- ocurrió, y la regla de superposición de la auditoría empezaría a marcar planes
-- contra vuelos reales.
--
-- Con la tabla aparte el peor caso es al revés: que un vuelo programado no aparezca
-- en alguna vista. Eso se ve y se arregla.
--
-- **Invariante:** ninguna función de agregación recibe jamás una fila de esta
-- tabla. Si alguna vez hace falta cruzarlas, se cruza en la vista, nunca en el
-- cálculo de horas.

create table public.planned_flights (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references public.profiles(id) on delete cascade,

  date            date not null,

  -- Nullable a propósito: se puede programar "el sábado a Rosario" sin haber
  -- decidido todavía con qué avión. `set null` y no `cascade` porque dar de baja
  -- una aeronave no puede borrar los planes del piloto.
  aircraft_id     uuid references public.aircraft(id) on delete set null,

  -- Mismo formato que `flights.route`: los ICAO separados por espacio.
  route           text,
  notes           text,

  status          text not null default 'programado'
                    check (status in ('programado', 'completado', 'descartado')),

  -- Con qué vuelo se cerró este plan. Es la trazabilidad, y además hace imposible
  -- convertir el mismo plan dos veces. `set null` si el vuelo se borra: el plan
  -- queda `completado` y huérfano, que es lo correcto —el piloto borró el vuelo a
  -- propósito— y no reabre una pregunta que ya contestó.
  flight_id       uuid references public.flights(id) on delete set null,

  -- Lo que hace que el botón "Después" signifique algo. Sin esto, posponer sólo
  -- esconde la tarjeta hasta el próximo render y vuelve a aparecer al navegar.
  postponed_until date,

  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

-- El barrido de la tarjeta del dashboard pregunta siempre por usuario + fecha.
create index planned_flights_user_date_idx on public.planned_flights (user_id, date);

-- **Un vuelo no puede cerrar dos planes.** Sin esto, dos planes del mismo día
-- apuntando al mismo vuelo hacen que el calendario muestre dos vuelos donde hay
-- uno, y que el piloto crea que cargó de más. Índice parcial porque `flight_id` es
-- null en todos los planes abiertos, y los nulls no colisionan entre sí.
create unique index planned_flights_flight_id_idx
  on public.planned_flights (flight_id) where flight_id is not null;


-- ---------------------------------------------------------------------------
-- RLS — las cuatro políticas explícitas
-- ---------------------------------------------------------------------------
-- Y no la variante de una sola `for all` que usa `custom_stats`. La migración 006
-- es la razón: `profiles` tenía select y update pero **no insert**, y el camino de
-- auto-reparación del backend falló en silencio para 5 de 15 usuarios. Cuatro
-- políticas escritas hacen visible cuál falta; una sola `for all` esconde el hueco.

alter table public.planned_flights enable row level security;

create policy "planned_flights_select_propios" on public.planned_flights
  for select using (auth.uid() = user_id);
create policy "planned_flights_insert_propios" on public.planned_flights
  for insert with check (auth.uid() = user_id);
create policy "planned_flights_update_propios" on public.planned_flights
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "planned_flights_delete_propios" on public.planned_flights
  for delete using (auth.uid() = user_id);


-- ---------------------------------------------------------------------------
-- updated_at
-- ---------------------------------------------------------------------------
-- Una fila de esta tabla cambia de estado —programado, completado, descartado,
-- pospuesto— y saber *cuándo* cambió es lo que se necesita para diagnosticar por
-- qué a un piloto le apareció o no le apareció la tarjeta. Es la misma pregunta
-- que costó el arreglo del marcado de alertas.

create or replace function public.planned_flights_touch()
returns trigger
language plpgsql
set search_path to ''
as $function$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$function$;

create trigger planned_flights_touch_trigger
  before update on public.planned_flights
  for each row execute function public.planned_flights_touch();


-- ---------------------------------------------------------------------------
-- Verificación.
-- ---------------------------------------------------------------------------
-- select column_name, data_type, is_nullable from information_schema.columns
--   where table_schema='public' and table_name='planned_flights' order by ordinal_position;
--
-- select polname from pg_policy
--   where polrelid = 'public.planned_flights'::regclass order by polname;
--   -- esperado: las cuatro (select/insert/update/delete)
--
-- select relrowsecurity from pg_class where oid = 'public.planned_flights'::regclass;
--   -- esperado: true
--
-- Y la invariante que sostiene todo el plan, después de programar un vuelo:
-- select count(*) from public.flights;
--   -- esperado: el mismo número que antes. Un plan NO es un vuelo.
