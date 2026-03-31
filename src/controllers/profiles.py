from litestar import Controller, get, patch, Request
from litestar.exceptions import NotFoundException
from supabase import Client
from typing import List
from uuid import UUID
from src.models.profile import Profile, ProfileUpdate
from src.auth.guards import auth_guard

class ProfilesController(Controller):
    path = "/profiles"
    guards = [auth_guard]

    @get()
    async def get_profiles(self, supabase_client: Client) -> List[Profile]:
        """Fetch all profiles the current user has access to."""
        response = supabase_client.table("profiles").select("*").execute()
        return [Profile(**data) for data in response.data]

    @get("/{profile_id:uuid}")
    async def get_profile(self, supabase_client: Client, profile_id: UUID) -> Profile:
        """Fetch a specific profile by ID."""
        response = supabase_client.table("profiles").select("*").eq("id", str(profile_id)).execute()
        if not response.data:
            raise NotFoundException(f"Profile with ID {profile_id} not found")
        return Profile(**response.data[0])

    @patch("/{profile_id:uuid}")
    async def update_profile(self, supabase_client: Client, profile_id: UUID, data: ProfileUpdate) -> Profile:
        """Update a specific profile."""
        update_data = data.model_dump(exclude_unset=True)
        # Dates need to be converted to ISO format strings for Supabase JSON serialization
        if "cma_expiry" in update_data and update_data["cma_expiry"]:
            update_data["cma_expiry"] = update_data["cma_expiry"].isoformat()

        response = supabase_client.table("profiles").update(update_data).eq("id", str(profile_id)).execute()
        if not response.data:
            raise NotFoundException(f"Profile with ID {profile_id} not found or you don't have permission to update it")
        return Profile(**response.data[0])
