-- 013 — Anclar el vencimiento a un vuelo puntual, y contar en meses.
--
-- La 011 trajo una sola regla derivada, `'ultimo_vuelo'`: la fecha se corre con cada
-- vuelo nuevo. Sirve para "60 días sin volar y necesitás adaptación". No sirve para
-- la otra mitad, que es "24 meses **desde aquel** vuelo" — el repaso de 61.135, la
-- habilitación que sacaste tal día, el curso que hiciste en tal salida.
--
-- Esta migración agrega la tercera regla, `'vuelo_ancla'`, y la unidad.
--
-- ---------------------------------------------------------------------------
-- Una regla anclada no es un vencimiento variable, y eso está bien.
-- ---------------------------------------------------------------------------
--
-- Vale decirlo porque suena a contradicción: si el ancla es un vuelo fijo, la fecha
-- no se mueve, así que esto es casi lo mismo que escribir la fecha a mano. **Casi.**
-- Las dos diferencias que lo justifican:
--
-- 1. Si corregís la fecha de ese vuelo —te equivocaste al cargarlo—, el vencimiento
--    se corrige solo. Escrito a mano quedaría apuntando al día viejo, en silencio.
-- 2. Queda registrado **de dónde salió la fecha**. Un `expiry_date` suelto es un
--    número sin origen; con el ancla, la pantalla puede decir "24 meses desde tu
--    vuelo del 2026-03-15".
--
-- ---------------------------------------------------------------------------
-- Referencia blanda al vuelo: a propósito, sin foreign key.
-- ---------------------------------------------------------------------------
--
-- `expiry_anchor_flight_id` no tiene FK contra `flights`, y no es un olvido. Las
-- tres opciones y por qué ninguna FK sirve:
--
--   - `on delete restrict` (lo que da una FK sin cláusula): **borrar un vuelo pasaría
--     a fallar** porque un documento lo señala. Inaceptable — el libro de vuelo es lo
--     principal y un documento no puede tomarlo de rehén.
--   - `on delete set null`: el ancla desaparece sin dejar rastro y el vencimiento se
--     evapora. Un documento que bloqueaba el vuelo deja de bloquear **en silencio**,
--     que es exactamente la clase de cosa que este proyecto ya pagó caro.
--   - `on delete cascade`: borraría el documento. Absurdo.
--
-- Lo que hace Vector en cambio, en `derived_expiries.recompute_for_user`: si el
-- vuelo ancla ya no existe, **congela** el documento — se queda con la última fecha
-- calculada y pasa a `'fijo'`. La intención del piloto ("esto vence el tal día")
-- sobrevive al borrado del vuelo, y después puede re-apuntarlo si quiere. Es la
-- única de las cuatro que no pierde información ni sorprende.
--
-- ---------------------------------------------------------------------------
-- Meses y no sólo días.
-- ---------------------------------------------------------------------------
--
-- El repaso de 61.135 son **24 meses calendario**, no 730 días. La diferencia son
-- uno o dos días según los bisiestos y los meses de 31, y en un vencimiento
-- regulatorio uno o dos días es la diferencia entre poder volar y no.
--
-- La suma de meses satura el día al último del mes destino: 31 de enero + 1 mes es
-- el 28 (o 29) de febrero, que es la convención de todo el mundo y la que usa
-- `dateutil.relativedelta`. La aritmética está en `derived_expiries.sumar_offset`,
-- escrita a mano porque `dateutil` no está en los requirements.
--
-- Los topes son distintos por unidad —3650 días, 120 meses— porque son el mismo
-- orden de magnitud (10 años) expresado en cada una. Son guardarraíles contra un
-- dedo de más, no reglas de la RAAC.

alter table public.documents
  add column if not exists expiry_anchor_flight_id uuid,
  add column if not exists expiry_offset_unit text not null default 'dias';

