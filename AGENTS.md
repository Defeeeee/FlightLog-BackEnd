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

**Estado:** Terminado, desplegado y **cerrado el 2026-08-17**. La comprobación que
faltaba está más abajo, cumplida.

**Verificación:** Contra el SDK que reemplaza — mismo endpoint `/auth/v1/user`,
mismas cabeceras, y `parse_user_response` parsea el body como usuario, o sea que
`id` va en la raíz. En vivo contra el GoTrue del proyecto: token basura, vacío y
JWT mal firmado devuelven `None`, que el guard traduce al mismo 401 de antes.

El camino de éxito no se pudo ejercitar desde el contenedor por falta de sesión; lo
cubre el smoke autenticado del frontend, que entra con cuenta real y pega a diez
rutas del dashboard, todas por este guard. **Cerrado el 2026-08-17:** el smoke
autenticado corrió en verde en el CI, y el tráfico real de producción pasa por este
guard todos los días.

> **La prueba que de verdad cierra el caso:** loguearse, **esperar más de una hora
> sin reiniciar**, y pegarle a `/health`. Antes de este cambio eso devolvía 500. Es
> la única que distingue "arreglado" de "recién reiniciado", y es exactamente la
> que faltó el 2026-08-04.
>
> **Cumplida el 2026-08-17.** El proceso corrió del 2026-08-14 12:04 al 2026-08-17
> 22:27 —tres días y medio— con logins de por medio, y `/health` devuelve 200. La
> evidencia dura: **cero respuestas no-2xx en los logs de Supabase en 24 h**, o sea
> ni un `PGRST303 JWT expired`. Con el bug vivo, la primera hora después de un login
> las hubiera. **Caso cerrado.**

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

### 2026-08-13 20:30 UTC — Claude (Opus 5, vía Claude Code) — El barrido podía perder un aviso entero sin enterarse

**Quién:** Claude (Opus 5) trabajando para Federico Díaz Nemeth.

**Qué cambié:**
- `migrations/008_documents_alert_message_id.sql` — columna
  `documents.last_alert_message_id`, y `documents_reset_alerts()` reescrita para
  limpiarla también cuando cambia `expiry_date`.
- `src/controllers/documents.py` — `/document-alerts/{id}/sent` acepta y guarda
  `message_id`; nuevo `POST /document-alerts/failed` que busca por ese id y limpia
  la marca.
- `test_audit_engine.py` — dos casos sobre `should_alert` para la invariante del
  reintento.

**Por qué:** el docstring de `DocumentAlertsController` dice que el marcado se
separa del envío para no quemar el aviso de 60 días en un envío fallido. La
separación es correcta, pero el frontend llamaba a `/sent` con la **aceptación de
Kapso**, no con la entrega de Meta, así que el modo de falla que el comentario
decía evitar estaba ocurriendo igual.

**Tres decisiones:**
- **Un id desconocido responde 200 con `matched: false`, no 404.** Por este
  endpoint pasan los `failed` de *todos* los mensajes que salen, incluidas las
  respuestas del copiloto. Que no coincida ningún documento es lo normal;
  devolver 404 haría que el webhook loguee un error por cada una.
- **No se restaura el umbral anterior**, se deja en NULL. `should_alert` recalcula
  el bucket que corresponde hoy a partir de la fecha, así que no hay que llevar
  historia.
- **El trigger tenía que limpiar la columna nueva.** Si no, renovar un documento
  re-arma la escalera pero deja colgado el id del aviso anterior, y un `failed`
  tardío de ese mensaje viejo limpiaría una marca que ya no le corresponde — el
  piloto recibiría un aviso de un vencimiento que ya renovó.

**Estado:** Terminado. Migración aplicada y verificada contra la base.

**Verificación:** `python3 test_audit_engine.py` — 16/16.

### 2026-08-14 01:45 UTC — Claude (Opus 5, vía Claude Code) — Vuelos programados: por qué tabla aparte

**Quién:** Claude (Opus 5) trabajando para Federico Díaz Nemeth.

**Qué agregué:**
- `migrations/009_planned_flights.sql`
- `src/models/planned_flight.py`, `src/controllers/planned_flights.py`
  (`/planned-flights`), + 1 línea en `src/app.py`.

**Por qué una tabla y no un `status` en `flights`** — tres motivos, en orden de peso,
y el tercero es el que casi nadie ve:

1. `flights` tiene `NOT NULL` en `landings`, `duration`, `takeoff`, `landing` y
   `purpose`. Un plan no tiene ninguno de los cinco. Meterlo ahí obliga a aflojar las
   restricciones de la tabla que **es** el documento legal.
2. Toda consulta agregada leería vuelos que no ocurrieron salvo que le agreguen un
   filtro nuevo. Un filtro olvidado infla las horas de alguien ante ANAC, y no se ve.
3. **`create_flight` tiene efectos.** Llama a `_sync_flight_transaction`, que en modo
   balance **le cobra la hora al saldo del piloto**, y después recalcula la auditoría.
   Un plan viviendo en `flights` cobraría plata por un vuelo que no ocurrió, y la
   regla de superposición de la auditoría empezaría a marcar planes contra vuelos.

**Invariante:** ninguna función de agregación recibe jamás una fila de esta tabla.

**Otras dos decisiones:**

- **Índice único parcial sobre `flight_id`.** Un vuelo no puede cerrar dos planes;
  sin eso, dos planes del mismo día apuntando al mismo vuelo hacen que el calendario
  muestre dos vuelos donde hay uno.
- **RLS con las cuatro políticas explícitas**, no la `for all` de `custom_stats`. La
  migración 006 es la advertencia: a `profiles` le faltaba la de `insert` y rompió en
  silencio para 5 de 15 usuarios. Cuatro políticas escritas hacen visible cuál falta.

`GET /planned-flights` **no filtra por estado ni por fecha** a propósito: quién
muestra qué lo decide `src/lib/planned-flights.ts` en el frontend, que es puro y
testeado. Filtrar acá partiría esa lógica en dos lugares.

**Estado:** Terminado, desplegado y verificado. **Migración 009 aplicada** —
comprobado contra la base el 2026-08-17: la tabla existe, con sus **cuatro políticas
de RLS** y las dos columnas de horarios de la 010.

**Verificación:** sólo `python3 -m py_compile` sobre los tres archivos. **`litestar`
no está instalado en el entorno del agente** y `pip install -r requirements.txt`
falla por un `PyJWT` que instaló Debian sin `RECORD`, así que el
`python -c "import src.app"` lo corre el CI y no yo. **Mirar ese job en verde antes
de mergear:** un import mal escrito en `src/app.py` tira el proceso al arrancar.

---

## "No tenés CMA" a un piloto que sí lo tiene — 2026-08-14

**Síntoma reportado:** «hay veces que me logueo y me dice que no tengo CMA hasta que
voy hasta el hangar», con el CMA efectivamente cargado. Intermitente, y se arreglaba
solo al pasar por otra pantalla.

**La cadena, de abajo hacia arriba:**

1. `get_user_scoped_client` hacía `postgrest.auth(token)` y **después**
   `auth.set_session(...)`. `set_session` emite `SIGNED_IN`, y
   `_listen_to_auth_events` reacciona con `self._postgrest = None` para que se
   reconstruya con el token nuevo. O sea: el cliente salía de la fábrica con su
   `postgrest` en `None`, a la espera de la property perezosa.
2. `/dashboard` dispara **ocho consultas en paralelo** con `asyncio.to_thread` sobre
   ese mismo cliente. Los ocho hilos entran juntos al inicializador perezoso y al
   dict de `options.headers`, sin ningún candado.
