from litestar import Controller, post, get, Request, Response, MediaType
from litestar.exceptions import NotFoundException, BadRequestException
from supabase import Client
from datetime import datetime, timezone
from typing import Optional, Any
from uuid import UUID
from src.auth.guards import auth_guard
from src.models.flight_helper import FlightSessionStart, FlightSessionResponse

class FlightHelperController(Controller):
    path = "/flight-helper"
    guards = [auth_guard]

    @staticmethod
    def format_flight_hours(minutes: float) -> float:
        """
        Format flight time in hours based on the specific FlightHelper mapping:
        1 to 2 minutes .0hs, 3 to 8 .1hs, 9 to 14 .2hs, 15 to 20 .3hs, 21 to 26 .4hs,
        27 to 33 .5hs, 34 to 39 .6hs, 40 to 45 .7hs, 46 to 51 .8hs, 52 to 57 .9hs,
        58 to 60 1.0hs
        """
        if minutes < 1: return 0.0
        if 1 <= minutes <= 2: return 0.0
        if 3 <= minutes <= 8: return 0.1
        if 9 <= minutes <= 14: return 0.2
        if 15 <= minutes <= 20: return 0.3
        if 21 <= minutes <= 26: return 0.4
        if 27 <= minutes <= 33: return 0.5
        if 34 <= minutes <= 39: return 0.6
        if 40 <= minutes <= 45: return 0.7
        if 46 <= minutes <= 51: return 0.8
        if 52 <= minutes <= 57: return 0.9
        if 58 <= minutes <= 60: return 1.0
        return 0.0

    @post("/session")
    async def toggle_session(
        self, 
        request: Request, 
        supabase_client: Client, 
        data: Optional[FlightSessionStart] = None,
        format: Optional[str] = None
    ) -> Any:
        """
        Starts or ends a flight session.
        If no active session exists, starts one.
        If an active session exists, ends it and saves to the flights table.
        """
        user_id = str(request.state.user.id)
        now_utc = datetime.now(timezone.utc)

        # 1. Check for an active session in 'flight_sessions'
        session_query = supabase_client.table("flight_sessions").select("*").eq("user_id", user_id).execute()
        
        if not session_query.data:
            # START SESSION
            if not data or not data.aircraft_id:
                raise BadRequestException("aircraft_id is required to start a session")
            
            start_data = {
                "user_id": user_id,
                "aircraft_id": str(data.aircraft_id),
                "start_time": now_utc.isoformat(),
                "route": data.route,
                "landings": data.landings
            }
            supabase_client.table("flight_sessions").insert(start_data).execute()

            message = f"🛫 Flight started at {now_utc.strftime('%H:%M')} UTC"
            if format == "text":
                return Response(content=message, media_type=MediaType.TEXT)
            return FlightSessionResponse(message=message, start_time=now_utc, aircraft_id=data.aircraft_id)

        else:
            # END SESSION
            session = session_query.data[0]
            start_time = datetime.fromisoformat(session["start_time"].replace('Z', '+00:00'))
            
            duration_delta = now_utc - start_time
            total_minutes = duration_delta.total_seconds() / 60
            
            # Use custom FlightHelper hour calculation
            hours_decimal = total_minutes // 60 + self.format_flight_hours(total_minutes % 60)
            flight_time_str = f"{hours_decimal:.1f}hs"

            # 2. Save to 'flights' table
            flight_record = {
                "user_id": user_id,
                "aircraft_id": session["aircraft_id"],
                "date": now_utc.date().isoformat(),
                "route": session["route"] or "Unknown",
                "landings": session["landings"] or 0,
                "duration": hours_decimal,
                "takeoff": start_time.isoformat(),
                "landing": now_utc.isoformat()
            }
            supabase_client.table("flights").insert(flight_record).execute()

            # 3. Clear the active session
            supabase_client.table("flight_sessions").delete().eq("user_id", user_id).execute()

            message = (
                f"🛬 Flight finished!\n"
                f"Start: {start_time.strftime('%H:%M')} UTC\n"
                f"End: {now_utc.strftime('%H:%M')} UTC\n"
                f"Duration: {flight_time_str}"
            )
            
            if format == "text":
                return Response(content=message, media_type=MediaType.TEXT)
            return FlightSessionResponse(message=message, flight_time=flight_time_str)

    @get("/session")
    async def get_active_session(self, request: Request, supabase_client: Client) -> Any:
        """Returns the current active session if any."""
        user_id = str(request.state.user.id)
        session_query = supabase_client.table("flight_sessions").select("*").eq("user_id", user_id).execute()
        
        if not session_query.data:
            return {"active": False}
        
        return {"active": True, "session": session_query.data[0]}
