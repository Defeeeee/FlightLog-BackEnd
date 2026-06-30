from litestar import Controller, get, patch, Request, post
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
        """Fetch all profiles the current user has access to. Auto-creates one if missing."""
        response = supabase_client.table("profiles").select("*").execute()
        
        if not response.data:
            # If no profile exists, create a default one for this user
            try:
                user_res = supabase_client.auth.get_user()
                if user_res.user:
                    user = user_res.user
                    # Default values for a new profile
                    new_profile = {
                        "id": str(user.id),
                        "first_name": user.user_metadata.get("first_name") or user.user_metadata.get("full_name", "Comandante").split(" ")[0],
                        "last_name": user.user_metadata.get("last_name") or " ".join(user.user_metadata.get("full_name", "").split(" ")[1:]),
                        "license_type": "-",
                        "cma_expiry": "2100-12-31" # Default far future date to signal it needs change
                    }
                    # Insert the new profile
                    supabase_client.table("profiles").insert(new_profile).execute()
                    # Re-fetch
                    response = supabase_client.table("profiles").select("*").execute()
            except Exception as e:
                print(f"Auto-profile creation failed: {str(e)}")
        
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

    @post("/apikey/regenerate")
    async def regenerate_api_key(self, request: Request, supabase_client: Client) -> Profile:
        """Regenerate the user's API key."""
        user_id = str(request.state.user.id)
        import uuid
        new_key = str(uuid.uuid4())
        response = supabase_client.table("profiles").update({"api_key": new_key}).eq("id", user_id).execute()
        if not response.data:
            raise NotFoundException("Profile not found")
        return Profile(**response.data[0])
