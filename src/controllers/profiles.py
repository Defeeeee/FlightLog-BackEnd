from litestar import Controller, get, patch, Request, post
from litestar.exceptions import InternalServerException, NotFoundException
from supabase import Client
from typing import Dict, List
from uuid import UUID
from src.models.profile import Profile, ProfileUpdate
from src.auth.guards import auth_guard


def _parse_name(metadata: Dict) -> Dict[str, str]:
    """
    Nombre y apellido a partir de la metadata del usuario.

    Misma regla que `handle_new_user()` en la migración 006, y conviene que sigan
    iguales: los dos caminos crean la misma fila. La API de Litestar manda
    `first_name`/`last_name`; Google manda `full_name`/`name`, y si el nombre
    viene en una sola palabra el apellido queda en el default en vez de repetirlo.
    """
    entero = (metadata.get("full_name") or metadata.get("name") or "").strip()
    partes = entero.split(" ", 1)

    first = (metadata.get("first_name") or "").strip() or partes[0] or "New"
    last = (metadata.get("last_name") or "").strip()
    if not last:
        last = (partes[1].strip() if len(partes) > 1 else "") or "Pilot"

    return {"first_name": first, "last_name": last}


class ProfilesController(Controller):
    path = "/profiles"
    guards = [auth_guard]

    @get()
    async def get_profiles(self, request: Request, supabase_client: Client) -> List[Profile]:
        """Fetch the authenticated user's own profile. Auto-creates one if missing."""
        user_id = str(request.state.user.id)
        response = supabase_client.table("profiles").select("*").eq("id", user_id).execute()

        if not response.data:
            # Segunda defensa: el trigger `on_auth_user_created` cubre las altas
            # nuevas, pero no repara hacia atrás. Esto cura al siguiente login.
            #
            # Estuvo muerto hasta la migración 006: `profiles` tenía RLS con
            # policies de SELECT y UPDATE pero ninguna de INSERT, así que este
            # insert lo negaba RLS, el `except` se lo tragaba en un print y el
            # piloto recibía una lista vacía. Cinco usuarios quedaron sin poder
            # usar la app. **No devolver [] en silencio de nuevo.**
            try:
                user_res = supabase_client.auth.get_user()
                if user_res.user:
                    user = user_res.user
                    supabase_client.table("profiles").insert({
                        "id": str(user.id),
                        **_parse_name(user.user_metadata or {}),
                        "license_type": "-",
                    }).execute()
                    response = supabase_client.table("profiles").select("*").eq("id", user_id).execute()
            except Exception as e:
                print(f"Auto-profile creation failed for {user_id}: {str(e)}")
                raise InternalServerException(
                    detail="No se pudo crear el perfil del piloto."
                ) from e

        if not response.data:
            raise InternalServerException(
                detail="No se pudo crear el perfil del piloto."
            )

        return [Profile(**data) for data in response.data]

    @get("/{profile_id:uuid}")
    async def get_profile(self, request: Request, supabase_client: Client, profile_id: UUID) -> Profile:
        """Fetch a specific profile by ID. Users may only access their own profile."""
        user_id = str(request.state.user.id)
        response = supabase_client.table("profiles").select("*").eq("id", str(profile_id)).eq("id", user_id).execute()
        if not response.data:
            raise NotFoundException(f"Profile with ID {profile_id} not found")
        return Profile(**response.data[0])

    @patch("/{profile_id:uuid}")
    async def update_profile(self, request: Request, supabase_client: Client, profile_id: UUID, data: ProfileUpdate) -> Profile:
        """Update a specific profile. Users may only update their own profile."""
        user_id = str(request.state.user.id)
        update_data = data.model_dump(exclude_unset=True)
        response = supabase_client.table("profiles").update(update_data).eq("id", str(profile_id)).eq("id", user_id).execute()
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
