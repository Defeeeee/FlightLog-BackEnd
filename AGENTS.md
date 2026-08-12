# AGENTS.md — Bitácora de agentes de FlightLog-BackEnd

Este archivo es la **bitácora obligatoria** de todo agente de IA que modifique
este repositorio. Igual que un piloto no cierra un vuelo sin cargarlo en el
libro, ningún agente cierra una tanda de cambios sin dejar su entrada acá.

## Orientación rápida

- **Este repo es el backend** (Python + Litestar + Supabase).
  El frontend vive en `/Users/defeee/Vector/Vector-FrontEnd` (Next.js 16 App Router).
- **Los controladores** están en `src/controllers/` y los modelos en `src/models/`.
- **Las migraciones de SQL** viven en `migrations/`.
- **Tests**: Ejecutar `python test_audit_engine.py` para probar las reglas de auditoría.
- **Políticas de entorno**: Los archivos `.env` deben estar siempre en `.gitignore` y NUNCA commitearse.

---

## Proceso obligatorio

**Es obligatorio para cada agente.** Sin excepciones, sin "lo anoto después".

1. **Antes de empezar**, leé las entradas existentes al final de este archivo.
   Te dicen qué se tocó recién, por qué, y qué quedó pendiente o a medias.
2. **A medida que hacés cambios**, escribí la entrada. No al final de todo:
   si la sesión se corta, el trabajo sin registrar queda huérfano.
3. **Una entrada por tanda coherente de cambios** (una fase, una feature, un
   fix). No una por archivo, no una por sesión entera de ocho horas.
4. **Las entradas se agregan al final**, en orden cronológico. Nunca se
   reescribe ni se borra una entrada anterior — si algo salió mal o se
   revirtió, se escribe una entrada nueva que lo diga.
5. **El timestamp va en UTC**, obtenido de verdad (`date -u`), no estimado.
6. **La justificación no es opcional.** "Pedido del usuario" no alcanza:
   explicá *por qué esa solución* y qué alternativa descartaste. El próximo
   agente necesita el razonamiento, no el changelog — el changelog ya está en
   `git log`.
7. **Si algo quedó a medias, roto o bloqueado, se dice.** Una entrada que
   miente sobre el estado del repo es peor que no tener entrada.

---

## Template

Copiá este bloque tal cual y completalo:

```markdown
### YYYY-MM-DD HH:MM UTC — <Agente / modelo> — <Título corto de la tanda>

**Quién:** <nombre del agente, modelo y en nombre de quién trabaja>

**Qué cambié:**
- `ruta/al/archivo.py` — qué se hizo ahí, en una línea.
- `ruta/al/otro.sql` — ídem.

**Por qué:** El razonamiento. Qué problema resuelve, qué alternativas se
evaluaron y por qué se descartaron, qué restricción del proyecto lo condiciona.

**Estado:** Terminado / Parcial / Bloqueado — y si no está terminado, qué falta
exactamente y qué es lo próximo.

**Verificación:** Cómo se comprobó que funciona (tests, curl, etc.). Si no se verificó, decirlo explícitamente.
```

---

## Bitácora

### 2026-08-04 12:17 UTC — Antigravity (Gemini 3.6 Flash) — Creación de AGENTS.md y registro de feature múltiples libros

**Quién:** Antigravity (Gemini 3.6 Flash), para Federico Díaz Nemeth.

**Qué cambié:**
- `AGENTS.md` (nuevo) — creación del archivo de bitácora del backend con las mismas políticas y estructura que el repositorio frontend.
- Registrado de los cambios de `feat(logbooks)`:
  - `migrations/001_logbooks.sql` — migración para tabla `logbooks`, FK en `flights.logbook_id` y backfill de libro por defecto.
  - `src/models/logbook.py` y `src/controllers/logbooks.py` — modelo Pydantic y endpoints de gestión de libros.
  - `src/controllers/flights.py` y `src/models/flight.py` — soporte y fallback `_default_logbook_id` para asignación automática al crear vuelos.

**Por qué:** Se alinea el backend con la política obligatoria de documentación y trazabilidad de agentes definida en `AGENTS.md`. Se documenta la implementación de la feature de múltiples libros de vuelo aprobada en el plan post-flightdeck.

**Estado:** Terminado. PR creada en https://github.com/Defeeeee/FlightLog-BackEnd/pull/4

