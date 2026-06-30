from litestar import Controller, post, get, Request, Response, MediaType
from litestar.exceptions import NotFoundException, ValidationException
from supabase import Client
from datetime import datetime, timezone
from typing import Optional, Any
from uuid import UUID
from src.auth.guards import auth_guard
from src.models.flight_helper import FlightSessionStart, FlightSessionResponse
from src.supabase_client import SupabaseManager

class FlightHelperController(Controller):
    path = "/flight-helper"
    guards = [auth_guard]

    @staticmethod
    def format_flight_hours(minutes: float) -> float:
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
        user_id = str(request.state.user.id)
        now_utc = datetime.now(timezone.utc)

        session_query = supabase_client.table("flight_sessions").select("*").eq("user_id", user_id).execute()
        
        if not session_query.data:
            if not data or not data.aircraft_id:
                raise ValidationException("aircraft_id is required to start a session")
            
            start_data = {
                "user_id": user_id,
                "aircraft_id": str(data.aircraft_id),
                "start_time": now_utc.isoformat(),
                "route": data.route,
                "landings": data.landings
            }
            supabase_client.table("flight_sessions").insert(start_data).execute()

            message = f"Flight started at {now_utc.strftime("%H:%M")} UTC"
            if format == "text":
                return Response(content=message, media_type=MediaType.TEXT)
            return FlightSessionResponse(
                message=message, 
                start_time=now_utc, 
                aircraft_id=data.aircraft_id,
                route=data.route,
                landings=data.landings
            )

        else:
            session = session_query.data[0]
            start_time = datetime.fromisoformat(session["start_time"].replace("Z", "+00:00"))
            
            duration_delta = now_utc - start_time
            total_minutes = duration_delta.total_seconds() / 60
            
            hours_decimal = total_minutes // 60 + self.format_flight_hours(total_minutes % 60)
            flight_time_str = f"{hours_decimal:.1f}hs"

            supabase_client.table("flight_sessions").delete().eq("user_id", user_id).execute()

            message = (
                f"Flight finished!\n"
                f"Start: {start_time.strftime("%H:%M")} UTC\n"
                f"End: {now_utc.strftime("%H:%M")} UTC\n"
                f"Duration: {flight_time_str}"
            )
            
            if format == "text":
                return Response(content=message, media_type=MediaType.TEXT)
            return FlightSessionResponse(
                message=message, 
                start_time=start_time,
                end_time=now_utc,
                flight_time=flight_time_str,
                aircraft_id=UUID(session["aircraft_id"]),
                route=session["route"],
                landings=session["landings"]
            )

    @get("/session")
    async def get_active_session(self, request: Request, supabase_client: Client) -> Any:
        user_id = str(request.state.user.id)
        session_query = supabase_client.table("flight_sessions").select("*").eq("user_id", user_id).execute()
        
        if not session_query.data:
            return {"active": False}
        
        return {"active": True, "session": session_query.data[0]}

    @post("/session/shortcut", guards=[])
    async def toggle_session_shortcut(self, request: Request) -> Any:
        """iOS Shortcut endpoint to toggle starting/stopping a flight session."""
        api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if not api_key:
            raise ValidationException("API Key (X-API-Key header or api_key query param) is required.")

        service_client = SupabaseManager.get_service_client()
        
        profile_resp = service_client.table("profiles").select("id").eq("api_key", api_key).execute()
        if not profile_resp.data:
            raise ValidationException("Invalid API Key.")
        
        user_id = profile_resp.data[0]["id"]
        now_utc = datetime.now(timezone.utc)

        session_query = service_client.table("flight_sessions").select("*").eq("user_id", user_id).execute()

        if not session_query.data:
            try:
                body = await request.json()
            except Exception:
                body = {}

            aircraft_input = body.get("aircraft") or request.query_params.get("aircraft")
            if not aircraft_input:
                raise ValidationException("aircraft registration or ID is required to start a session.")

            route = body.get("route") or request.query_params.get("route")
            landings = body.get("landings") or request.query_params.get("landings") or 1

            acft_resp = service_client.table("aircraft")\
                .select("id, registration")\
                .eq("user_id", user_id)\
                .ilike("registration", aircraft_input.strip())\
                .execute()
            
            if not acft_resp.data:
                acft_resp = service_client.table("aircraft")\
                    .select("id, registration")\
                    .eq("user_id", user_id)\
                    .eq("id", aircraft_input.strip())\
                    .execute()

            if not acft_resp.data:
                raise ValidationException(f"Aircraft '{aircraft_input}' not found.")

            acft = acft_resp.data[0]
            aircraft_id = acft["id"]
            reg = acft["registration"]

            start_data = {
                "user_id": user_id,
                "aircraft_id": aircraft_id,
                "start_time": now_utc.isoformat(),
                "route": route,
                "landings": landings
            }
            service_client.table("flight_sessions").insert(start_data).execute()

            return {
                "active": True,
                "message": f"Vuelo INICIADO con éxito en la aeronave {reg}.",
                "aircraft": reg,
                "start_time": now_utc.isoformat()
            }
        else:
            session = session_query.data[0]
            start_time = datetime.fromisoformat(session["start_time"].replace("Z", "+00:00"))
            
            duration_delta = now_utc - start_time
            total_minutes = duration_delta.total_seconds() / 60
            hours_decimal = total_minutes // 60 + self.format_flight_hours(total_minutes % 60)
            
            service_client.table("flight_sessions").delete().eq("user_id", user_id).execute()

            acft_resp = service_client.table("aircraft").select("registration").eq("id", session["aircraft_id"]).execute()
            reg = acft_resp.data[0]["registration"] if acft_resp.data else "Avión"

            takeoff_str = start_time.strftime("%H:%M")
            landing_str = now_utc.strftime("%H:%M")
            date_str = start_time.strftime("%Y-%m-%d")
            
            base_url = "https://vector.fdiaznem.com.ar"
            link = (
                f"{base_url}/dashboard/log-flight?"
                f"prefill=true&"
                f"aircraft_id={session['aircraft_id']}&"
                f"takeoff={takeoff_str}&"
                f"landing={landing_str}&"
                f"date={date_str}&"
                f"route={session.get('route') or ''}&"
                f"landings={session.get('landings') or 1}&"
                f"duration={hours_decimal:.1f}"
            )

            return {
                "active": False,
                "message": f"Vuelo FINALIZADO en {reg}. Tiempo de vuelo: {hours_decimal:.1f} hs.",
                "duration": hours_decimal,
                "link": link
            }
