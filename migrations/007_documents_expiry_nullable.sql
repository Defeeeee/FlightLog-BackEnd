-- 007 — Un documento puede no vencer.
--
-- `documents.expiry_date` era `NOT NULL`, que asume que todo documento caduca.
-- No es cierto: una licencia puede ser de por vida, y forzar una fecha obliga al
-- piloto a inventar una. Un dato inventado en una cadena regulatoria es lo mismo
-- que arreglamos en el onboarding sacándole el default al CMA.
--
-- **Sin fecha significa "no vence", no "no sabemos".** Es la diferencia con
-- `documento_faltante` de `pilot-status.ts`, que es el caso de un documento que
-- debería estar y no está. Acá el documento está y sabemos que no caduca:
--
--   - nunca cuenta como vencido, así que nunca bloquea el semáforo
--   - nunca dispara un aviso de vencimiento
--   - se muestra en gris, no en verde: no es salud, es ausencia de cuenta regresiva
--
-- Esta migración es segura de aplicar **antes** de desplegar el código, al revés
-- que un DROP COLUMN: sólo relaja una restricción. Ninguna fila existente cambia,
-- y el código viejo no puede escribir un null porque exigía la fecha. El código
-- nuevo tolera el null en los dos sentidos.
--
-- El barrido de vencimientos ya lo contemplaba sin saberlo:
-- `document_alerts.py` abre con `if not raw_expiry: return None`.

alter table public.documents
  alter column expiry_date drop not null;

comment on column public.documents.expiry_date is
  'Fecha de vencimiento, o NULL si el documento no vence (una licencia de por vida). NULL nunca cuenta como vencido ni dispara avisos.';


-- ---------------------------------------------------------------------------
-- Verificación.
-- ---------------------------------------------------------------------------
-- select is_nullable from information_schema.columns
--   where table_schema='public' and table_name='documents' and column_name='expiry_date';
--   -- esperado: YES
--
-- select count(*) from public.documents where expiry_date is null;
--   -- esperado: 0 — nada existente cambia de significado
