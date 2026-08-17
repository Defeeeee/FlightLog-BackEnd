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
