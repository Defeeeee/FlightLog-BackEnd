-- 011 — Vencimientos que se mueven solos.
--
-- Hasta acá `documents.expiry_date` era siempre una fecha que el piloto escribía a
-- mano. Alcanza para el CMA y para la licencia, que vencen el día que dice el
-- papel, y no alcanza para la mitad de las exigencias con las que vive un piloto de
-- escuela: "si pasás 60 días sin volar, necesitás un vuelo de adaptación", "la
-- autorización del instructor caduca a los 90 días del último vuelo". Ninguna de
-- esas tiene fecha: tiene una **regla**, y la fecha se corre cada vez que el piloto
-- vuela.
--
-- Escrito a mano, un vencimiento así está mal desde el día siguiente.
--
-- ---------------------------------------------------------------------------
-- El modelo: la regla es nueva, `expiry_date` no cambia de significado.
-- ---------------------------------------------------------------------------
--
-- `expiry_date` sigue siendo **la** fecha de vencimiento para todo el resto del
-- sistema: el semáforo de `pilot-status.ts`, `documentStatus`, el barrido de avisos
-- de `document_alerts.py`, el orden de `GET /documents`. Nada de eso se entera de
-- que existen reglas.
--
-- Lo que cambia es **quién la escribe**. Con `expiry_rule = 'fijo'` (el default, y
-- lo que son hoy todas las filas) la escribe el piloto. Con `'ultimo_vuelo'` la
-- escribe el backend: `src/services/derived_expiries.py` la recalcula cada vez que
-- los vuelos de ese piloto cambian —alta, edición o baja—, que es exactamente
-- cuando el ancla se mueve.
--
-- **Se guarda calculada en vez de derivarse en cada lectura**, y no es por
-- comodidad: el barrido de vencimientos corre de noche sobre `documents` de todos
-- los pilotos y filtra por `expiry_date`. Derivarla al leer obligaría a ese barrido
-- —y a la ruta de chat, y al webhook— a traerse los vuelos de cada piloto para
-- resolver una fecha. Una columna cacheada con un solo escritor bien definido es
-- más barata y deja el resto del sistema intacto.
--
-- El precio es que la caché puede quedar vieja si el recálculo falla. Falla del
-- lado seguro: `recompute_for_user` nunca voltea la escritura que la disparó (misma
-- política que `_refresh_audit`), así que el peor caso es una fecha de ayer, no un
-- vuelo perdido.
--
-- ---------------------------------------------------------------------------
-- Sin vuelos no hay ancla.
-- ---------------------------------------------------------------------------
--
-- Un piloto sin ningún vuelo cargado y un documento con regla `ultimo_vuelo` deja
-- `expiry_date` en NULL, que desde la migración 007 significa "no vence": nunca
-- vencido, nunca un aviso. Es lo correcto y no un caso degradado — "vence 60 días
-- después de tu último vuelo" cuando no hubo ningún vuelo es una cuenta que todavía
-- no empezó a correr. En cuanto cargue el primero, la fecha aparece sola.
--
-- ---------------------------------------------------------------------------
-- Segura de aplicar antes de desplegar el código.
-- ---------------------------------------------------------------------------
--
-- Sólo agrega dos columnas con default. Toda fila existente queda en `'fijo'`, que
-- es literalmente lo que hoy son. El código viejo ignora las columnas nuevas y
-- sigue escribiendo `expiry_date` a mano, que para `'fijo'` es el comportamiento
-- correcto.

alter table public.documents
  add column if not exists expiry_rule text not null default 'fijo',
  add column if not exists expiry_offset_days integer;

-- Dos restricciones en una: la regla es de un conjunto cerrado, y los dos campos
-- son coherentes entre sí. Sin la segunda mitad se pueden guardar filas que no
-- significan nada —una regla `ultimo_vuelo` sin offset no tiene cómo calcularse, y
-- un offset sobre una regla `fijo` es un número que nadie va a leer nunca.
--
-- El tope de 3650 días (10 años) no es regulatorio: es un guardarraíl contra un
-- dedo de más en el formulario. Un vencimiento a 300 años no es un vencimiento.
do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'documents_expiry_rule_check'
  ) then
    alter table public.documents
      add constraint documents_expiry_rule_check check (
        (expiry_rule = 'fijo' and expiry_offset_days is null)
        or (expiry_rule = 'ultimo_vuelo' and expiry_offset_days between 1 and 3650)
      );
  end if;
end
$$;

comment on column public.documents.expiry_rule is
  'Quién escribe expiry_date. "fijo": el piloto, a mano. "ultimo_vuelo": el backend, recalculando desde la fecha del último vuelo cada vez que los vuelos cambian (src/services/derived_expiries.py).';

comment on column public.documents.expiry_offset_days is
  'Días después del ancla, para expiry_rule = "ultimo_vuelo". NULL cuando la regla es fija.';


-- ---------------------------------------------------------------------------
-- Verificación.
-- ---------------------------------------------------------------------------
-- select column_name, data_type, is_nullable, column_default
--   from information_schema.columns
--   where table_schema='public' and table_name='documents'
--     and column_name in ('expiry_rule','expiry_offset_days');
--   -- esperado: dos filas; expiry_rule NOT NULL default 'fijo'
--
-- select expiry_rule, count(*) from public.documents group by 1;
--   -- esperado: todo en 'fijo' — ninguna fila existente cambia de significado
--
-- Y que la restricción efectivamente rechace lo incoherente:
--   update public.documents set expiry_rule = 'ultimo_vuelo' where id = '...';
--   -- esperado: error, falta el offset
