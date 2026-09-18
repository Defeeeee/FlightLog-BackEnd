from typing import Optional
import threading
import time
from functools import lru_cache

import httpx
import jwt
from jwt import PyJWK, PyJWKSet
from supabase import create_client, Client, ClientOptions
from src.config import settings


"""
Cliente HTTP compartido, con su pool de conexiones.

`httpx.get(...)` —la función de módulo— construye un `Client` nuevo, abre una
conexión y hace un handshake TLS **en cada llamada**, y después lo tira. Contra
GoTrue, que vive en us-east-1 mientras el backend corre en São Paulo, ese
handshake solo son ~40 ms que se pagaban en cada request autenticado.

Medido desde el server el 2026-09-18: 190-640 ms por llamada sin pool contra
145-165 ms reusando el cliente.
"""
_http = httpx.Client(timeout=10.0)

def _cachear_contexto_ssl() -> None:
    """
    Que construir un cliente HTTP deje de releer el almacén de certificados.

    **Éste era el costo más caro que quedaba, y no se veía.** Cada `httpx.Client`
    llama a `create_ssl_context()`, que hace `ssl.create_default_context()`, que
    **lee y parsea el bundle de CAs entero desde disco**. Son cientos de
    certificados: ~27 ms cada vez.

    `create_client` de supabase-py arma dos clientes httpx (el de auth y el de
    postgrest), o sea **dos lecturas del bundle por request**. Perfilado en el VPS:
    `load_verify_locations` era 0,546 s de los 0,579 s de construir diez clientes
    — el **94%** del tiempo. Medido de punta a punta, `get_user_scoped_client`
    costaba **58 ms de CPU pura por request**, y como `provide_supabase_client`
    corre en el event loop, eran **~350 ms de bloqueo serializado por carga de
    dashboard** (seis requests).

    Estaba ahí desde siempre; lo tapaba el viaje a GoTrue de `set_session`, que era
    más caro todavía. Al sacar ese viaje, esto quedó como el término dominante — y
    además anulaba parte del pool de 40 hilos, porque bloquear el loop hace que no
    importe cuántos hilos haya libres.

    El arreglo es memoizar: para los mismos parámetros, el contexto es el mismo
    objeto. Un `SSLContext` está **hecho** para compartirse entre conexiones e
    hilos —es el patrón normal, y el propio httpx acepta que le pasen uno ya
    construido—, así que esto no relaja nada: el contexto cacheado sigue con
    `verify_mode=CERT_REQUIRED` y `check_hostname=True`. Verificado: 58,41 ms →
    0,40 ms, **145x**.

    Se parchea también `httpx._transports.default`, porque importa la función por
    valor (`from .._config import create_ssl_context`) y quedarse sólo con
    `_config` no alcanzaría.

    **Es API privada de httpx**, así que todo el parche va adentro de un `try`: si
    una versión nueva cambia de forma, esto no hace nada y el backend sigue
    andando, sólo más lento. Y si los argumentos no son hasheables, cae a la
    función original en vez de romper.
    """
    try:
        import httpx._config as _cfg
        import httpx._transports.default as _dflt
    except Exception:
        return

    original = getattr(_cfg, "create_ssl_context", None)
    if original is None or getattr(original, "_vector_cacheado", False):
        return

    @lru_cache(maxsize=8)
    def _memo(verify, cert, trust_env):
        return original(verify=verify, cert=cert, trust_env=trust_env)

    def cacheado(verify=True, cert=None, trust_env=True):
        try:
            return _memo(verify, cert, trust_env)
        except TypeError:
            # Algún argumento no es hasheable: se construye como siempre.
            return original(verify=verify, cert=cert, trust_env=trust_env)

    cacheado._vector_cacheado = True
    _cfg.create_ssl_context = cacheado
    _dflt.create_ssl_context = cacheado


_cachear_contexto_ssl()


_jwks_lock = threading.Lock()
_jwks_cache: Optional[tuple] = None  # (PyJWKSet, vence_en)
_JWKS_TTL_SEGUNDOS = 3600


