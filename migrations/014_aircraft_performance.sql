-- 014 — Performance de la aeronave: TAS de crucero, consumo y capacidad.
--
-- El planificador de navegación necesita tres números que Vector no guarda en ningún
-- lado. `aircraft` hoy es {registration, icao, type, type_acft, cost_per_hour}: sabe
-- cuánto sale la hora y no sabe a qué velocidad vuela.
--
-- ---------------------------------------------------------------------------
-- Por aeronave y no por plan de vuelo
-- ---------------------------------------------------------------------------
--
-- Los calculadores operativos venían usando constantes hardcodeadas —TAS 110, consumo
-- 32 L/h— que son las del Harmony y no las de ningún otro avión. Poner los campos en
-- el plan en vez de en la aeronave obligaría a tipearlos antes de cada vuelo, que es
-- exactamente la fricción que el planificador viene a sacar: se cargan una vez, al dar
-- de alta el avión, y sirven para siempre.
--
-- ---------------------------------------------------------------------------
-- Nullables, y sin default
-- ---------------------------------------------------------------------------
--
-- Un default de 110 kt sería mentir con cara de dato: el piloto vería su avión con una
-- velocidad que nadie cargó y no tendría forma de distinguirla de una real. **Null es
-- "no lo sé", y la pantalla tiene que decirlo** — la misma disciplina que `unavailable`
-- en el dashboard y que `datos_no_disponibles` en el semáforo.
--
-- Con null, el planificador cae a las constantes de siempre y avisa que está estimando.
--
-- ---------------------------------------------------------------------------
-- Litros, no galones
-- ---------------------------------------------------------------------------
--
-- El surtidor en Argentina despacha en litros y el POH de un LSA europeo viene en
-- litros. Guardar en galones obligaría a convertir en los dos extremos. `aviation.ts`
-- ya sabe convertir para mostrar si algún día hace falta.
--
-- ---------------------------------------------------------------------------
-- Los CHECK, y por qué no son `> 0` a secas
-- ---------------------------------------------------------------------------
--
-- Un CHECK que evalúa a NULL **pasa** —sólo FALSE rechaza—, así que `cruise_tas_kt > 0`
-- deja entrar los nulls solo, que es justo lo que queremos. Es la misma lógica de tres
-- valores que en la migración 011 hizo que una restricción no rechazara nada; acá juega
-- a favor, pero conviene tenerlo escrito para el próximo que lea.
--
-- Los techos son deliberadamente amplios: no están para validar el avión sino para
-- atajar el dedo gordo (500 en vez de 50). Vector es para aviación general; una TAS de
-- 400 kt es un error de tipeo, no un Learjet.

ALTER TABLE public.aircraft
  ADD COLUMN IF NOT EXISTS cruise_tas_kt   numeric,
  ADD COLUMN IF NOT EXISTS fuel_burn_lph   numeric,
  ADD COLUMN IF NOT EXISTS fuel_capacity_l numeric;

ALTER TABLE public.aircraft
  DROP CONSTRAINT IF EXISTS aircraft_cruise_tas_kt_check,
  DROP CONSTRAINT IF EXISTS aircraft_fuel_burn_lph_check,
  DROP CONSTRAINT IF EXISTS aircraft_fuel_capacity_l_check;

ALTER TABLE public.aircraft
  ADD CONSTRAINT aircraft_cruise_tas_kt_check   CHECK (cruise_tas_kt   > 0 AND cruise_tas_kt   <= 400),
  ADD CONSTRAINT aircraft_fuel_burn_lph_check   CHECK (fuel_burn_lph   > 0 AND fuel_burn_lph   <= 500),
  ADD CONSTRAINT aircraft_fuel_capacity_l_check CHECK (fuel_capacity_l > 0 AND fuel_capacity_l <= 2000);

COMMENT ON COLUMN public.aircraft.cruise_tas_kt IS
  'TAS de crucero en nudos. Null = no cargada; el planificador estima y lo dice.';
COMMENT ON COLUMN public.aircraft.fuel_burn_lph IS
  'Consumo en litros por hora a crucero. Null = no cargado.';
COMMENT ON COLUMN public.aircraft.fuel_capacity_l IS
  'Capacidad utilizable en litros. Utilizable, no total: el no utilizable no vuela.';
