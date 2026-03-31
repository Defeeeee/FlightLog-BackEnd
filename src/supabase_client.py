from typing import Optional
from supabase import create_client, Client
from src.config import settings

class SupabaseManager:
    """Manages the base Supabase client configuration."""
    
    _base_client: Optional[Client] = None
    
    @classmethod
    def get_base_client(cls) -> Client:
        """Returns the base anonymous Supabase client."""
        if cls._base_client is None:
            cls._base_client = create_client(
                supabase_url=settings.supabase_url,
                supabase_key=settings.supabase_anon_key
            )
        return cls._base_client

    @staticmethod
    def get_user_scoped_client(access_token: str) -> Client:
        """
        Returns a Supabase client instance acting on behalf of a specific user.
        """
        client = create_client(
            supabase_url=settings.supabase_url,
            supabase_key=settings.supabase_anon_key
        )
        
        # This ensures the database (Postgrest) uses the user's JWT for RLS
        client.postgrest.auth(access_token)
        
        return client

    @staticmethod
    def get_service_client() -> Client:
        """Returns a Supabase client using the service role key (bypasses RLS)."""
        if not settings.supabase_service_role_key:
            # Fallback to anon key if service role is not provided, 
            # but warn that RLS will apply.
            return create_client(settings.supabase_url, settings.supabase_anon_key)
        
        return create_client(
            supabase_url=settings.supabase_url,
            supabase_key=settings.supabase_service_role_key
        )
