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
CACHE_TTL = 10  # Seconds

async def auth_guard(connection: Request, _: BaseRouteHandler) -> None:
    """
    Guard that ensures the request has been authenticated.
    Uses an in-memory cache to avoid redundant get_user() calls for parallel requests.
    """
    token = AuthHandler.extract_bearer_token(connection)
    
    if not token:
        raise NotAuthorizedException("This endpoint requires an active session.")

    # Check cache first
    now = time.time()
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
