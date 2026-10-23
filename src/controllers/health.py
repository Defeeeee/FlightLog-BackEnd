from litestar import Controller, get, MediaType
from litestar.exceptions import InternalServerException
from supabase import Client
import os
from datetime import datetime, timezone
from typing import Any, Dict
from src.auth.security import AuthHandler
from src.services.adsb import latido_del_grabador

class HealthController(Controller):
    """Monitors the operational health of the API and its connection to Supabase."""
    path = "/health"
    dependencies = {"supabase_client": AuthHandler.provide_base_client}
    
    @get(media_type=MediaType.JSON)
    async def health_check(self, supabase_client: Client) -> Dict[str, Any]:
        """
        Verifies both API functionality and database connectivity.
        """
        try:
            # We perform a lightweight SELECT 1 to verify the database connection.
            # Using Supabase's Postgrest interface ensures we're checking the full path.
            # Note: We use .rpc() for the most basic existence check or just select(1)
            supabase_client.table("profiles").select("count").limit(1).execute()
            
            return {
                "status": "healthy",
                "service": "flightlog-backend",
                "database": "connected",
                # Informativo: el grabador ADS-B es otro proceso, y que esté caído no hace
                # que el backend esté mal (el deploy mira este endpoint).
                "grabador_adsb": latido_del_grabador(os.getenv("ADSB_LATIDO", "/tmp/grabador-adsb.json"), datetime.now(timezone.utc)),
            }
        except Exception as e:
            # If the database fails, we want to return a 500 status to alert monitoring systems.
            raise InternalServerException(detail=f"Database connectivity issue: {str(e)}") from e