-- El índice sirve al recálculo: cuando se borra o se edita un vuelo hay que
-- encontrar los documentos que lo señalan. Parcial porque la enorme mayoría de las
-- filas tiene el ancla en NULL y no tiene sentido indexarlas.
create index if not exists documents_anchor_flight_idx
  on public.documents (expiry_anchor_flight_id)
  where expiry_anchor_flight_id is not null;

-- La restricción, reescrita para las tres reglas.
--
-- `case` y no `or`, por lo que enseñó la migración 012: con `or`, una rama que da
-- NULL hace que el CHECK entero dé NULL, **y un CHECK que da NULL pasa**. Cada rama
-- de acá termina en un booleano armado con `is null` / `is not null`, que no
-- propagan lo desconocido, y el `else false` cierra la puerta a cualquier valor de
-- `expiry_rule` que no sea uno de los tres.
alter table public.documents
  drop constraint if exists documents_expiry_rule_check;

alter table public.documents
  add constraint documents_expiry_rule_check check (
    expiry_offset_unit in ('dias', 'meses')
    and case expiry_rule
      when 'fijo' then
        expiry_offset_days is null and expiry_anchor_flight_id is null
      when 'ultimo_vuelo' then
        expiry_anchor_flight_id is null
        and expiry_offset_days is not null
        and expiry_offset_days between 1 and (case expiry_offset_unit when 'meses' then 120 else 3650 end)
      when 'vuelo_ancla' then
        expiry_anchor_flight_id is not null
        and expiry_offset_days is not null
        and expiry_offset_days between 1 and (case expiry_offset_unit when 'meses' then 120 else 3650 end)
      else false
    end
  );

comment on column public.documents.expiry_anchor_flight_id is
  'Vuelo desde el que se cuenta, para expiry_rule = "vuelo_ancla". Referencia blanda a proposito: sin FK, para que borrar un vuelo nunca falle. Si el vuelo desaparece, recompute_for_user congela el documento en "fijo" con la ultima fecha calculada.';

comment on column public.documents.expiry_offset_unit is
  'Unidad de expiry_offset_days: "dias" o "meses". Los meses saturan al ultimo dia del mes destino (31 de enero + 1 mes = 28 de febrero).';

comment on column public.documents.expiry_rule is
  'Quien escribe expiry_date. "fijo": el piloto, a mano. "ultimo_vuelo": el backend, contando desde el vuelo mas reciente y recalculando con cada cambio. "vuelo_ancla": el backend, contando desde el vuelo que señala expiry_anchor_flight_id. Ver src/services/derived_expiries.py.';


-- ---------------------------------------------------------------------------
-- Verificación.
-- ---------------------------------------------------------------------------
-- select column_name, data_type, is_nullable, column_default
--   from information_schema.columns
--   where table_schema='public' and table_name='documents'
--     and column_name in ('expiry_anchor_flight_id','expiry_offset_unit');
--   -- esperado: dos filas; expiry_offset_unit NOT NULL default 'dias'
--
-- select expiry_rule, expiry_offset_unit, count(*) from public.documents group by 1,2;
--   -- esperado: todo en ('fijo','dias') — ninguna fila existente cambia de significado
--
-- Y la prueba que la 011 no pasaba, ahora sobre las tres reglas. El `raise` final
-- revierte el bloque entero, así que ningún update de prueba queda escrito:
--
--   do $$
--   declare r text := ''; doc_id uuid;
--   begin
--     select id into doc_id from public.documents limit 1;
--     begin
--       update public.documents set expiry_rule='vuelo_ancla', expiry_offset_days=24,
--         expiry_offset_unit='meses' where id=doc_id;
--       r := r || 'MAL: acepto vuelo_ancla sin ancla; ';
--     exception when check_violation then r := r || 'bien: rechazo sin ancla; ';
--     end;
--     begin
--       update public.documents set expiry_rule='ultimo_vuelo', expiry_offset_days=200,
--         expiry_offset_unit='meses' where id=doc_id;
--       r := r || 'MAL: acepto 200 meses; ';
--     exception when check_violation then r := r || 'bien: rechazo 200 meses; ';
--     end;
--     raise exception 'RESULTADOS: %', r;
--   end $$;
