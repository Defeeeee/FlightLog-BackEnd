from litestar import Controller, get, Request
from supabase import Client
from typing import Dict, Any
from src.auth.guards import auth_guard
from src.controllers.flight_packs import FlightPacksController
from src.models.flight import Flight

class DashboardController(Controller):
    path = "/dashboard"
    guards = [auth_guard]

    @get()
    async def get_dashboard_data(self, request: Request, supabase_client: Client) -> Dict[str, Any]:
        """Fetch all data needed for the dashboard in a single optimized request."""
        user_id = str(request.state.user.id)
        
        # 1. Profile
        profile_resp = supabase_client.table("profiles").select("*").eq("id", user_id).execute()
        profile = profile_resp.data[0] if profile_resp.data else None
        
        # 2. Aircraft
        aircraft_resp = supabase_client.table("aircraft").select("*").execute()
        aircraft = aircraft_resp.data
        
        # 3. Flights
        flights_resp = supabase_client.table("flights").select("*").execute()
        flights = [Flight(**data).model_dump(mode="json") for data in flights_resp.data]
        
        # 4. Active Session
        session_resp = supabase_client.table("flight_sessions").select("*").eq("user_id", user_id).execute()
        session_data = session_resp.data[0] if session_resp.data else None
        
        # 5. Flight Packs (Static call)
        packs_data = []
        try:
            packs = await FlightPacksController._get_packs_with_hours(user_id, supabase_client)
            packs_data = [p.model_dump(mode="json") for p in packs]
        except Exception as e:
            print(f"Consolidated dashboard packs error: {str(e)}")
            
        return {
            "profile": profile,
            "aircraft": aircraft,
            "flights": flights,
            "session": {"active": bool(session_data), "session": session_data},
            "packs": packs_data
        }