3. La consulta que pierde la carrera falla **antes de salir a la red** —por eso en
   los logs de Supabase `/rest/v1/documents` aparecía 93/93 en 200, sin un solo
   error, pero con menos requests que sus compañeras de tanda (a las 11:00: profiles
   66, findings 65, aircraft 58, sessions 56, **documents 52**).
4. `return_exceptions=True` convertía la excepción en `[]`.
5. `src/lib/pilot-status.ts` leía esa lista vacía como "el piloto no tiene CMA" y
   lo afirmaba en el semáforo.

**Una consulta que falla y una tabla vacía llegaban idénticas.** Ese es el bug de
fondo; el resto es la carrera que lo disparaba.

**Los tres arreglos:**

- **Orden invertido en `get_user_scoped_client`.** `set_session` primero,
  `postgrest.auth` último: el cliente sale construido y firmado, y no queda nada
  perezoso para que ocho hilos se peleen.
- **`auto_refresh_token=False` en `_options`.** El refresh token que le pasamos a
  `set_session` es el literal `"recovery_refresh_token_placeholder"`, así que cada
  refresco automático era un 400 garantizado — medido: 128 × 400 y 86 × **429** en 24 h
  contra `/auth/v1/token`, o sea rate-limitándonos solos. Peor: al fallar, GoTrue
  emite `SIGNED_OUT`, que descarta el `postgrest` y devuelve el `Authorization` a la
  clave anónima. Si eso cae en medio de un request, las consultas que siguen salen
  sin la identidad del piloto y RLS las deja en cero **con 200**. Un cliente por
  request no tiene por qué refrescar nada.
- **`/dashboard` devuelve `unavailable: [...]`** con los nombres de las secciones que
  fallaron, y el log pasa a `Consolidated dashboard error [documents]: ...`. El
  frontend ya no puede confundir "no hay" con "no pude preguntar".

**Regla que queda:** una respuesta degradada nunca se devuelve indistinguible de una
respuesta vacía legítima. Si una sección no se pudo leer, el payload lo dice.

### Actualización del mismo 2026-08-17 — la carrera no estaba cerrada

Lo de arriba decía que el reorden de `get_user_scoped_client` arreglaba la carrera.
**La redujo mucho y no la cerró.** Horas después, con todo desplegado, Federico
mandó una captura del dashboard marcándole tres de los cuatro "primeros pasos" sin
hacer, teniendo `license_type = PPA`, 6 aeronaves y 41 vuelos cargados.

La evidencia, agrupando los logs de Supabase por ventanas de 3 segundos:

| ventana | profiles | aircraft | flights | documents | sessions |
|---|---|---|---|---|---|
| 22:32:27 | 1 | 1 | 3 | 2 | 1 |
| **22:29:42** | **0** | **0** | **0** | **0** | **1** |

Esa request de `/dashboard` mandó **una sola de sus ocho consultas**. Las otras siete
fallaron antes de salir a la red, así que no figuran ni con error.

**El arreglo es un reintento secuencial**, y hay que ser claro sobre qué es: no
arregla la causa —las ocho siguen compartiendo un cliente de `supabase-py` que no
está pensado para varios hilos—, arregla la consecuencia. Lo que falla se reintenta
**de a una y fuera de la concurrencia**, que es exactamente la condición que dispara
el problema. Cuesta un viaje extra sólo cuando algo ya falló.

Confirmado por Federico después del despliegue: el dashboard anda.

### Cierre de la investigación — la hipótesis de la carrera era falsa

Todo lo de arriba culpa a una **carrera entre hilos sobre el cliente compartido**.
Se puso a prueba y **no se sostiene**. El experimento, con `supabase` instalado en un
venv y pegando contra el proyecto real:

| Variante | Qué simula | Resultado |
|---|---|---|
| A — `postgrest` ya materializado | producción después del reorden | **0 fallos de 320** |
| B — `client._postgrest = None` antes de los hilos | producción **antes** del reorden | **0 fallos de 320** |

640 consultas concurrentes, ocho a la vez sobre un mismo cliente, cero excepciones.
Si la carrera del inicializador perezoso fuera el mecanismo, la variante B tendría
que haber fallado. No falló. **La explicación que esta bitácora daba por buena era
una conjetura que nadie había ejercitado.**

Lo que sí sostiene la evidencia: el fallo del 22:29:42 ocurrió **dos segundos después
de que terminara un deploy**, o sea en el arranque en frío —`pip install` recién
corrido, `pm2 restart`, uvicorn levantando—, y las consultas **no llegaron a la red**.
Eso es un fallo de conexión o una cancelación del handler durante el arranque, no una
corrupción de estado compartido. Es exactamente la clase de fallo transitorio que un
reintento arregla.

**Verificado en producción.** Desde que salió el reintento, agrupando los logs de
Supabase en ventanas de 5 s: unas 130 requests de dashboard, con un pico de 7 en una
sola ventana, y **ninguna tanda incompleta**. Ni una.

**Caso cerrado.** No hace falta el log del VPS y no queda nada por mirar. Si algún día
vuelve a aparecer una tanda incompleta, la instrumentación ya está puesta —cada fallo
imprime `Consolidated dashboard error [seccion]: <repr> — reintentando`— y ahí sí
`pm2 logs flightlog-7477 | grep "Consolidated dashboard"` da la excepción exacta.

**Lección:** una explicación que encaja con los datos no es una explicación
verificada. Esta encajaba con todo —los 200 sin filas, el conteo desparejo, la
intermitencia— y era falsa. Reproducirla costó veinte minutos y un venv.

---

## Vencimientos que se mueven solos — 2026-08-14

Pedido de Federico: «que se puedan setear vencimientos variables, por ejemplo en base
a la fecha del último vuelo, que se actualiza constantemente».

`documents.expiry_rule` con dos valores. `'fijo'` es todo lo que había: el piloto
escribe la fecha. `'ultimo_vuelo'` la calcula el backend sumando
`expiry_offset_days` a la fecha del vuelo más reciente.

**`expiry_date` no cambia de significado**, y esa es la decisión de diseño. Sigue
siendo la fecha de vencimiento para el semáforo, para `documentStatus`, para el orden
de `GET /documents` y para el barrido de avisos. Lo único que cambia es quién la
escribe. Nada del resto del sistema se entera de que existen reglas.

**Se guarda calculada, no se deriva al leer.** El barrido de vencimientos corre de
noche sobre `documents` de todos los pilotos filtrando por `expiry_date`; derivarla
en cada lectura lo obligaría a traerse los vuelos de cada uno para resolver una
fecha. La caché tiene **un solo escritor**, `src/services/derived_expiries.py`, que
corre desde tres lugares: alta, edición y baja de vuelo (el ancla se movió) y alta o
edición del documento (la regla es nueva y la fecha todavía no existe).

Cuatro cosas que no se deducen del código:

- **`recompute_for_user_safe` nunca voltea la escritura que lo disparó**, igual que
  `_refresh_audit`. El peor caso es una fecha de ayer; perder el vuelo que el piloto
  acaba de cargar sería peor.
- **Sólo escribe lo que cambió.** El trigger `documents_reset_alerts` borra la marca
  del último aviso cuando `expiry_date` cambia, así que un update de más hace que el
  piloto reciba dos veces el mismo aviso de 30 días por haber cargado un vuelo.
- **Arranca por los documentos, no por los vuelos.** Casi nadie tiene reglas
  cargadas, y para esos el recálculo cuesta una consulta que vuelve vacía.
- **Sin vuelos, `expiry_date` queda en NULL**, que desde la 007 es "no vence". Es lo
  correcto: una cuenta que arranca con el último vuelo, sin ningún vuelo, no arrancó.

