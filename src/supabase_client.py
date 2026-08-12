from typing import Optional
import httpx
from supabase import create_client, Client, ClientOptions
from src.config import settings


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

    Ninguna de las dos claves puede vencer —el `service_role` va hasta 2036 y la
    publicable es del tipo nuevo, sin `exp`—, así que el JWT vencido sólo podía
    ser el de un usuario.

    Un GET a GoTrue es lo que el SDK hace por dentro. Sin objeto con estado no hay
    nada que contaminar, y se evita igual el `create_client` por request que el
    comentario original quería evitar.
    """
    try:
        response = httpx.get(
            f"{settings.supabase_url}/auth/v1/user",
            headers={
                "apikey": settings.supabase_anon_key,
                "Authorization": f"Bearer {token}",
            },
            timeout=10.0,
        )
    except httpx.HTTPError:
        return None

    if response.status_code != 200:
        return None

    return response.json().get("id")


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
        """
        return ClientOptions(flow_type="implicit", persist_session=persist_session)

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
        Returns a Supabase client instance acting on behalf of a specific user.
        """
        client = create_client(
            supabase_url=settings.supabase_url,
            supabase_key=settings.supabase_anon_key,
            options=SupabaseManager._options()
        )
        
        # 1. Set for Database operations (Postgrest/RLS)
        client.postgrest.auth(access_token)
        
        # 2. Set for Auth operations (update_user, etc.)
        # We set the session manually so the auth client knows who is performing the action
        client.auth.set_session(access_token, "recovery_refresh_token_placeholder")
        
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