def _bajar_jwks() -> PyJWKSet:
    """
    El conjunto de claves públicas del proyecto, recién bajado.

    **Con `_http` y no con `PyJWKClient`, y la diferencia importa.**
    `PyJWKClient` baja el JWKS con `urllib.request`, que trae su propio contexto
    SSL y su propio almacén de certificados — distinto del de `httpx`, que usa
    `certifi`. En un intérprete donde `urllib` no encuentra la CA (pasa, y pasó
    escribiendo esto), la verificación local **fallaría en silencio** y cada
    request se iría al fallback de red: la app seguiría andando y seguiría lenta,
    que es exactamente la clase de regresión que nadie mira.

    Un solo stack HTTP, uno solo que pueda romperse, y el mismo pool de conexiones
    que ya usa el fallback.
    """
    respuesta = _http.get(
        f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    )
    respuesta.raise_for_status()
    return PyJWKSet.from_dict(respuesta.json())


def _jwks(refrescar: bool = False) -> PyJWKSet:
    """
    El JWKS cacheado. Una bajada por hora, no una por request.

    El fetch va **afuera** del lock: adentro, un JWKS lento dejaría a todos los
    hilos del guard esperando por una operación de red, que es justo lo que este
    cambio vino a sacar del camino.
    """
    global _jwks_cache

    # Todo adentro del lock, **incluida la bajada**. Con el fetch afuera, N
    # requests que llegan juntos con el cache frío fallan todos la comprobación y
    # bajan el JWKS N veces: se vio en producción el 2026-09-18, seis bajadas en
    # 300 ms en el primer login después de un restart. Adentro, el primero baja y
    # los demás esperan y encuentran el cache ya puesto.
    #
    # El precio es que esos pocos requests esperan a uno solo, y es el precio
    # correcto: esto pasa una vez por hora, no una vez por request.
    with _jwks_lock:
        if not refrescar and _jwks_cache and time.time() < _jwks_cache[1]:
            return _jwks_cache[0]

        conjunto = _bajar_jwks()
        _jwks_cache = (conjunto, time.time() + _JWKS_TTL_SEGUNDOS)
        return conjunto


def _clave_de_firma(token: str) -> PyJWK:
    """
    La clave pública con la que se firmó este token, por su `kid`.

    Si el `kid` no está en el conjunto cacheado se baja **una vez más** antes de
    darlo por inválido: es exactamente lo que pasa cuando Supabase rota las
    claves, y sin este reintento la app quedaría rechazando tokens legítimos hasta
    que venza el cache de una hora.
    """
    kid = jwt.get_unverified_header(token).get("kid")
    if not kid:
        raise jwt.InvalidTokenError("el token no declara kid")

    for refrescar in (False, True):
        for clave in _jwks(refrescar=refrescar).keys:
            if clave.key_id == kid:
                return clave

    raise jwt.InvalidKeyError(f"kid desconocido: {kid}")


def _verificar_localmente(token: str) -> Optional[str]:
    """
    El `sub` del token, verificando la firma acá mismo. Sin red.

    Este proyecto firma con **ES256** y publica su clave pública en el JWKS
    (`/auth/v1/.well-known/jwks.json`, abierto, sin apikey). O sea que la
    verificación no necesita preguntarle nada a nadie: se baja la clave una vez,
    se cachea una hora, y cada token se valida con criptografía local. Medido:
    **0,05 ms**, contra 145-640 ms del viaje a GoTrue que reemplaza.

    **`algorithms` sólo lista algoritmos asimétricos a propósito.** Aceptar
    `HS256` acá sería el ataque de confusión de algoritmo clásico: un atacante
    firma un token con la clave *pública* —que es pública— como si fuera un
    secreto HMAC, y la librería lo valida. Con la lista restringida a ES256/RS256
    ese token ni se intenta. Hay un test que lo comprueba
    (`test_verify_token.py`); si alguien agrega "HS256" acá, falla.

    Tira si el token no es válido; quien llama decide si cae al camino de red.
    """
    claims = jwt.decode(
        token,
        _clave_de_firma(token).key,
        algorithms=["ES256", "RS256"],
        audience="authenticated",
        issuer=f"{settings.supabase_url.rstrip('/')}/auth/v1",
        options={"require": ["exp", "sub"]},
    )
    return claims.get("sub")