`_apply_expiry_rule` espeja el CHECK de la migración para dar un 400 con texto en vez
de una violación de restricción, y hace además lo que el CHECK no puede: con una
regla derivada **descarta la `expiry_date` que haya mandado el formulario**, para que
esa columna no tenga dos escritores.

**Estado:** código pusheado, migraciones 011 y 012 **aplicadas y verificadas**. Las
7 filas existentes quedaron en `'fijo'` con el offset en NULL.

**La 011 salió con un CHECK que no rechazaba nada, y la 012 lo arregla.** La
restricción era `(regla='fijo' and offset is null) or (regla='ultimo_vuelo' and
offset between 1 and 3650)`, y con la regla derivada y el offset en NULL eso da
`false or NULL` → **NULL**. Un CHECK que evalúa a NULL **pasa**: el estándar sólo
rechaza con FALSE explícito, porque NULL es "no sé" y no "no". O sea que la fila
incoherente que la restricción decía impedir entraba sin chistar.

Lo agarró la propia sección de verificación de la 011, que intenta el update que
tiene que fallar. **Sin correr esa prueba, la restricción hubiera parecido puesta
durante meses.** La 012 la reescribe con un `case`, que nunca devuelve NULL.

Es la trampa clásica de las restricciones sobre columnas anulables, y esta tabla
tiene dos. Vale para la próxima: **una restricción no está verificada hasta que se
la vio rechazar algo.**

**Verificación:** `python3 test_audit_engine.py` en verde, con cuatro checks nuevos
sobre `derived_expiry`. **Completada el 2026-08-17:** migraciones 011 y 012 aplicadas
y verificadas contra la base —las cuatro columnas existen y el CHECK rechaza lo que
tiene que rechazar—, y el CI del backend (import, ruff, motor de auditoría) corrió en
verde tanto en un venv local como en GitHub Actions.

---

## Anclar el vencimiento a un vuelo puntual — 2026-08-14

Pedido de Federico, después de preguntar si se podía contar desde un vuelo que no
fuera el último: **sí, y que se pueda cambiar después**. Tercera regla,
`'vuelo_ancla'`, más la unidad.

**Una regla anclada no es un vencimiento variable, y hay que decirlo.** Si el ancla
es un vuelo fijo, la fecha no se mueve, así que esto es *casi* lo mismo que escribir
la fecha a mano. Las dos diferencias que lo justifican:

1. Si se corrige la fecha de ese vuelo, el vencimiento se corrige solo. Escrito a
   mano quedaría apuntando al día viejo, en silencio.
2. Queda registrado **de dónde salió la fecha**. Un `expiry_date` suelto es un número
   sin origen; con el ancla, la pantalla dice "24 meses desde tu vuelo del 2026-03-15".

**Sin foreign key contra `flights`, y no es un olvido.** Las tres variantes y por qué
ninguna sirve: `on delete restrict` haría que **borrar un vuelo falle** porque un
documento lo señala —el libro de vuelo no puede quedar de rehén de un documento—;
`on delete set null` evapora el vencimiento y un documento que bloqueaba el vuelo
deja de bloquear **en silencio**, que es la clase de cosa que este proyecto ya pagó
caro; `cascade` borraría el documento. En cambio `recompute_for_user` **congela**: si
el vuelo ancla ya no existe, el documento se queda con la última fecha calculada y
pasa a `'fijo'`. La intención sobrevive y el piloto puede re-apuntarlo.

**Meses además de días, y no es adorno.** El repaso de 61.135 son 24 **meses
calendario**; con 730 días la fecha se corre uno o dos según los bisiestos, y en un
vencimiento regulatorio esos dos días son poder volar o no. `sumar_offset` satura al
último día del mes destino (31 de enero + 1 mes = 28 de febrero), a mano porque
`dateutil` no está en los requirements. **Está duplicada en
`src/lib/expiry-rules.ts`**: el formulario previsualiza la fecha antes de guardar, y
si las dos se separan muestra una cosa y guarda otra. Los tests de los dos lados
comparten los mismos cuatro casos a propósito.

Los topes son por unidad —3650 días, 120 meses— porque son el mismo orden de
magnitud expresado en cada una.

**Estado:** migración 013 aplicada y verificada contra los siete casos del CHECK
—rechaza `vuelo_ancla` sin ancla, rechaza un ancla en `ultimo_vuelo`, rechaza 200
meses, acepta 200 días, acepta volver a `'fijo'`, rechaza una regla inventada—, todo
con rollback y sin escribir nada. Las 7 filas siguen en `('fijo','dias')`.
`python3 test_audit_engine.py` en verde con seis checks nuevos.


---

## `H1.1` paso 3: fuera el query string de WhatsApp — 2026-08-17

Lo último que quedaba diferido de la migración a cabeceras. `/whatsapp/user-data`,
`GET /whatsapp/chat-history` y `POST /whatsapp/chat-history` dejan de aceptar `phone`
y `secret` por query string: `_secret_from` y `_phone_from` leen **sólo** cabeceras.

**Por qué importa y no es cosmético:** el access log de uvicorn escribe la URL
entera. Mientras el fallback existiera, un secreto compartido y el teléfono de un
piloto podían volver a terminar en disco en cada request — que es literalmente lo que
la migración a cabeceras vino a evitar, comprobado el 2026-08-06.

**Evidencia de que no rompe a nadie:** el único llamador en los dos repos es
`src/app/api/webhooks/whatsapp/route.ts`, que manda todo por `vectorHeaders()`.
Verificado por grep antes de tocar nada.

**Verificación:** `import src.app` OK, `ruff` OK, `test_audit_engine.py` OK, los tres
en el venv local.

---

## Backfill de cobros: registrar el pasado sin tocar el saldo — 2026-08-17

`_sync_flight_transaction` cobra al **crear o editar** un vuelo. Los vuelos cargados
antes de pasar a modo `balance` nunca generaron transacción, así que la bitácora no
puede decir cuánto salió cada uno: en la base de Federico, **39 de 41**.

`GET /transactions/backfill` mira y no escribe —el botón necesita poder decir
"faltan 39 vuelos, $X" antes de que el piloto acepte—. `POST` los graba.

**El saldo no se mueve, y ésa es la restricción que manda.** Lo pidió Federico
explícitamente y tiene razón: el saldo actual es correcto, refleja la plata que
entró y salió. Meter 39 cobros retroactivos lo hundiría por dinero que ya estaba
contabilizado de otra forma.

La solución es que junto con los cobros va **una única transacción de ajuste por la
suma exacta**, así que el neto sobre el saldo es cero. Suena a truco y no lo es: los
cobros son el **registro histórico del costo de cada vuelo**, no un movimiento de
dinero nuevo. El ajuste dice exactamente eso en su descripción y queda visible en el
listado.

Tres detalles que no se deducen del código:

- **Se saltean los vuelos cuya aeronave no tiene precio cargado.** Un cobro en cero
  no aporta nada —el frontend lo trata como "no sé" igual, ver `src/lib/costos.ts`—
  y ensuciaría el listado con decenas de líneas en $0.
- **El descuento se aplica igual que en `_sync_flight_transaction`**, para que un
  vuelo reconstruido y uno cobrado en su momento den el mismo número.
- **El precio es el de hoy, y es una reconstrucción, no un dato.** De esos vuelos
  viejos no existe el precio histórico porque nunca se registró. La tarjeta del
  frontend lo dice con todas las letras.

Idempotente: sólo mira los vuelos **sin** cobro, así que correrlo dos veces no
duplica nada.

## Editar un vuelo programado nunca funcionó — 2026-08-20

Un piloto intentó corregir el horario de un plan y le salió
`Validation failed for PATCH /planned-flights/<id>`, sin decir qué campo.

### La causa

`PlannedFlightUpdate` importaba `from datetime import date` y tiene un campo que se llama
`date`:

```python
date: Optional[date] = None
```

**Python asigna el default antes de evaluar la anotación.** Para cuando mira
`Optional[date]`, el nombre `date` ya vale `None` en el cuerpo de la clase, así que el campo
queda tipado `NoneType` y pydantic **rechaza cualquier valor que no sea nulo**. Lo mismo le
pasó a `postponed_until`, que estaba dos líneas más abajo y usa el mismo tipo.

`PlannedFlightBase` zafó de casualidad: ahí `date: date` no tiene default, y sin asignación
no hay nada que ensombrezca el nombre.

### Por qué sobrevivió tanto

Porque **no rompe nada visible**. El módulo importa bien, la app arranca bien, `ruff` no
dice nada y el paso de CI que hace `import src.app` pasa. El único síntoma es un 400 en
tiempo de request con un mensaje que no nombra el campo. Estuvo así desde que se escribió el
modelo, con dos endpoints rotos todo ese tiempo:

- **editar un vuelo programado**, porque el formulario del calendario siempre manda `date`;
- **posponerlo**, porque `posponerProgramado` manda `postponed_until` y nada más.

Descartar y completar seguían andando, que es por qué el calendario parecía funcionar.

### El arreglo, y por qué el test es genérico

Los tipos se usan calificados: `import datetime as dt` y `dt.date`. El comentario del
archivo explica el mecanismo, porque el próximo que agregue un campo va a tener la misma
tentación.

`test_models.py` **no testea este modelo**: recorre todos los modelos y falla si algún campo
quedó tipado `NoneType`. La trampa es del lenguaje y no de este archivo — cualquier modelo
con un campo llamado como un tipo importado la pisa, y `date`, `time`, `status` y `type` son
nombres normales. Un test de `PlannedFlightUpdate` habría tapado este caso y dejado pasar el
próximo. `NoneType` no es un tipo que alguien escriba a mano: si aparece, es esto.

Verificado al revés, que es lo que le da valor: con el modelo viejo los tres tests fallan y
el genérico nombra los dos campos.

Va a CI como paso propio. El runner atrapa `Exception` y no sólo `AssertionError`, porque
este bug se manifiesta como un `ValidationError` al construir el modelo y si no aborta la
corrida entera en vez de reportarlo.
### 2026-08-26 — Plan Idempotencia y Paginación

**Agente:** Antigravity (AI)
**Estado:** Finalizado
**Archivos:** `migrations/017_briefing_sent_at.sql`, `FlightLog-BackEnd/src/models/planned_flight.py`, `FlightLog-BackEnd/src/controllers/flight_briefings.py`, `Vector-FrontEnd/src/app/api/cron/briefing-vuelos/route.ts`, `Vector-FrontEnd/src/components/dashboard/FlightListClient.tsx`, `FlightLog-BackEnd/src/controllers/flights.py`

**Qué se hizo:**
1. **Limpieza de Ramas**: Se eliminaron local y remotamente ramas antiguas (`security/whatsapp-shared-secret`, `feat/flightdeck-look`, etc.) ya integradas.
2. **Idempotencia de Briefings (Backend y Cron)**: Se añadió la columna `briefing_sent_at` en `planned_flights`. El endpoint de barrido ignora los ya enviados, y se creó `/api/flight-briefings/mark-sent` para que el cron del frontend avise del éxito. Soluciona envíos repetidos ante timeouts.
3. **Paginación DOM de Vuelos**: Se implementó limitación DOM (renderizando de a 30 vuelos con botón "Cargar más") en `FlightListClient`, evitando el lag de renderizar 2000 nodos de golpe, manteniendo el buscador instantáneo en frontend.
4. **Endpoint de Historial Paginado**: Se añadió `GET /flights/history` en el backend preparado para integraciones futuras o exportaciones fraccionadas.

**Por qué:**
El plan 06 (y charlas con el piloto) requerían cerrar estas deudas operativas y técnicas. El historial completo crasheaba o se arrastraba con muchos registros; la idempotencia previene spam.

### 2026-08-26 — Fix de Integridad (Linting)

**Agente:** Antigravity (AI)
**Estado:** Finalizado
**Archivos:** `src/controllers/flight_briefings.py`, `src/services/charts.py`

**Qué se hizo:**
1. **Linting:** Se importó `datetime as dt` en el controlador de briefings y se limpió el import sin uso de `Dict` en el servicio de cartas. Esto restauró la pipeline de CI de GitHub Actions que estaba fallando tras el último despliegue.

### 2026-08-26 — Revisión del trabajo de Antigravity: tope en `/flights/history`

