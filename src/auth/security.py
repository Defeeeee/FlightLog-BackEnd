from typing import Optional
from litestar import Request
from litestar.exceptions import NotAuthorizedException
from supabase import Client, create_client
from src.supabase_client import SupabaseManager
from src.config import settings

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
        if a valid JWT is present (set by the guard); otherwise returns an anonymous client.
        """
        # If the guard already verified the user, use that token for RLS
        token = cls.extract_bearer_token(request)
        
        if not token:
            return SupabaseManager.get_base_client()

        return SupabaseManager.get_user_scoped_client(access_token=token)

    @staticmethod
    def provide_base_client() -> Client:
        """Provides a standard anonymous Supabase client."""
        return SupabaseManager.get_base_client()