def _verificar_contra_gotrue(token: str) -> Optional[str]:
    """
    El camino viejo: preguntarle a GoTrue quién es el dueño del token.

    Queda como red de contención de `_verificar_localmente`, no como camino
    normal. Cubre los casos donde la verificación local legítimamente no puede
    decidir: un token viejo firmado con el secreto simétrico (de antes de que el
    proyecto pasara a claves asimétricas), o una rotación de claves que el cache
    del JWKS todavía no vio.

    Un token adulterado también cae acá, y está bien: GoTrue lo rechaza. Este
    camino es el que manda, así que la verificación local nunca puede *aflojar*
    la seguridad — sólo evitar el viaje cuando ya alcanza.
    """
    try:
        response = _http.get(
            f"{settings.supabase_url}/auth/v1/user",
            headers={
                "apikey": settings.supabase_anon_key,
                "Authorization": f"Bearer {token}",
            },
        )
    except httpx.HTTPError:
        return None

    if response.status_code != 200:
        return None

    return response.json().get("id")


def verify_access_token(token: str) -> Optional[str]:
    """
    El `sub` del token, o `None` si no es válido.

    **Sin cliente de por medio, y ese es el punto.** Antes esto se hacía con
    `SupabaseManager.get_base_client().auth.get_user(token)`, o sea pasándole el
    token de un usuario cualquiera al cliente **compartido de por vida** que
    además sirve las consultas anónimas —entre ellas `/health`—.

    El resultado, visto en producción el 2026-08-10: el cliente quedaba firmando
    con el access token del último usuario que se autenticó, ese token vencía a la
    hora, y desde entonces **toda consulta anónima devolvía `PGRST303 JWT expired`
    hasta que alguien reiniciaba el proceso**. Cuadra con el episodio del
    2026-08-04, donde el dashboard andaba (vivía del `TOKEN_CACHE` de 10s) y
    Reanalizar fallaba (caía fuera y tocaba el cliente ya contaminado). Se
    diagnosticó como "la clave anónima venció" y se rotó; lo que la arregló fue el
    reinicio del deploy, no la rotación.

    **Desde 2026-09-18 verifica local y sólo cae a la red si no puede.** Antes
    era siempre un GET a GoTrue en us-east-1: 145-640 ms medidos desde São Paulo,
    en el camino caliente de *cada* request autenticado. La firma es ES256 y la
    clave pública está publicada, así que ese viaje no compraba nada que no se
    pueda comprobar acá.
    """
    if not token:
        return None

    try:
        sub = _verificar_localmente(token)
        if sub:
            return sub
    except Exception:
        # Firma que no valida, token vencido, clave que no está en el JWKS: todo
        # cae acá. No se loguea porque un token inválido es un evento normal
        # (sesión vencida) y esto corre en el camino caliente.
        pass

    return _verificar_contra_gotrue(token)


