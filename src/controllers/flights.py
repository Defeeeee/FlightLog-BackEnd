from litestar import Controller, get, post, patch, delete, Request
from litestar.exceptions import NotFoundException
from supabase import Client
from typing import List, Optional
from uuid import UUID
from src.models.flight import Flight, FlightCreate, FlightUpdate
from src.auth.guards import auth_guard

class FlightsController(Controller):
    path = "/flights"
    guards = [auth_guard]

    async def _sync_flight_transaction(
        self,
        user_id: str,
        flight_id: str,
        duration: float,
        aircraft_id: Optional[str],
        route: str,
        discount_type: Optional[str],
        discount_amount: Optional[float],
        supabase_client: Client
    ) -> None:
        # 1. Check user tracking mode
        profile_query = supabase_client.table("profiles").select("tracking_mode").eq("id", user_id).execute()
        tracking_mode = profile_query.data[0].get("tracking_mode", "packs") if profile_query.data else "packs"

        if tracking_mode != "balance":
            # If not in balance mode, ensure no transaction exists for this flight (in case they switched modes)
            supabase_client.table("transactions").delete().eq("flight_id", flight_id).execute()
            return

        # 2. Get aircraft cost per hour
        cost_per_hour = 0.0
        if aircraft_id:
            acft_query = supabase_client.table("aircraft").select("cost_per_hour").eq("id", aircraft_id).execute()
            if acft_query.data:
                cost_per_hour = float(acft_query.data[0].get("cost_per_hour") or 0.0)

        # 3. Calculate gross cost
        gross_cost = duration * cost_per_hour

        # 4. Calculate discount
        discount = 0.0
        d_amount = float(discount_amount or 0.0)
        if discount_type == "value":
            discount = d_amount
        elif discount_type == "percent":
            discount = gross_cost * (d_amount / 100.0)

        # 5. Calculate net cost
        net_cost = max(0.0, gross_cost - discount)

        # 6. Check if transaction already exists for this flight
        tx_query = supabase_client.table("transactions").select("id").eq("flight_id", flight_id).execute()
        
        tx_data = {
            "user_id": user_id,
            "flight_id": flight_id,
            "amount": -net_cost,
            "type": "charge",
            "description": f"Vuelo {route} ({duration:.1f} hs)"
        }

        if tx_query.data:
            # Update existing
            tx_id = tx_query.data[0]["id"]
            supabase_client.table("transactions").update(tx_data).eq("id", tx_id).execute()
        else:
            # Create new
            supabase_client.table("transactions").insert(tx_data).execute()

    @get()
    async def list_flights(self, request: Request, supabase_client: Client) -> List[Flight]:
        """Fetch all flights belonging to the authenticated user."""
        user_id = str(request.state.user.id)
        response = supabase_client.table("flights").select("*").eq("user_id", user_id).execute()
        # Pydantic's populate_by_name=True allows mapping DB names (with spaces) to model fields
        return [Flight(**data) for data in response.data]

    @get("/{flight_id:uuid}")
    async def get_flight(self, request: Request, supabase_client: Client, flight_id: UUID) -> Flight:
        """Fetch a specific flight by ID, scoped to the authenticated user."""
        user_id = str(request.state.user.id)
        response = supabase_client.table("flights").select("*").eq("id", str(flight_id)).eq("user_id", user_id).execute()
        if not response.data:
            raise NotFoundException(f"Flight with ID {flight_id} not found")
        return Flight(**response.data[0])

    @post()
    async def create_flight(self, request: Request, supabase_client: Client, data: FlightCreate) -> Flight:
        """Create a new flight record."""
        # Use mode="json" to serialize UUIDs, dates, etc., to strings
        # and by_alias=True to use the database column names (with spaces)
        insert_data = data.model_dump(by_alias=True, mode="json")
        insert_data["user_id"] = str(request.state.user.id)
        
        response = supabase_client.table("flights").insert(insert_data).execute()
        flight_obj = Flight(**response.data[0])

        await self._sync_flight_transaction(
            user_id=str(flight_obj.user_id),
            flight_id=str(flight_obj.id),
            duration=float(flight_obj.duration),
            aircraft_id=str(flight_obj.aircraft_id) if flight_obj.aircraft_id else None,
            route=flight_obj.route,
            discount_type=flight_obj.discount_type,
            discount_amount=flight_obj.discount_amount,
            supabase_client=supabase_client
        )

        return flight_obj

    @patch("/{flight_id:uuid}")
    async def update_flight(self, request: Request, supabase_client: Client, flight_id: UUID, data: FlightUpdate) -> Flight:
        """Update a specific flight."""
        user_id = str(request.state.user.id)
        # Use mode="json" for serialization and by_alias=True for DB column names
        update_data = data.model_dump(exclude_unset=True, by_alias=True, mode="json")

        response = supabase_client.table("flights").update(update_data).eq("id", str(flight_id)).eq("user_id", user_id).execute()
        if not response.data:
            raise NotFoundException(f"Flight with ID {flight_id} not found or permission denied")
        flight_obj = Flight(**response.data[0])

        await self._sync_flight_transaction(
            user_id=str(flight_obj.user_id),
            flight_id=str(flight_obj.id),
            duration=float(flight_obj.duration),
            aircraft_id=str(flight_obj.aircraft_id) if flight_obj.aircraft_id else None,
            route=flight_obj.route,
            discount_type=flight_obj.discount_type,
            discount_amount=flight_obj.discount_amount,
            supabase_client=supabase_client
        )

        return flight_obj

    @delete("/{flight_id:uuid}")
    async def delete_flight(self, request: Request, supabase_client: Client, flight_id: UUID) -> None:
        """Delete a specific flight."""
        user_id = str(request.state.user.id)
        response = supabase_client.table("flights").delete().eq("id", str(flight_id)).eq("user_id", user_id).execute()
        if not response.data:
            raise NotFoundException(f"Flight with ID {flight_id} not found or permission denied")
