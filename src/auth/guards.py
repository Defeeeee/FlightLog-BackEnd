import asyncio
import time
from typing import Dict, Tuple
from litestar.handlers.base import BaseRouteHandler
from litestar.connection import Request
from litestar.exceptions import NotAuthorizedException
from src.auth.security import AuthHandler
from src.supabase_client import SupabaseManager, verify_access_token

# Simple in-memory cache for verified tokens to speed up parallel requests
# Key: token, Value: (user_obj, expiry_timestamp)
TOKEN_CACHE: Dict[str, Tuple[any, float]] = {}
# Key: api_key, Value: (user_obj, expiry_timestamp)
API_KEY_CACHE: Dict[str, Tuple[any, float]] = {}
CACHE_TTL = 10  # Seconds

class SimpleUser:
    def __init__(self, user_id: str):
        self.id = user_id

async def auth_guard(connection: Request, _: BaseRouteHandler) -> None:
    """
    Guard that ensures the request has been authenticated.
    Supports Bearer Token (JWT) or X-API-Key header.
    """
    token = AuthHandler.extract_bearer_token(connection)
    now = time.time()
    
    if not token:
        # Fallback to X-API-Key authentication
        api_key = connection.headers.get("X-API-Key") or connection.query_params.get("api_key")
        if not api_key:
            raise NotAuthorizedException("This endpoint requires an active session or a valid X-API-Key.")

        # Check API key cache
        if api_key in API_KEY_CACHE:
            user, expiry = API_KEY_CACHE[api_key]
            if now < expiry:
                connection.state.user = user
                return
            else:
                del API_KEY_CACHE[api_key]

        try:
            # `to_thread` por lo mismo que abajo: `supabase-py` es sincrónico y
            # esto es una consulta a us-east-1.
            def _buscar_por_api_key():
                service_client = SupabaseManager.get_service_client()
                return service_client.table("profiles").select("id").eq("api_key", api_key).execute()

            profile_resp = await asyncio.to_thread(_buscar_por_api_key)
            if not profile_resp.data:
                raise NotAuthorizedException("Invalid API Key.")
            
            user_id = profile_resp.data[0]["id"]
            user = SimpleUser(user_id)
            
            # Cache the API key
            API_KEY_CACHE[api_key] = (user, now + CACHE_TTL)
            connection.state.user = user
            return
        except Exception as exc:
            raise NotAuthorizedException("Invalid API Key.") from exc

    # Bearer Token flow
    if token in TOKEN_CACHE:
        user, expiry = TOKEN_CACHE[token]
        if now < expiry:
            connection.state.user = user
            return
        else:
            del TOKEN_CACHE[token]

    try:
        # Verificación sin cliente con estado. Antes esto usaba el singleton
        # anónimo —el mismo que sirve /health—, que quedaba firmando con el token
        # del último usuario verificado y tiraba PGRST303 en cuanto ese token
        # vencía, hasta el siguiente restart. Ver `verify_access_token`.
        # ------------------------------------------------------------------
        # `to_thread` y no la llamada directa.
        # ------------------------------------------------------------------
        #
        # Este guard es `async` pero `verify_access_token` es sincrónico, así que
        # llamarlo derecho **bloquea el event loop entero** mientras dura. Con la
        # verificación contra GoTrue eso eran ~200 ms por request, y como Litestar
        # atiende todo en un solo loop, los requests concurrentes se hacían cola
        # uno atrás del otro en vez de solaparse.
        #
        # Medido en producción el 2026-09-18, seis requests concurrentes a
        # `/api/profiles` —exactamente las que manda una carga del dashboard—:
        # 0.198, 0.397, 0.593, 0.792, 0.987, 1.182 s. Una escalera perfecta de
        # ~197 ms de escalón. 1,2 s de pared para algo que debía tardar 200 ms.
        #
        # Hoy el camino normal verifica local y no toca la red (ver
        # `verify_access_token`), pero el fallback sí, y el costo de un hilo es de
        # microsegundos. No vale la pena volver a apostar el loop a que la red no
        # haga falta.
        user_id = await asyncio.to_thread(verify_access_token, token)

        if not user_id:
            raise NotAuthorizedException("Invalid token: user not found")

        user = SimpleUser(user_id)

        # Cache the result for a short duration
        TOKEN_CACHE[token] = (user, now + CACHE_TTL)
        
        # Cleanup old cache entries occasionally
        if len(TOKEN_CACHE) > 100:
            expired_keys = [k for k, v in TOKEN_CACHE.items() if time.time() > v[1]]
            for k in expired_keys:
                del TOKEN_CACHE[k]
                
        connection.state.user = user
        
    except Exception as exc:
        raise NotAuthorizedException(detail="Invalid or expired session token") from exc
