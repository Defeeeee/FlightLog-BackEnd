from litestar.handlers.base import BaseRouteHandler
from litestar.connection import Request
from litestar.exceptions import NotAuthorizedException
from src.auth.security import AuthHandler
from src.supabase_client import SupabaseManager

async def auth_guard(connection: Request, _: BaseRouteHandler) -> None:
    """
    Guard that ensures the request has been authenticated.
    Extracts and verifies the JWT directly from the header because 
    guards execute before dependencies in Litestar.
    """
    token = AuthHandler.extract_bearer_token(connection)
    
    if not token:
        raise NotAuthorizedException("This endpoint requires an active session. Please provide a valid Bearer token.")

    try:
        # Create a user-scoped client temporarily to verify the token
        client = SupabaseManager.get_user_scoped_client(access_token=token)
        user_response = client.auth.get_user(token)
        
        # Cache the user object for downstream use in controllers if needed
        connection.state.user = user_response.user
        
    except Exception as exc:
        raise NotAuthorizedException(detail="Invalid or expired session token") from exc
