from litestar import Controller, get, post, patch, delete, Request
from litestar.exceptions import NotFoundException
from supabase import Client
from typing import List
from uuid import UUID
from src.models.aircraft import Aircraft, AircraftCreate, AircraftUpdate
from src.auth.guards import auth_guard

class AircraftController(Controller):
    path = "/aircraft"
    guards = [auth_guard]

    @get()
    async def list_aircraft(self, supabase_client: Client) -> List[Aircraft]:
        """Fetch all aircraft the current user has access to."""
        response = supabase_client.table("aircraft").select("*").execute()
        return [Aircraft(**data) for data in response.data]

    @get("/{aircraft_id:uuid}")
    async def get_aircraft(self, supabase_client: Client, aircraft_id: UUID) -> Aircraft:
        """Fetch a specific aircraft by ID."""
        response = supabase_client.table("aircraft").select("*").eq("id", str(aircraft_id)).execute()
        if not response.data:
            raise NotFoundException(f"Aircraft with ID {aircraft_id} not found")
        return Aircraft(**response.data[0])

    @post()
    async def create_aircraft(self, request: Request, supabase_client: Client, data: AircraftCreate) -> Aircraft:
        """Create a new aircraft for the authenticated user."""
        insert_data = data.model_dump()
        # Ensure the aircraft is linked to the authenticated user's UUID
        insert_data["user_id"] = str(request.state.user.id)
        
        response = supabase_client.table("aircraft").insert(insert_data).execute()
        return Aircraft(**response.data[0])

    @patch("/{aircraft_id:uuid}")
    async def update_aircraft(self, supabase_client: Client, aircraft_id: UUID, data: AircraftUpdate) -> Aircraft:
        """Update a specific aircraft."""
        update_data = data.model_dump(exclude_unset=True)
        response = supabase_client.table("aircraft").update(update_data).eq("id", str(aircraft_id)).execute()
        if not response.data:
            raise NotFoundException(f"Aircraft with ID {aircraft_id} not found or permission denied")
        return Aircraft(**response.data[0])

    @delete("/{aircraft_id:uuid}")
    async def delete_aircraft(self, supabase_client: Client, aircraft_id: UUID) -> None:
        """Delete a specific aircraft."""
        response = supabase_client.table("aircraft").delete().eq("id", str(aircraft_id)).execute()
        if not response.data:
            raise NotFoundException(f"Aircraft with ID {aircraft_id} not found or permission denied")
