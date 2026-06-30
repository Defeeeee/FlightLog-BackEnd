import time
from typing import Dict, Tuple
from litestar.handlers.base import BaseRouteHandler
from litestar.connection import Request
from litestar.exceptions import NotAuthorizedException
from src.auth.security import AuthHandler
from src.supabase_client import SupabaseManager

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
            service_client = SupabaseManager.get_service_client()
            profile_resp = service_client.table("profiles").select("id").eq("api_key", api_key).execute()
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
        # Use the base client for verification to avoid create_client overhead
        client = SupabaseManager.get_base_client()
        user_response = client.auth.get_user(token)
        
        user = user_response.user
        if not user:
            raise NotAuthorizedException("Invalid token: user not found")
            
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
