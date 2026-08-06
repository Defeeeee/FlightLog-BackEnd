from typing import Optional
from litestar import Request
from supabase import Client
from src.supabase_client import SupabaseManager

class AuthHandler:
    """Handles authentication and provides user-scoped Supabase clients."""

    @staticmethod
    def extract_bearer_token(request: Request) -> Optional[str]:
        """Utility function to extract Bearer token from headers."""
        auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None
        return auth_header.split(" ")[1]

    @classmethod
    async def provide_supabase_client(cls, request: Request) -> Client:
        """
        Dependency Injection Provider: Returns a client configured for RLS 
        if a valid JWT is present (set by the guard); otherwise returns 
        the service client (if authenticated via X-API-Key) or the anonymous client.
        """
        # If the guard already verified the user, use that token for RLS
        token = cls.extract_bearer_token(request)
        
        if not token:
            # Check if authenticated via X-API-Key (which sets connection.state.user in guard)
            if hasattr(request.state, "user") and request.state.user:
                return SupabaseManager.get_service_client()
            return SupabaseManager.get_base_client()

        return SupabaseManager.get_user_scoped_client(access_token=token)

    @staticmethod
    def provide_base_client() -> Client:
        """Provides a standard anonymous Supabase client."""
        return SupabaseManager.get_base_client()
