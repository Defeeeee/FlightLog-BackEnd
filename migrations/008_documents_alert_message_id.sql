-- 008 — Aceptado no es entregado.
--
-- El barrido marcaba un documento como avisado en cuanto Kapso devolvía 2xx. Eso
-- no es una entrega: es un acuse de recibo de la API. Meta resuelve la entrega
-- *después*, asincrónicamente, y avisa por webhook (`sent`/`delivered`/`read`/
-- `failed`). Entre las dos cosas caben un número dado de baja, un piloto que
-- bloqueó la cuenta, o una plantilla pausada.
--
-- Cuando eso pasa hoy, el documento queda marcado con el umbral de 30 y
-- `should_alert` no vuelve a disparar hasta que cruce el de 7. **El aviso de los
-- 30 días se quema sin que nadie lo haya leído**, y el piloto se entera —si se
-- entera— un mes más tarde. Es exactamente el modo de falla que el comentario de
-- `DocumentAlertsController` dice estar evitando al separar el marcado del envío:
-- la separación es correcta, pero el frontend llama a `/sent` con la aceptación,
-- no con la entrega.
--
-- Guardar el id del mensaje es lo que permite cerrar el círculo: el `failed` que
-- manda Meta trae ese id y nada más, así que sin la columna no hay forma de saber
-- **qué documento** se quedó sin avisar. Con ella, el webhook limpia la marca y el
-- barrido del día siguiente reintenta solo.
--
-- Marcar en la aceptación se mantiene a propósito. La alternativa —esperar el
-- `delivered` para marcar— deja la ventana entre el envío y el webhook con el
-- documento sin marcar, y si el barrido corriera dos veces ahí en el medio el
-- piloto recibe el aviso duplicado. Marcar y desmarcar ante el fallo falla del
-- lado correcto: el peor caso es un reintento, no un silencio.
--
-- Segura de aplicar **antes** de desplegar el código: sólo agrega una columna
-- nullable. El código viejo la ignora, y `/sent` sin `message_id` la deja en NULL,
-- que es exactamente lo que significa "no sabemos qué mensaje fue" — un documento
-- así simplemente no se puede desmarcar, que es el comportamiento de hoy.

alter table public.documents
  add column if not exists last_alert_message_id text;

comment on column public.documents.last_alert_message_id is
  'wamid del último aviso enviado, para poder desmarcarlo si Meta reporta que falló. NULL significa que no sabemos qué mensaje fue: ese aviso no se puede reintentar automáticamente.';


-- ---------------------------------------------------------------------------
-- El trigger de reset tiene que limpiar la columna nueva también.
-- ---------------------------------------------------------------------------
-- Si no, renovar un documento re-arma la escalera 60/30/7 pero deja colgado el id
-- del aviso del vencimiento *anterior*. Un `failed` tardío de ese mensaje viejo
-- entraría a limpiar una marca que ya no le corresponde, y el piloto recibiría un
-- aviso de un vencimiento que ya renovó.
--
-- Se reescribe entera y no con un ALTER porque plpgsql no tiene forma de parchear
-- un cuerpo. Es la misma función de `003`, más una línea.

create or replace function public.documents_reset_alerts()
returns trigger
language plpgsql
set search_path to ''
as $function$
BEGIN
    NEW.updated_at := now();
    IF NEW.expiry_date IS DISTINCT FROM OLD.expiry_date THEN
        NEW.last_alert_threshold := NULL;
        NEW.last_alert_at := NULL;
        NEW.last_alert_message_id := NULL;
    END IF;
    RETURN NEW;
END;
$function$;


-- ---------------------------------------------------------------------------
-- Verificación.
-- ---------------------------------------------------------------------------
-- select column_name, is_nullable from information_schema.columns
--   where table_schema='public' and table_name='documents'
--     and column_name='last_alert_message_id';
--   -- esperado: una fila, YES
--
-- select pg_get_functiondef('public.documents_reset_alerts'::regproc);
--   -- esperado: incluye last_alert_message_id := NULL
--
-- Y el camino completo, sobre un documento de prueba:
--   update public.documents set expiry_date = expiry_date + 1 where id = '...';
--   select last_alert_threshold, last_alert_at, last_alert_message_id
--     from public.documents where id = '...';
--   -- esperado: las tres en NULL
