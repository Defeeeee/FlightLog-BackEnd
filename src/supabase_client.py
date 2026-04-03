from typing import Optional
from supabase import create_client, Client, ClientOptions
from src.config import settings

class SupabaseManager:
    """Manages the base Supabase client configuration."""
    
    _base_client: Optional[Client] = None
    _options = ClientOptions(flow_type="implicit")
    
    @classmethod
    def get_base_client(cls) -> Client:
        """Returns the base anonymous Supabase client."""
        if cls._base_client is None:
            cls._base_client = create_client(
                supabase_url=settings.supabase_url,
                supabase_key=settings.supabase_anon_key,
                options=cls._options
            )
        return cls._base_client

    @staticmethod
    def get_user_scoped_client(access_token: str) -> Client:
        """
        Returns a Supabase client instance acting on behalf of a specific user.
        """
        client = create_client(
            supabase_url=settings.supabase_url,
            supabase_key=settings.supabase_anon_key,
            options=SupabaseManager._options
        )
        
        # 1. Set for Database operations (Postgrest/RLS)
        client.postgrest.auth(access_token)
        
        # 2. Set for Auth operations (update_user, etc.)
        # We set the session manually so the auth client knows who is performing the action
        client.auth.set_session(access_token, "recovery_refresh_token_placeholder")
        
        return client

    @staticmethod
    def get_service_client() -> Client:
        """Returns a Supabase client using the service role key (bypasses RLS)."""
        if not settings.supabase_service_role_key:
            return create_client(settings.supabase_url, settings.supabase_anon_key, options=SupabaseManager._options)
        
        return create_client(
            supabase_url=settings.supabase_url,
            supabase_key=settings.supabase_service_role_key,
            options=SupabaseManager._options
        )
