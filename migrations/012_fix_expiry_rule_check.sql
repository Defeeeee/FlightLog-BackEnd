-- 012 — El CHECK de la 011 no rechazaba nada.
--
-- La restricción que salió en la migración 011 era:
--
--     check (
--       (expiry_rule = 'fijo' and expiry_offset_days is null)
--       or (expiry_rule = 'ultimo_vuelo' and expiry_offset_days between 1 and 3650)
--     )
--
-- y con `expiry_rule = 'ultimo_vuelo'` y `expiry_offset_days` en NULL evalúa así:
--
--     rama 1: false and true                → false
--     rama 2: true and (NULL >= 1) and ...  → true and NULL → NULL
--     false or NULL                         → NULL
--
-- **Un CHECK que da NULL pasa.** Es del estándar SQL y no un capricho de Postgres:
-- la restricción sólo rechaza con FALSE explícito, porque NULL es "no sé" y no "no".
-- Así que la fila incoherente que la 011 decía impedir entraba sin chistar. Lo
-- confirmó la propia sección de verificación de la 011, intentando el update que
-- tenía que fallar: no falló.
--
-- Vale la pena tenerlo escrito porque es la trampa clásica de las restricciones con
-- columnas anulables, y esta tabla ya tiene dos (`expiry_date`, `expiry_offset_days`).
--
-- La reescritura usa un CASE, que **nunca devuelve NULL**: cada rama termina en un
-- booleano armado con `IS NULL` / `IS NOT NULL`, que no propagan lo desconocido. El
-- `else false` de yapa cierra la puerta a cualquier valor de `expiry_rule` que no
-- sea uno de los dos.
--
-- No hay datos que reparar: la 011 se aplicó hace minutos y las 7 filas existentes
-- están todas en 'fijo' con el offset en NULL, que es coherente bajo las dos
-- versiones de la restricción. Igual el `alter` valida la tabla entera al agregarla,
-- así que si hubiera alguna incoherente esto fallaría en vez de pasarla por alto.

alter table public.documents
  drop constraint if exists documents_expiry_rule_check;

alter table public.documents
  add constraint documents_expiry_rule_check check (
    case expiry_rule
      when 'fijo' then expiry_offset_days is null
      when 'ultimo_vuelo' then
        expiry_offset_days is not null and expiry_offset_days between 1 and 3650
      else false
    end
  );


-- ---------------------------------------------------------------------------
-- Verificación.
-- ---------------------------------------------------------------------------
-- select pg_get_constraintdef(oid) from pg_constraint
--   where conrelid = 'public.documents'::regclass
--     and conname = 'documents_expiry_rule_check';
--   -- esperado: un CASE, no un OR
--
-- Y la prueba que importa, la que la 011 no pasaba. El `raise exception` final
-- revierte el bloque entero, así que el update de prueba no queda escrito ni
-- aunque el CHECK lo dejara pasar:
--
--   do $$
--   declare
--     resultado text := 'NO rechazo — el CHECK sigue sin cumplir su funcion';
--     doc_id uuid;
--   begin
--     select id into doc_id from public.documents limit 1;
--     begin
--       update public.documents set expiry_rule = 'ultimo_vuelo' where id = doc_id;
--     exception when check_violation then
--       resultado := 'rechazo correctamente';
--     end;
--     raise exception 'RESULTADO: %', resultado;
--   end
--   $$;
--   -- esperado: "RESULTADO: rechazo correctamente"
