from litestar import Controller, get, post, patch, delete, Request
from litestar.exceptions import NotFoundException
from supabase import Client
from typing import List
from uuid import UUID
from datetime import datetime
from src.models.flight_pack import FlightPack, FlightPackCreate, FlightPackUpdate
from src.auth.guards import auth_guard

class FlightPacksController(Controller):
    path = "/flight-packs"
    guards = [auth_guard]

    @get()
    async def list_packs(self, request: Request, supabase_client: Client) -> List[FlightPack]:
        """Fetch all flight packs for the current user with remaining hours optimized."""
        return await self._get_packs_with_hours(str(request.state.user.id), supabase_client)

    @staticmethod
    async def _get_packs_with_hours(user_id: str, supabase_client: Client) -> List[FlightPack]:
        """Core logic for fetching packs with calculated hours."""
        # 1. Fetch all flight packs
        packs_resp = supabase_client.table("flight_packs").select("*").eq("user_id", user_id).execute()
        if not packs_resp.data:
            return []
            
        # 2. Fetch all aircraft associations for these packs
        pack_ids = [p["id"] for p in packs_resp.data]
        ac_resp = supabase_client.table("flight_pack_aircraft").select("*").in_("pack_id", pack_ids).execute()
        
        # Map aircraft IDs to each pack
        pack_aircraft = {}
        all_relevant_aircraft_ids = set()
        for item in ac_resp.data:
            pid = item["pack_id"]
            aid = item["aircraft_id"]
            if pid not in pack_aircraft:
                pack_aircraft[pid] = []
            pack_aircraft[pid].append(aid)
            all_relevant_aircraft_ids.add(aid)
            
        # 3. Fetch all flights for these aircraft for this user
        all_flights = []
        if all_relevant_aircraft_ids:
            flights_resp = supabase_client.table("flights")\
                .select("duration, takeoff, aircraft_id")\
                .eq("user_id", user_id)\
                .in_("aircraft_id", list(all_relevant_aircraft_ids))\
                .execute()
            all_flights = flights_resp.data
        
        # 4. Build final pack list with in-memory calculation
        packs = []
        for data in packs_resp.data:
            pid = data["id"]
            aids = pack_aircraft.get(pid, [])
            start_date_str = data["start_date"]
            
            # Filter flights for this pack
            used_hours = sum(
                float(f.get("duration") or 0.0) 
                for f in all_flights 
                if f.get("aircraft_id") in aids and f.get("takeoff", "") >= start_date_str
            )
            
            pack = FlightPack(
                **data,
                aircraft_ids=[UUID(aid) for aid in aids],
                remaining_hours=float(data["total_hours"]) - used_hours
            )
            packs.append(pack)
        
        return packs

    @post()
    async def create_pack(self, request: Request, supabase_client: Client, data: FlightPackCreate) -> FlightPack:
        """Create a new flight pack."""
        user_id = str(request.state.user.id)
        
        # Insert pack
        pack_data = {
            "name": data.name,
            "total_hours": data.total_hours,
            "user_id": user_id,
            "is_active": data.is_active
        }
        if data.start_date:
            pack_data["start_date"] = data.start_date.isoformat()
            
        response = supabase_client.table("flight_packs").insert(pack_data).execute()
        new_pack_data = response.data[0]
        pack_id = new_pack_data["id"]
        
        # Insert aircraft associations
        if data.aircraft_ids:
            assoc_data = [{"pack_id": pack_id, "aircraft_id": str(aid)} for aid in data.aircraft_ids]
            supabase_client.table("flight_pack_aircraft").insert(assoc_data).execute()
        
        # Recalculate remaining hours
        flights_resp = supabase_client.table("flights")\
            .select("duration")\
            .eq("user_id", user_id)\
            .in_("aircraft_id", [str(aid) for aid in data.aircraft_ids])\
            .gte("takeoff", new_pack_data["start_date"])\
            .execute()
        
        used_hours = sum(float(f["duration"]) for f in flights_resp.data)

        return FlightPack(
            **new_pack_data,
            aircraft_ids=data.aircraft_ids,
            remaining_hours=float(new_pack_data["total_hours"]) - used_hours
        )

    @patch("/{pack_id:uuid}")
    async def update_pack(self, request: Request, supabase_client: Client, pack_id: UUID, data: FlightPackUpdate) -> FlightPack:
        """Update a specific flight pack."""
        user_id = str(request.state.user.id)
        
        update_data = data.model_dump(exclude_unset=True, exclude={"aircraft_ids"}, mode="json")
        if update_data:
            response = supabase_client.table("flight_packs").update(update_data).eq("id", str(pack_id)).eq("user_id", user_id).execute()
            if not response.data:
                raise NotFoundException(f"Flight pack with ID {pack_id} not found")
            updated_pack_data = response.data[0]
        else:
            response = supabase_client.table("flight_packs").select("*").eq("id", str(pack_id)).eq("user_id", user_id).execute()
            if not response.data:
                raise NotFoundException(f"Flight pack with ID {pack_id} not found")
            updated_pack_data = response.data[0]

        # Update aircraft associations if provided
        if data.aircraft_ids is not None:
            # Delete old associations
            supabase_client.table("flight_pack_aircraft").delete().eq("pack_id", str(pack_id)).execute()
            # Insert new ones
            if data.aircraft_ids:
                assoc_data = [{"pack_id": str(pack_id), "aircraft_id": str(aid)} for aid in data.aircraft_ids]
                supabase_client.table("flight_pack_aircraft").insert(assoc_data).execute()
            aircraft_ids = data.aircraft_ids
        else:
            ac_resp = supabase_client.table("flight_pack_aircraft").select("aircraft_id").eq("pack_id", str(pack_id)).execute()
            aircraft_ids = [UUID(item["aircraft_id"]) for item in ac_resp.data]

        # Recalculate remaining hours
        flights_resp = supabase_client.table("flights")\
            .select("duration")\
            .eq("user_id", user_id)\
            .in_("aircraft_id", [str(aid) for aid in aircraft_ids])\
            .gte("takeoff", updated_pack_data["start_date"])\
            .execute()
        
        used_hours = sum(float(f["duration"]) for f in flights_resp.data)

        return FlightPack(
            **updated_pack_data,
            aircraft_ids=aircraft_ids,
            remaining_hours=float(updated_pack_data["total_hours"]) - used_hours
        )


    @delete("/{pack_id:uuid}")
    async def delete_pack(self, request: Request, supabase_client: Client, pack_id: UUID) -> None:
        """Delete a specific flight pack."""
        user_id = str(request.state.user.id)
        response = supabase_client.table("flight_packs").delete().eq("id", str(pack_id)).eq("user_id", user_id).execute()
        if not response.data:
            raise NotFoundException(f"Flight pack with ID {pack_id} not found")