**Verificación:** `python test_audit_engine.py` pasa correctamente. `git status` limpio. Rama `feat/logbooks` pusheada a origin.

### 2026-08-10 21:45 UTC — Claude (Opus 5, vía Claude Code) — Cada login envenenaba el proceso entero

**Quién:** Claude Opus 5 corriendo en Claude Code, para Federico Díaz Nemeth.

**Qué cambié:**
- `src/supabase_client.py` — `get_base_client()` deja de cachear el cliente y devuelve uno nuevo por llamada. Se agrega `verify_access_token()`, que valida un JWT con un GET a GoTrue sin cliente de por medio.
- `src/auth/guards.py` — el guard verifica con esa función en vez de `auth.get_user()` sobre el cliente compartido.
- `requirements.txt` — `supabase` pineado en `2.28.3`.

**Por qué:** `/health` devolvía `PGRST303 "JWT expired"` y **un `pm2 restart` lo
arreglaba**. Ese detalle descarta la explicación que se venía usando desde el
2026-08-04: si la clave del `.env` estuviera vencida, reiniciar no cambiaría nada.

Ninguna clave del proyecto puede vencer — `service_role` y `anon` legacy van hasta
2036-03-31, y la publicable es del tipo nuevo sin `exp`. El JWT vencido sólo podía
ser el access token de un usuario.

Un cliente de `supabase-py` **no es un objeto sin estado**. En la 2.28.3:

```python
def _listen_to_auth_events(self, event, session):
    if event in ["SIGNED_IN", "TOKEN_REFRESHED", "SIGNED_OUT"]:
        self._postgrest = None
        access_token = session.access_token if session else self.supabase_key
    self.options.headers["Authorization"] = auth_header
```

`POST /auth/login` no lleva bearer token, así que `provide_supabase_client`
(`security.py:31`) le entregaba **el singleton anónimo** —el mismo que sirve
`/health`— y `AuthController.login` le hacía `sign_in_with_password` encima. Cada
login dejaba al proceso firmando con el token de esa persona; una hora después,
toda consulta anónima fallaba hasta el próximo restart. Con un solo piloto usando
la app, el síntoma parecía aleatorio.

Esto cierra la asimetría del 2026-08-04: el dashboard andaba porque vivía del
`TOKEN_CACHE` de 10 s y Reanalizar fallaba porque caía fuera y tocaba el cliente
contaminado. Se atribuyó a la clave y se rotó; **lo que lo arregló fue el reinicio
que traía el deploy.**

> **Un restart que "arregla" algo es información, no una solución.** Si reiniciar
> lo cura, el problema está en memoria y va a volver. Es lo que separó seis días
> de diagnóstico equivocado de la causa real.

**Dos cosas que no hay que revertir:**

- **No volver a cachear `get_base_client()`.** Mientras cualquier consumidor pueda
  iniciar sesión sobre el cliente que recibe, compartirlo es compartir esa sesión.
  El `create_client` por request sólo se paga en rutas sin sesión.
- **No despinear `supabase`.** Estaba en `>=2.0.0`, con 60 versiones posibles y
  comportamiento de auth distinto entre ellas. El análisis de arriba vale para
  2.28.3.

Descartado con evidencia, para que no se vuelva a levantar: compartir una única
instancia de `ClientOptions` **es seguro** en 2.28.3, porque el cliente hace
`copy.copy(options)` y se arma su propio dict de headers.

**Estado:** Terminado y desplegado. Falta la comprobación de que el bug murió, que
requiere esperar (ver abajo).

**Verificación:** Contra el SDK que reemplaza — mismo endpoint `/auth/v1/user`,
mismas cabeceras, y `parse_user_response` parsea el body como usuario, o sea que
`id` va en la raíz. En vivo contra el GoTrue del proyecto: token basura, vacío y
JWT mal firmado devuelven `None`, que el guard traduce al mismo 401 de antes.

El camino de éxito no se pudo ejercitar desde el contenedor por falta de sesión; lo
cubre el smoke autenticado del frontend, que entra con cuenta real y pega a diez
rutas del dashboard, todas por este guard.

> **La prueba que de verdad cierra el caso:** loguearse, **esperar más de una hora
> sin reiniciar**, y pegarle a `/health`. Antes de este cambio eso devolvía 500. Es
> la única que distingue "arreglado" de "recién reiniciado", y es exactamente la
> que faltó el 2026-08-04.

