from litestar import Controller, get, post, patch, delete, Request
from litestar.exceptions import NotFoundException
from supabase import Client
from typing import List
from uuid import UUID
from src.models.flight import Flight, FlightCreate, FlightUpdate
from src.auth.guards import auth_guard

class FlightsController(Controller):
    path = "/flights"
    guards = [auth_guard]

    @get()
    async def list_flights(self, supabase_client: Client) -> List[Flight]:
        """Fetch all flights the current user has access to."""
        response = supabase_client.table("flights").select("*").execute()
        return [Flight(**data) for data in response.data]

    @get("/{flight_id:uuid}")
    async def get_flight(self, supabase_client: Client, flight_id: UUID) -> Flight:
        """Fetch a specific flight by ID."""
        response = supabase_client.table("flights").select("*").eq("id", str(flight_id)).execute()
        if not response.data:
            raise NotFoundException(f"Flight with ID {flight_id} not found")
        return Flight(**response.data[0])

    @post()
    async def create_flight(self, request: Request, supabase_client: Client, data: FlightCreate) -> Flight:
        """Create a new flight record."""
        insert_data = data.model_dump()
        insert_data["user_id"] = str(request.state.user.id)
        
        # Serialize UUIDs, dates and datetimes
        insert_data["date"] = insert_data["date"].isoformat()
        insert_data["takeoff"] = insert_data["takeoff"].isoformat()
        insert_data["landing"] = insert_data["landing"].isoformat()
        if insert_data.get("aircraft_id"):
            insert_data["aircraft_id"] = str(insert_data["aircraft_id"])

        response = supabase_client.table("flights").insert(insert_data).execute()
        return Flight(**response.data[0])

    @patch("/{flight_id:uuid}")
    async def update_flight(self, supabase_client: Client, flight_id: UUID, data: FlightUpdate) -> Flight:
        """Update a specific flight."""
        update_data = data.model_dump(exclude_unset=True)
        
        # Format datetimes and dates if they exist in the update payload
        if "date" in update_data and update_data["date"]:
            update_data["date"] = str(update_data["date"])
        if "takeoff" in update_data and update_data["takeoff"]:
            update_data["takeoff"] = update_data["takeoff"].isoformat()
        if "landing" in update_data and update_data["landing"]:
            update_data["landing"] = update_data["landing"].isoformat()
        if "aircraft_id" in update_data and update_data["aircraft_id"]:
            update_data["aircraft_id"] = str(update_data["aircraft_id"])

        response = supabase_client.table("flights").update(update_data).eq("id", str(flight_id)).execute()
        
        if not response.data:
            raise NotFoundException(f"Flight with ID {flight_id} not found or permission denied")
        
        return Flight(**response.data[0])

    @delete("/{flight_id:uuid}")
    async def delete_flight(self, supabase_client: Client, flight_id: UUID) -> None:
        """Delete a specific flight."""
        response = supabase_client.table("flights").delete().eq("id", str(flight_id)).execute()
        if not response.data:
            raise NotFoundException(f"Flight with ID {flight_id} not found or permission denied")