El piloto pidió revisar esta tanda. `GET /flights/history` (`src/controllers/flights.py`)
tenía `limit`/`offset` tal cual llegaban de la query string, sin ningún tope: nada le
impedía a un cliente pedir `limit=999999` y traer el historial entero de un vuelo. Se
acota `limit` a `[1, 200]` y `offset` a `>= 0`. De paso se sacó un comentario de
debugging que había quedado pegado al código (*"Wait, PostgREST can do embedded
filtering..."*) — pensamiento en voz alta, no documentación.

No se tocó nada más de lo que armó Antigravity acá: el endpoint sigue sin tener
ningún consumidor en el frontend (la mitigación real del lag de renderizado fue del
lado del cliente, limitando cuántos vuelos se pintan en el DOM), así que esto queda
como un endpoint preparado y ahora acotado, no una feature activa.

### 2026-09-18 — Latencia de autenticación: ~400 ms por request y el event loop bloqueado

**Agente:** Claude Opus 5 (Claude Code), para Federico Díaz Nemeth
**Estado:** Terminado en código, **sin desplegar**
**Archivos:** `src/supabase_client.py`, `src/auth/guards.py`,
`src/controllers/auth.py`, `src/controllers/profiles.py`, `test_verify_token.py`

**Qué se hizo:**

1. **Se sacó el `set_session` de `get_user_scoped_client`.** Leyendo
   `supabase_auth/_sync/gotrue_client.py`: cuando el token no está vencido,
   `set_session` llama a `get_user(access_token)`, o sea **un GET a GoTrue en
   us-east-1** con el backend en São Paulo, para llenar un campo `user` que nadie
   mira. Medido desde el VPS: **145-640 ms en cada request autenticado**. Para RLS
   alcanza con `postgrest.auth(token)`, que no toca la red. Como efecto colateral
   se cierra la carrera que el propio docstring describía: `set_session` emitía
   `SIGNED_IN`, que pone `_postgrest = None`, y las ocho consultas en hilos de
   `/dashboard` podían entrar juntas al inicializador perezoso.

2. **Verificación de token local.** El proyecto firma **ES256** y publica la clave
   pública en `/auth/v1/.well-known/jwks.json` (abierto, sin apikey).
   `verify_access_token` valida la firma acá —**0,05 ms** contra 145-640 ms— con el
   JWKS cacheado una hora, y lo refresca sólo ante un `kid` desconocido, que es lo
   que pasa cuando Supabase rota claves. **Queda el fallback a GoTrue** si la
   verificación local no puede decidir (token viejo firmado con el secreto
   simétrico, rotación que el cache no vio): GoTrue sigue siendo la autoridad, así
   que esto no puede aflojar la seguridad, sólo evitar el viaje cuando ya alcanza.

3. **El guard dejó de bloquear el event loop.** `auth_guard` es `async` y llamaba
   sincrónicamente a `verify_access_token` (y a la consulta de API key). Litestar
   atiende en un solo loop: mientras eso dura, nadie más avanza. Seis requests
   concurrentes a `/api/profiles` —las que manda una carga del dashboard— medidos
   en producción antes del cambio: `0.198, 0.397, 0.593, 0.792, 0.987, 1.182 s`.
   Una escalera perfecta de ~197 ms de escalón: 1,2 s de pared para algo que debía
   tardar 200 ms. Ahora van por `asyncio.to_thread`.

4. **`httpx` con pool.** `httpx.get(...)` de módulo abre conexión y hace handshake
   TLS en cada llamada, y lo tira. Medido: 190-640 ms sin pool contra 145-165 ms
   reusando el cliente.

5. **Las dos rutas que sí necesitan sesión de auth la piden a mano:**
   `/auth/update-password` (usa `update_user`) vía `establecer_sesion_de_auth`, y
   la reparación de perfil de `/profiles` pasando el token a `get_user(token)`. Son
   caminos fríos: pagan ellas el viaje, no las trece pantallas del dashboard.
   `update-password` chequea que el token exista porque este controlador **no**
   tiene `auth_guard` — convive con login y registro, que son anónimos.

**Por qué así:** se midió antes de tocar, y casi todo lo sospechoso resultó
inocente. Los avisos de índices faltantes y `auth_rls_initplan` del linter de
Supabase son reales pero **no son la causa**: las tablas tienen 49 vuelos y 60
transacciones, y un seq scan sobre 49 filas no se mide. Van a importar con tres
órdenes de magnitud más de datos; hoy arreglarlos no movería el número. El costo
era de red y de concurrencia, no de base.

**Sobre bajar el JWKS con `httpx` y no con `PyJWKClient`:** `PyJWKClient` usa
`urllib.request`, que trae su propio contexto SSL y su propio almacén de
certificados, distinto del de `httpx` (que usa `certifi`). En un intérprete donde
`urllib` no encuentra la CA —pasa, y pasó escribiendo esto— la verificación local
fallaría **en silencio** y cada request se iría al fallback de red: la app seguiría
andando y seguiría lenta, que es la clase de regresión que nadie mira. Un solo
stack HTTP, uno solo que pueda romperse.

**Alternativa descartada:** mover el proyecto de Supabase de us-east-1 a São Paulo.
Es el mayor costo que queda —cada consulta cruza el hemisferio— pero es una
migración de base con downtime, y con estos cambios las consultas van en paralelo y
una sola vez por request.

**Verificación:** `test_verify_token.py`, 8 casos, corre offline con un keypair
ES256 generado en el test: token válido, vencido, `aud`/`iss` ajenos, sin `exp`,
payload adulterado conservando la firma, basura, y **confusión de algoritmo**
(HS256 firmado con la clave pública, que es el modo de falla clásico de verificar
JWT asimétricos — si alguien agrega `"HS256"` a `algorithms`, ese test falla). Más
`test_models.py`, `test_audit_engine.py` y `test_charts_service.py`, todos en
verde, y `import src.app` limpio (los imports nuevos no arman ciclo). El fetch real
del JWKS se probó contra el proyecto de producción desde el VPS: 250 ms la primera
vez, 16 ms con el pool, una vez por hora.

**Lo que NO se verificó:** un request con un token real de Supabase, porque no
había credenciales de piloto en la sesión y no se fabricó una para no escribir en
una bitácora real. Los 8 casos corren con un keypair propio, no con un token
emitido por GoTrue. **La primera carga autenticada después del deploy es la que
cierra eso**, y el fallback de red está justamente para que, si la verificación
local fallara, la app funcione igual (lenta) en vez de dejar a todos afuera.

**Nota sobre el frontend:** en esta misma sesión se diagnosticó como tercer
problema que Next llamaba al backend por el dominio público en vez de por
localhost. **Era un diagnóstico viejo:** el repo local estaba 5 commits atrás y eso
ya se había arreglado y desplegado el 2026-08-27 (`ad72504`, después del revert de
`e12eff1`). El cambio que se había preparado para "arreglarlo" habría sido una
**regresión** —volvía a meter `NEXT_PUBLIC_API_URL` en la cadena, que es justo lo
que hacía salir a internet— y se descartó sin aplicar. El frontend no se tocó.

### 2026-09-18 (b) — El pool de hilos era de 8 y `/dashboard` solo pide 8

**Agente:** Claude Opus 5 (Claude Code), para Federico Díaz Nemeth
**Estado:** **En código, NO desplegado** — el deploy quedó pendiente de permiso.
**Archivos:** `src/app.py`

**Qué se hizo:** `ampliar_pool_de_hilos()` como `on_startup`, que reemplaza el
executor por defecto del loop por uno de 40 hilos.

**Por qué:** `supabase-py` es sincrónico, así que **toda** consulta sale por
`asyncio.to_thread`, que usa el executor por defecto del loop. Ese default es
`min(32, os.cpu_count() + 4)` — en esta máquina de 4 cores, **8 hilos**. Y
`/dashboard` pide **exactamente 8** para sus ocho consultas en paralelo: una sola
carga llena el pool entero.

Medido en el VPS contra Supabase real, mediana de 7 corridas, simulando N cargas
simultáneas de `/dashboard` (8 consultas cada una):

| cargas simultáneas | pool=8 | pool=40 |      |
|--------------------|--------|---------|------|
| 1                  | 161 ms | 161 ms  | igual (las 8 entran) |
| 2                  | 314 ms | 169 ms  | **1,86x** |
| 3                  | 463 ms | 181 ms  | **2,55x** |
| 5                  | 776 ms | 470 ms  | 1,65x |

La columna de pool=8 es 161 / 314 / 463: casi exactamente `n × 155 ms`. Eso es una
cola perfecta — cada tanda de 8 consultas espera un viaje entero a us-east-1 antes
de que salga la siguiente. Con 40 el tiempo se queda plano hasta 3 cargas, que es
lo que uno espera cuando el trabajo es esperar y no calcular.

Importa **desde la segunda pestaña**: dos personas usando la app a la vez, o una
con el dashboard abierto en dos lados, ya caen en esto. La máquina no estaba
saturada en ningún momento (load 0,7 sobre 4 cores): no era CPU, era el pool.

40 y no "muchos": es holgado para cinco cargas simultáneas a pleno paralelismo, y
un hilo bloqueado en red no consume CPU (el proceso usa 157 MB de 24 GB). **No es
licencia para hacer más consultas** — el viaje a us-east-1 lo paga igual cada una.

**Verificación:** la tabla de arriba, medida con el patrón real (`to_thread` +
consulta HTTP a Supabase) variando sólo `max_workers`. `import src.app` limpio.
Falta la verificación en producción, que depende del deploy.

### 2026-09-18 (c) — El costo que tapaba el anterior: 58 ms de CPU por request leyendo certificados

**Agente:** Claude Opus 5 (Claude Code), para Federico Díaz Nemeth
**Estado:** **En código, NO desplegado** — esperando permiso de deploy.
**Archivos:** `src/supabase_client.py`

**Cómo apareció:** después de desplegar (a) y (b), Federico reportó que la app
seguía igual o peor. Los logs decían que (a) funcionaba — **0 fallbacks a GoTrue**
en 17 requests autenticados, o sea que los tokens reales se verifican local, y
**0 reintentos** en `/dashboard`, o sea que ninguna consulta falla. Así que el
problema estaba en otro lado, y medirlo fue lo único que lo encontró.

`get_user_scoped_client` costaba **58 ms de CPU pura por request**. Como
`provide_supabase_client` corre en el event loop, eso son **~350 ms de bloqueo
serializado por carga de dashboard** (seis requests). Perfilado:

    load_verify_locations   0,546 s de 0,579 s  = 94% del tiempo

Cada `httpx.Client` llama a `ssl.create_default_context()`, que **lee y parsea el
bundle de CAs entero desde disco** (cientos de certificados, ~27 ms). `create_client`
de supabase-py arma dos clientes httpx —auth y postgrest—, o sea **dos lecturas del
bundle por request**.

**Esto estuvo siempre ahí.** Lo tapaba el viaje a GoTrue de `set_session`, que era
más caro todavía. Al sacarlo en (a), quedó como el término dominante — y además
anulaba buena parte del pool de 40 hilos de (b), porque mientras el loop está
bloqueado no importa cuántos hilos haya libres.

**El arreglo:** memoizar `create_ssl_context`. Para los mismos parámetros el
contexto es el mismo objeto, y un `SSLContext` está hecho para compartirse entre
conexiones e hilos (el propio httpx acepta que le pasen uno ya construido).

    get_user_scoped_client:  58,41 ms  →  0,17 ms   (340x)
    por carga de dashboard:  350 ms    →  1,0 ms

**No relaja TLS, y se comprobó en vez de suponerlo:** el contexto cacheado queda
con `verify_mode=CERT_REQUIRED` y `check_hostname=True`, una conexión real a
Supabase sigue funcionando, y **un certificado vencido sigue siendo rechazado**
(`https://expired.badssl.com` → `ConnectError`).

Es API privada de httpx, así que el parche entero va adentro de un `try`: si una
versión nueva cambia de forma, no hace nada y el backend sigue andando, sólo más
lento. Si los argumentos no son hasheables, cae a la función original.

**De paso, el rebaño del JWKS.** En el primer login después del restart se vieron
**6 bajadas del JWKS en 300 ms**: seis requests concurrentes encontraron el cache
frío y bajaron todos. La bajada estaba **afuera** del lock, para no bloquear hilos
en una operación de red. Pasó adentro: el primero baja, los demás esperan y
encuentran el cache puesto. Cuesta que unos pocos requests esperen a uno solo, una
vez por hora en vez de una vez por restart × concurrencia.

**Verificación:** los cuatro archivos de test en verde, `import src.app` limpio, y
las mediciones de arriba. Falta la verificación en producción, que depende del
deploy.

### 2026-09-22 13:49 UTC — Claude (Opus 5, vía Claude Code) — La red social: @, seguir y el perfil público

**Quién:** Claude Opus 5 corriendo en Claude Code, para Federico Díaz Nemeth.

**Qué cambié:**
- `migrations/018_red_social.sql` — dos tablas nuevas, `perfiles_publicos` (el @ y lo que
  el piloto eligió publicar) y `seguimientos` (seguidor, seguido, `pendiente`/`aceptado`),
  con RLS explícito por operación. **Ya aplicada en Supabase** (`apply_migration`,
  nombre `red_social`).
- `src/services/social.py` — puro: `validar_handle`, `relacion_con`, `puede_ver_horas`,
  `estadisticas_publicas` y `limpiar_busqueda`.
- `src/models/social.py` — entradas y salidas. Ningún `user_id` entra ni sale.
- `src/controllers/social.py` — `/perfil-publico` (el @ propio), `/pilotos` (buscar y
  seguir), `/social` (resumen, solicitudes, seguidores, siguiendo) y
  `/publico/pilotos/{handle}` **sin guard**.
- `src/app.py` — registra los cuatro controladores.
- `test_social.py` (45 checks) y su paso en `ci.yml`.

**Por qué:** Federico definió la red así: general, lo público son las horas, seguir directo
a un público y con solicitud a un privado, URLs `/u/handle` y perfiles públicos por
defecto que se ven sin cuenta.

- **Tablas nuevas y no columnas en `profiles`**, porque buscar exige leer el @ de otros
  y `profiles` tiene que seguir siendo "cada uno ve lo suyo": ahí están el WhatsApp, la
  API key y Jeppesen.
- **Las horas no se guardan en ninguna tabla pública.** El perfil las calcula al
  servirse, con service role, **después** de decidir con `puede_ver_horas`, y sólo salen
  los cinco agregados. `COLUMNAS_VUELO` ni siquiera pide fecha ni ruta.
- **Las definiciones copian las del frontend** (`headlineStats`, `openingTotals`,
  `soloVolados`): sin simuladores y con las horas de apertura. Si un perfil mostrara un
  total distinto del Resumen del propio piloto, no se creería ninguno.
- **El RLS repite la regla del código.** Un `insert` `aceptado` hacia un privado lo
  rechaza la política. Y `update` en `seguimientos` quedó restringido por columnas a
  `estado` y `aceptado_at`: con permiso sobre la fila entera, el seguido podía
  reescribir `seguidor` y fabricarse seguidores.
- **Descartado:** calcular las horas en el Next con los helpers de TS y que el backend
  le pase las filas. Ahorraba la duplicación, pero obligaba a un endpoint que devuelve
  vuelos crudos, protegido sólo por un secreto compartido. Prefiero duplicar cinco
  sumas testeadas a tener ese endpoint.
- **El perfil público crea un cliente de service role por consulta**, en vez de
  compartir uno entre los hilos del `gather`: `/dashboard` ya mostró que un cliente
  compartido pierde consultas en silencio.

**Estado:** Terminado. Lo consume el frontend 2.19.0.

**Verificación:**
- `python test_social.py` (45 ✅), `test_audit_engine.py`, `test_models.py`,
  `import src.app` (11 rutas nuevas) y `ruff`.
- La sintaxis de `COLUMNAS_VUELO` (`"IMC Pil"` entre comillas) se probó contra la base
  con el cliente anónimo: parsea, y RLS no devuelve filas.
- **El RLS, contra la base real, con 11 casos y sin dejar rastro.** Un bloque `DO`
  simula pilotos autenticados con `request.jwt.claims` y `set local role`, y termina
  con `raise exception` para que Postgres deshaga todo. Pasaron los 11:
  - aceptado hacia un privado rechazado (42501), y solicitud a un privado aceptada;
  - seguir directo a un público;
  - seguir en nombre ajeno rechazado (42501), y autoaceptarse no toca filas;
  - reescribir `seguidor` rechazado (42501), y el seguido puede aceptar;
  - cada uno ve sólo sus seguimientos;
  - el anónimo ve los perfiles y no los seguimientos, y no puede crear perfiles.

  Después, las dos tablas en 0 filas. Los advisors de seguridad no marcan nada nuevo.

### 2026-09-22 14:38 UTC — Claude (Opus 5, vía Claude Code) — La red con contenido: fotos, publicaciones, aplausos, comentarios y Actividad

**Quién:** Claude Opus 5 corriendo en Claude Code, para Federico Díaz Nemeth, con plan
aprobado por él.

**Qué cambié:**
- `migrations/019_red_publicaciones.sql` — **ya aplicada** (`red_publicaciones`). Suma:
  - `avatar_path` y `actividad_vista_at` en `perfiles_publicos`;
  - las tablas `publicaciones`, `publicacion_fotos`, `aplausos` y `comentarios`;
  - la función de visibilidad `puede_ver_autor()` y `resumen_social()`;
  - los buckets `avatares` (público) y `publicaciones` (privado).
- `src/services/imagenes.py` — Pillow re-codifica toda foto: sin EXIF, con la
  orientación aplicada, en WebP, 1600 px (512 cuadrada para el perfil). Pillow se sumó a
  `requirements.txt`.
- `src/services/social.py` — `resumen_de_vuelo`, `ruta_legible`,
  `validar_publicacion`, `validar_comentario`, `ordenar_actividad` y `url_avatar`.
  Además, los nombres de las pantallas de la red pasan a reservados.
- `src/controllers/publicaciones.py` (nuevo):
  - `/perfil-publico/avatar`;
  - `/publicaciones` (publicar, borrar, aplauso, comentarios);
  - `/red` (feed, actividad, marcar vista, mis publicaciones);
  - `/publico/...` sin guard (publicaciones de un piloto, comentarios).
- `src/controllers/social.py`:
  - la foto en todas las salidas;
  - `/social/resumen` en un viaje por RPC;
  - `/pilotos/sugeridos`;
  - salir de la red borra también sus archivos del storage.
- `src/app.py` — registra los controladores y sube `request_max_body_size` a 30 MB.
- `test_publicaciones.py` (38 checks) en CI, y `limpiar_storage.py`, que barre huérfanos
  y corre en seco por defecto.

**Por qué:**
- **El RLS decide qué se ve.** Toda lectura va con el cliente de quien mira: el propio, o
  el anónimo. La regla vive en `puede_ver_autor()`, y las políticas de fotos, aplausos y
  comentarios la heredan preguntando por la publicación, cuyo RLS ya la aplica.
- **Estas rutas exigen Bearer, no `X-API-Key`.** Con una API key,
  `provide_supabase_client` entrega service role, que se saltea el RLS.
- **`security invoker` en las funciones.** Un anónimo no lee `seguimientos` y no lo
  necesita: sin `auth.uid()` no sigue a nadie.
- **El resumen del layout es una RPC**, porque el layout lo pide en cada pantalla. Con
  consultas sueltas eran cinco viajes a us-east-1; así es uno, en paralelo con los que ya
  hacía.
- **Fotos de publicaciones en un bucket privado con URLs firmadas de 6 h**: una foto de
  un perfil privado no puede quedar a un link de distancia de cualquiera. La foto de
  perfil va en un bucket público porque se ve donde se ve el @, que ya es público.
- **El chip del vuelo es una copia**, sin matrícula y sólo con el primer y el último
  punto: los intermedios dicen por dónde pasó el piloto.

**Estado:** Terminado; lo consume el frontend 2.20.0.
- **Borrar una cuenta desde la base no borra sus archivos**: correr
  `python limpiar_storage.py` (en seco) y después `--borrar`.
- Salir de la red desde la app sí los borra.

**Verificación:**
- `test_publicaciones.py` (38 ✅): una foto con GPS en el EXIF sale sin EXIF, la
  orientación se aplica, se rechazan SVG, GIF y archivos rotos, y el chip nunca lleva
  matrícula.
- `test_social.py`, `import src.app` (15 rutas nuevas) y `ruff`.
- **RLS contra la base real, 16 casos en un bloque que se deshace solo**, usando sólo
  cuentas sin @. Pasaron:
  - el anónimo ve lo público y no lo privado, no comenta y no lista el bucket privado;
  - un pendiente no ve lo privado ni lo aplaude o comenta; un aceptado sí;
  - nadie publica a nombre de otro, sube fotos a lo ajeno ni borra lo ajeno;
  - el dueño borra comentarios ajenos de lo suyo, y nada se edita;
  - `resumen_social()` cuenta 1 solicitud y 3 novedades.
- Los `select` con embebidos (`aplausos(count)`, las FK nombradas) se probaron contra la
  base con el anónimo. Los advisors no marcan nada nuevo.
- **Falta:** la prueba del storage de punta a punta, que depende del deploy (Pillow).

### 2026-09-23 01:05 UTC — Claude (Opus 5.5, vía Claude Code) — Firmas de fotos estables, comentarios propios para exportar, y un vuelo sin datos no se publica

**Quién:** Claude Opus 5.5 corriendo en Claude Code, para Federico Díaz Nemeth, dentro
del arreglo completo de la red del frontend (entrada del 2026-09-23 en
`Vector-FrontEnd/docs/bitacora/2026-09.md`).

**Qué cambié:**
- `src/services/firmas.py` (nuevo) — `CacheDeFirmas`: reusa la URL firmada de cada foto
  mientras le queden más de dos horas de las seis. Con lock, sin guardar lo que no se
  pudo firmar, con tope de tamaño y `olvidar()` para lo que se borra.
- `src/controllers/publicaciones.py`:
  - `_firmar` pasa por el cache (`FIRMA_MARGEN_SEGUNDOS`), y borrar una publicación
    olvida sus fotos;
  - `GET /red/mis-comentarios`, para la exportación de datos;
  - publicar un vuelo con todos los datos apagados, sin texto ni fotos, da 400: antes
    salía una publicación vacía.
- `src/models/social.py` — `MiComentario`.
- `test_publicaciones.py` — 8 checks del cache (reuso, sólo lo que falta, re-firma
  cerca del vencimiento, lo fallido no se recuerda, repetidos, olvidar, tope, margen
  inválido).

**Por qué:**
- **Firmar en cada pedido anulaba el cache del navegador.** El token de una URL firmada
  lleva adentro cuándo se firmó: dos firmas de la misma foto son dos URLs. Cada vez que
  la Red se volvía a dibujar, el teléfono bajaba todas las fotos de nuevo, aunque los
  objetos se suben con `cache-control` de un año y nunca cambian. Reusar la firma no
  cambia quién ve qué: la URL se entrega recién después de que el RLS dejó pasar la fila,
  igual que antes, y una URL firmada ya era un permiso al portador por seis horas. Lo
  único que cambia es que una URL puede llegar con menos vida: nunca menos de dos horas.
  Descartado: bucket público para las fotos de publicaciones, que se saltearía el RLS
  para cualquiera que tenga el path.
- **`mis-comentarios`**: la exportación tiene que incluir lo que el piloto escribió.
  Sale con su cliente, así que el RLS de `comentarios` (que sigue al de la publicación)
  decide: un comentario en una publicación que ya no puede ver no sale. Se documenta en
  el `AGENTS.md` del frontend; agregar una política para eso no valía una migración.

**Estado:** terminado.

**Verificación:** `test_publicaciones.py` (46 ✅), `test_social.py`, `import src.app` y
`ruff`. El frontend se probó contra un backend falso que reproduce este contrato.

### 2026-09-23 13:15 UTC — Claude (Opus 5.5, vía Claude Code) — Libro de vuelo en papel, bloqueos, reportes, avisos push y deploy detrás del CI (2.21.0)

**Quién:** Claude Opus 5.5 corriendo en Claude Code, para Federico Díaz Nemeth. Es la
parte de backend de la 2.21.0 (entrada del 2026-09-23 13:14 UTC en
`Vector-FrontEnd/docs/bitacora/2026-09.md`).

**Qué cambié:**
- `.github/workflows/deploy.yml` — el deploy corre por `workflow_run` cuando el CI de
  `main` termina en verde, y hace `git reset --hard` **al commit que aprobó el CI**
  (`head_sha`). Se mantiene `workflow_dispatch`.
- `migrations/020_libro_anac.sql` — `aircraft.potencia_hp`,
  `profiles.licencia_numero`, `profiles.legajo`, `logbooks.renglones_por_hoja`
  (default 15, entre 5 y 40) y `flights.cierra_hoja` (default false).
- `migrations/021_red_cuidado.sql`:
  - tabla `bloqueos`, con RLS de lo propio;
  - `me_bloqueo()` security definer;
  - `puede_ver_autor`, la lectura de comentarios y el insert de seguimientos, que
    miran el bloqueo en las dos direcciones;
  - tabla `reportes`, que sólo se inserta: no tiene política de lectura;
  - tabla `suscripciones_push`, con RLS de lo propio.
- `src/models/*` — los campos nuevos. `FlightUpdate.cierra_hoja` es opcional, así un
  PATCH que no lo manda no lo pisa.
- `src/controllers/flights.py` — `solo_marcas_del_libro`: un PATCH que sólo cambia
  `cierra_hoja` no re-sincroniza el cobro, ni la auditoría, ni los vencimientos.
- `src/controllers/logbooks.py` — crear y editar aceptan `renglones_por_hoja`.
- `src/controllers/social.py`:
  - `POST/DELETE /pilotos/{h}/bloqueo` y `GET /social/bloqueados`;
  - listas, sugeridos y el perfil público respetan el bloqueo (quien fue bloqueado ve
    404);
  - avisos al seguir y al aceptar.
- `src/controllers/publicaciones.py` — aviso al autor por aplauso y por comentario (en
  segundo plano), y la Actividad sin eventos de bloqueados.
- `src/controllers/cuidado.py` (nuevo):
  - `/push/clave`, `/push/suscripcion` y `/push/baja`;
  - `POST /reportes`, con tope de 20 por día y aviso a `ADMINS_RED`.
- `src/services/avisos.py` (nuevo) — el texto de cada aviso (`armar_aviso`, puro), el
  envío con pywebpush, y el borrado de suscripciones muertas (404/410).
- `src/config.py` — `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` y
  `ADMINS_RED`. `requirements.txt` — `pywebpush`.
- `test_publicaciones.py` y `test_models.py` — bloqueos, avisos, reportes, los campos
  del libro y el PATCH que no recalcula el cobro.

**Por qué:**
- **Deploy detrás del CI:** hasta ahora el backend se desplegaba en cada push, pasara o
  no el CI. Es la misma trampa que ya le costó once commits en rojo en producción al
  frontend.
- **`cierra_hoja` no recalcula el cobro:** `_sync_flight_transaction` usa el
  `cost_per_hour` de hoy. Marcar una hoja reescribía lo que se cobró el día del vuelo.
  Editar el vuelo completo sigue recalculando, como antes, y no se tocó.
- **Bloqueo en el RLS y no sólo en el controlador:** así una consulta nueva no puede
  olvidarse de filtrarlo. `me_bloqueo` es security definer porque el bloqueado no puede
  leer la fila que lo bloquea, y no debe poder.
- **Reportes sin lectura:** los revisa quien administra, directo en la base. Una
  pantalla de moderación, con 6 cuentas, no se justifica.
- **Avisos en un hilo aparte**, y sin claves no se manda nada: un aviso que no llega es
  mejor que un aplauso que falla.
- Las fuentes normativas del libro están en
  `Vector-FrontEnd/docs/normativa/libro-de-vuelo-anac.md`: RAAC 61.120 (VI edición) y
  Res. ANAC 470/2025.

**Estado:** terminado en código. **Orden de despliegue**:

1. aplicar la 020 y la 021 **antes** del deploy, porque los modelos ya mandan las
   columnas nuevas: un alta de vuelo sin la 020 fallaría;
2. generar las claves VAPID y poner `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` y
   `ADMINS_RED` (el user id de Federico) en el `.env` del VPS.

Sin el paso 2 todo anda, pero sin avisos.

**Verificación:**
- `test_social.py`, `test_publicaciones.py`, `test_models.py` (8 ✅),
  `import src.app` y `ruff --select=E9,F`.
- El RLS de la 021, contra la base, en un bloque `DO` que termina en error: todo se
  deshizo, 22 de 22 casos OK.
- La 020 completa, también en un bloque que termina en error, y sin rastros después:
  - el libro existente quedó con 15 renglones;
  - los 51 vuelos, sin cerrar hoja;
  - rechazó 3 renglones por hoja.
- El frontend se probó contra un backend falso con este contrato.
- **Sin verificar:** el envío real de un push, que necesita las claves.

### 2026-09-23 13:31 UTC — Claude (Opus 5.5, vía Claude Code) — El CI sin `.env`: `avisos.py` cargaba la configuración al importarse

**Quién:** Claude Opus 5.5 en Claude Code, para Federico, desplegando la 2.21.0.

**Qué cambié:**
- `src/services/avisos.py` — `settings` se importa recién cuando hace falta
  (`_settings()`), no al cargar el módulo.

**Por qué:** el primer push de la 2.21.0 (`80cee3d`) rompió el paso "Publicaciones y
fotos" del CI. `test_publicaciones.py` importa `avisos` para probar `armar_aviso`, y el
import cargaba `Settings()`, que exige `SUPABASE_URL`. En mi máquina pasaba porque
hay `.env`; en el CI no hay.

Descartado: sumarle las variables de mentira a ese paso de `ci.yml`, como tiene
"Modelos". Taparía que un módulo de funciones puras depende de la configuración para
cargarse.

El deploy nuevo cumplió su función: con el CI en rojo, **no se desplegó nada**.

**Estado:** terminado.

**Verificación:** todos los pasos de `ci.yml` en una copia limpia del repo, sin
`.env` y con las mismas variables que da el CI: import, auditoría, red social,
publicaciones, modelos, cartas y ruff.

### 2026-09-23 13:44 UTC — Claude (Opus 5.5, vía Claude Code) — Configurar los avisos push desde Actions

**Quién:** Claude Opus 5.5 en Claude Code, para Federico ("hacé todo lo que necesites").

**Qué cambié:**
- `.github/workflows/configurar-avisos.yml` (nuevo, manual) — por el mismo SSH del
  Deploy:
  - genera las claves VAPID **en el VPS** (`~/.config/vector/vapid_private.pem`, 600);
  - hace una copia del `.env`;
  - pone `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` (la ruta al PEM) y `ADMINS_RED`;
  - comprueba que el backend lo lea.

  No reinicia: eso lo hace el Deploy manual, con health check y rollback.

**Por qué:**
- Las claves tenían que estar en el `.env` del backend, y SSH desde el Mac depende de
  Tailscale, que figuraba abierto pero sin conectar. El Deploy ya entra al VPS con
  secretos del repo: esto usa ese camino y deja el procedimiento escrito y repetible.
- **La privada nunca sale del VPS.** La alternativa de guardarla como secreto de GitHub
  la habría copiado a un lugar más.
- **Idempotente:** si la clave existe, se reusa. Rotarla invalida todas las
  suscripciones, así que no se hace sin querer.
- **Si la verificación falla, restaura el `.env`:** un `.env` roto tiraría el backend
  en el próximo deploy.
- **La entrada se valida** (sólo UUIDs separados por coma) antes de tocar el VPS.

**Estado:** terminado. Falta correrlo con el user id de Federico y después el Deploy.

**Verificación:** el script, idéntico al del workflow (se comparó con `diff`), corrió en
macOS con adaptadores para `base64 -w0` y `sed -i` de GNU:
- en limpio: genera la clave, agrega las 3 variables y el backend las lee;
- la segunda vez: reusa la clave y no duplica líneas;
- con un `.env` que no carga: sale con error y deja el `.env` idéntico al de antes.

La validación rechaza `x; rm -rf ~`, `|` y vacío.

### 2026-09-23 13:48 UTC — Claude (Opus 5.5, vía Claude Code) — Avisos push configurados en el VPS

**Quién:** Claude Opus 5.5 en Claude Code, para Federico.

**Qué hice:**
- Corrí "Configurar avisos push" con el user id de Federico en `admins`: clave nueva en
  `~/.config/vector/vapid_private.pem` y copia del `.env`
  (`.env.antes-avisos-20260923134552`).
- Después, el Deploy manual: reinició `cbca6e0` con health OK.

**Por qué:** es el paso que faltaba de la 2.21.0 (ver las entradas anteriores).

**Estado:** terminado. Los avisos se ofrecen en la app desde este reinicio.

**Verificación:**
- Por SSH:
  - `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` y `ADMINS_RED` en el `.env`;
  - PEM en 600;
  - `flightlog-7477` arrancó a las 13:46:24 UTC, después del cambio del `.env`
    (13:45:52);
  - sin errores en el log.
- **Sin verificar:** un aviso de punta a punta. Todavía no hay suscripciones, y la
  primera la tiene que hacer Federico desde su teléfono.