### 2026-08-12 15:50 UTC — Claude (Opus 5, vía Claude Code) — El cliente de service role consultaba como usuario, y el barrido no se quejaba

**Quién:** Claude Opus 5 corriendo en Claude Code, para Federico Díaz Nemeth.

**Qué cambié:**
- `src/supabase_client.py` — `_options` pasa de atributo de clase compartido a **método que devuelve una instancia nueva**. El cliente de service role va con `persist_session=False`. El fallback a la clave anónima ahora avisa por log.
- `src/controllers/documents.py` — el barrido acepta el secreto por `X-Cron-Secret` además del query string (paso 1 de 3 de `H1.1` aplicado acá). `PendingAlert` expone `first_name` para la plantilla de WhatsApp.
- `src/controllers/whatsapp.py` — el log del teléfono sin match dice largo y prefijo, no sólo el sufijo.

**Por qué:** el barrido de vencimientos devolvía `[]` **con 200 y sin ningún error**. Los logs de Supabase mostraron esto:

```
GET /rest/v1/documents?select=*
apikey        = service_role
authorization = authenticated      <- el token de un piloto
content_range = 0-2/*              <- 3 filas de 6
```

**PostgREST prioriza `Authorization` sobre `apikey`.** El cliente de service role consultaba como usuario común, RLS le tapaba las filas ajenas, y el documento vencido de otro piloto era invisible.

La causa: `ClientOptions` crea su `storage` con `default_factory` —uno nuevo por instancia— pero `supabase-py` hace `copy.copy(options)`, copia **superficial**, y sólo rehace el dict de `headers`. **El `storage` queda siendo el mismo objeto** (`_sync/client.py:72-74`, 2.28.3). Con un único `ClientOptions` de clase, todos los clientes del proceso comparten el depósito de sesiones: `login` guarda la del piloto y cualquier cliente posterior la recupera, dispara `SIGNED_IN`, y se pisa el `Authorization`.

Probado con el paquete real, no deducido:

```
compartidas: a.storage is b.storage -> True   y la sesión se lee cruzada
nuevas:      c.storage is d.storage -> False  y no se lee
```

> **Era la segunda mitad del bug del 2026-08-10.** Descachear `get_base_client()`
> arregló `/health` porque ahí lo compartido era el **cliente**. Acá lo compartido
> son las **options**, y por eso crear un cliente nuevo por llamada no alcanzaba:
> todos nacían apuntando al mismo storage. **Cuando aparezca contaminación de
> sesión, revisar los dos niveles.**

**Lo más importante para el próximo, que no es el bug:**

> **El barrido nunca falló.** Devolvía 200 y una lista vacía, indistinguible de
> "no hay nada por avisar". Si el cron hubiera estado puesto, habría corrido en
> verde todos los días avisándole a un solo piloto, y no había forma de notarlo
> desde afuera. Un proceso que corre sobre **todos** los usuarios y de golpe ve los
> de uno **tiene que gritar**. Por eso el fallback a la clave anónima ahora
> loguea — pero el problema general sigue abierto: nadie se entera de que un
> barrido silencioso dejó de ver gente.

**Cómo se diagnosticó, que es reusable:** los `edge_logs` de Supabase tienen
`request.sb.jwt.apikey.payload.role` y `request.sb.jwt.authorization.payload.role`
por separado, más `response.headers.content_range` con el conteo de filas. Ver esos
tres juntos fue lo que lo resolvió; leer el código no alcanzaba, porque el código
está bien.

⚠️ **Al consultar logs, fijar la ventana con la fecha correcta.** Se perdió una
vuelta mirando los logs del día anterior y sacando conclusiones de ahí.

**Estado:** Terminado y desplegado. `T1.1` cerrada: el cron quedó instalado el
2026-08-12 (`0 12 * * *`, 09:00 ART).

**Verificación:** antes y después en la misma consulta de Supabase —
`authorization=authenticated` con `0-2/*` pasó a `authorization=service_role` con
`0-5/*`— y el barrido devuelve `{"pending":1,"sent":0,"skipped":1,"failed":0}`. El
`skipped` es un piloto sin WhatsApp, que queda **sin marcar** a propósito.