class SupabaseManager:
    """Manages the base Supabase client configuration."""

    @staticmethod
    def _options(persist_session: bool = True) -> ClientOptions:
        """
        **Options nuevas en cada llamada. Nunca una instancia compartida.**

        Acá estuvo la segunda mitad del bug de sesiones cruzadas, y es la parte
        que no se ve leyendo el código de Vector. `ClientOptions` declara:

            storage: SyncSupportedStorage = field(default_factory=SyncMemoryStorage)

        El `default_factory` da un storage nuevo **por instancia de options**. Pero
        `supabase-py` hace `self.options = copy.copy(options)` —copia
        **superficial**— y sólo rehace el dict de `headers`: **el `storage` sigue
        siendo el mismo objeto** (`_sync/client.py:72-74`, verificado en 2.28.3).

        Con un único `ClientOptions` compartido, todos los clientes del proceso
        comparten un storage de sesión. Entonces:

          1. `AuthController.login` hace `sign_in_with_password` y la sesión del
             piloto queda guardada ahí.
          2. Cualquier cliente creado después —incluido el de **service role**—
             nace con ese storage, recupera la sesión, dispara `SIGNED_IN`, y
             `_listen_to_auth_events` le pisa el `Authorization` con el token de
             ese usuario.
          3. PostgREST prioriza `Authorization` sobre `apikey`: el cliente de
             service role pasa a consultar como `authenticated` y **RLS le tapa
             las filas de los demás**.

        Medido en los logs de Supabase el 2026-08-12: el barrido de vencimientos
        salía con `apikey=service_role` y `authorization=authenticated`, y traía
        3 de 6 documentos. Los del resto de los pilotos eran invisibles, sin ningún
        error: devolvía una lista vacía como si no hubiera nada por avisar.

        `persist_session=False` para el cliente de service role: no representa a
        nadie y no tiene por qué guardar ni recuperar sesiones.

        **`auto_refresh_token=False` en todos.** Guardar una sesión con
        `set_session` arranca un timer de refresco que, cuando vence, hace
        `POST /auth/v1/token?grant_type=refresh_token`. Acá el refresh token es el
        literal `"recovery_refresh_token_placeholder"` —el backend nunca lo
        recibe, sólo tiene el access token del bearer—, así que **cada intento es
        un 400 garantizado**. Medido en los logs de Supabase en 24 h: 128 × 400 y
        86 × 429 contra `/auth/v1/token`, o sea que además nos estábamos
        rate-limitando solos.

        Y el 400 no es sólo ruido: al fallar el refresco, GoTrue borra la sesión y
        emite `SIGNED_OUT`, que `_listen_to_auth_events` traduce en descartar el
        `postgrest` del cliente y devolver la cabecera `Authorization` a la clave
        anónima. Si eso pasa mientras el request está en vuelo —el dashboard corre
        ocho consultas en hilos sobre **el mismo cliente**— las que lleguen
        después consultan sin la identidad del piloto. Ver `get_user_scoped_client`.

        Un cliente por request no tiene ninguna razón para refrescar nada: vive
        menos de lo que tarda un token en vencer.
        """
        return ClientOptions(
            flow_type="implicit",
            persist_session=persist_session,
            auto_refresh_token=False,
        )

    @classmethod
    def get_base_client(cls) -> Client:
        """
        Cliente anónimo **nuevo en cada llamada**. Antes era un singleton, y ahí
        estaba el bug.

        Un cliente de `supabase-py` **no es un objeto sin estado**: se suscribe a
        los eventos de su propio `auth` y, ante `SIGNED_IN` o `TOKEN_REFRESHED`,
        se reemplaza la cabecera `Authorization` por el access token de esa sesión
        y descarta su `postgrest` para reconstruirlo con la nueva
        (`supabase/_sync/client.py:_listen_to_auth_events`, verificado en 2.28.3,
        la versión que corre en producción).

        `AuthController.login` recibe este cliente por inyección —`/auth/login` no
        lleva bearer token, así que `provide_supabase_client` caía acá— y le hace
        `sign_in_with_password`. Con el cliente cacheado, **cada login dejaba al
        proceso entero firmando con el token de esa persona**. Una hora después,
        toda consulta anónima —incluida `/health`— devolvía `PGRST303 JWT expired`
        hasta el próximo restart.

        Crear el cliente por request cuesta poco y sólo pasa en las rutas sin
        sesión (`/health`, login, registro, recuperación): el camino caliente, la
        verificación de tokens del guard, ya no pasa por acá sino por
        `verify_access_token`.

        **No volver a cachearlo.** Mientras cualquier consumidor pueda iniciar
        sesión sobre el cliente que recibe, compartirlo es compartir esa sesión.
        """
        return create_client(
            supabase_url=settings.supabase_url,
            supabase_key=settings.supabase_anon_key,
            options=cls._options()
        )

    @staticmethod
    def get_user_scoped_client(access_token: str) -> Client:
        """
        Un cliente que consulta en nombre de un piloto. **Sin red.**

        Antes esto empezaba con
        `client.auth.set_session(access_token, "...placeholder")`, y ahí estaba
        escondido el costo más caro de toda la app. `set_session`, cuando el token
        **no** está vencido, llama a `self.get_user(access_token)`
        (`supabase_auth/_sync/gotrue_client.py`) — o sea **un GET a GoTrue en
        us-east-1**, sincrónico, para llenar un campo `user` que ningún consumidor
        de este cliente mira. Medido desde el server el 2026-09-18: 145-640 ms,
        en cada request autenticado, sin cache de ningún tipo.

        `postgrest.auth(access_token)` es lo único que hace falta para que RLS vea
        al piloto correcto, y no toca la red: pone el token en la cabecera y listo.

        Sacar `set_session` además **cierra la carrera** que este docstring
        describía. Emitía `SIGNED_IN`, y `_listen_to_auth_events` reacciona
        poniendo `self._postgrest = None` para reconstruirlo perezosamente
        (`supabase/_sync/client.py`, verificado en 2.28.3). Con `/dashboard`
        disparando ocho consultas en hilos sobre el mismo cliente, los ocho podían
        entrar a la vez a ese inicializador perezoso. Ahora no hay nada perezoso:
        `postgrest` sale de acá construido y firmado, y nada lo invalida después.

        Las dos rutas que sí necesitan una sesión de auth de verdad
        —`/auth/update-password` y la reparación de perfil en `/profiles`— la
        piden explícitamente con `establecer_sesion_de_auth`. Son caminos fríos:
        pagan el viaje ellas, no las trece pantallas del dashboard.
        """
        client = create_client(
            supabase_url=settings.supabase_url,
            supabase_key=settings.supabase_anon_key,
            options=SupabaseManager._options()
        )

        # Para la base (PostgREST/RLS). Materializa el postgrest y le pone el
        # token: al salir de acá no queda nada perezoso por construir.
        client.postgrest.auth(access_token)

        return client

    @staticmethod
    def get_service_client() -> Client:
        """
        Cliente de service role, que salta RLS y corre sobre todos los usuarios.

        `persist_session=False`: este cliente no representa a ningún piloto, así
        que no tiene por qué guardar ni **recuperar** sesiones. Sin eso heredaba la
        del último login por el storage compartido y terminaba consultando como
        `authenticated`, con RLS tapándole las filas ajenas. Ver `_options`.

        **El fallback a la clave anónima es peligroso y por eso avisa.** Un barrido
        que corre sobre todos los usuarios y de golpe ve sólo los de uno no falla:
        devuelve menos filas, en silencio. Sin este log, descubrirlo cuesta lo que
        costó el 2026-08-12.
        """
        if not settings.supabase_service_role_key:
            print(
                "[supabase] SUPABASE_SERVICE_ROLE_KEY no está configurada: "
                "cayendo a la clave anónima. Todo lo que corra sobre varios "
                "usuarios (barrido de vencimientos, WhatsApp) va a ver de menos."
            )
            return create_client(
                settings.supabase_url,
                settings.supabase_anon_key,
                options=SupabaseManager._options(persist_session=False),
            )

        return create_client(
            supabase_url=settings.supabase_url,
            supabase_key=settings.supabase_service_role_key,
            options=SupabaseManager._options(persist_session=False),
        )


def establecer_sesion_de_auth(client: Client, access_token: str) -> None:
    """
    Carga la sesión del piloto en el cliente, para operaciones de **auth**.

    Sólo hace falta para lo que toca a GoTrue y no a la base: `update_user`,
    `get_user()` sin argumento. Para consultar tablas alcanza con el
    `postgrest.auth(...)` que ya hizo `get_user_scoped_client`.

    **Cuesta un viaje a us-east-1** (`set_session` llama a `get_user` por dentro
    cuando el token no está vencido), así que se pide a mano y no por defecto. Ver
    `get_user_scoped_client`: tenerlo por defecto le costaba ~200 ms a cada
    request autenticado de la aplicación para servir a dos rutas frías.
    """
    client.auth.set_session(access_token, "recovery_refresh_token_placeholder")
