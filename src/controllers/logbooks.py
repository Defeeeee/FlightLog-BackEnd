from litestar import Controller, get, post, patch, delete, Request
from litestar.exceptions import NotFoundException, ClientException
from supabase import Client
from typing import List, Dict, Any
from uuid import UUID

from src.models.logbook import Logbook, LogbookCreate, LogbookUpdate, OpeningBalance
from src.auth.guards import auth_guard

#: Column names of the carried-forward balance, without the `opening_` prefix.
OPENING_FIELDS = [
    "landings",
    "pic_day_loc", "pic_day_tra", "pic_night_loc", "pic_night_tra",
    "sic_day_loc", "sic_day_tra", "sic_night_loc", "sic_night_tra",
    "imc_pil", "imc_cop", "capota",
]


def _opening_to_columns(opening: OpeningBalance | None) -> Dict[str, Any]:
    """Flattens the nested opening balance onto its `opening_*` columns."""
    if opening is None:
        return {}
    data = opening.model_dump()
    return {f"opening_{key}": data[key] for key in OPENING_FIELDS}


class LogbooksController(Controller):
    path = "/logbooks"
    guards = [auth_guard]

    @staticmethod
    def _counts_by_logbook(user_id: str, supabase_client: Client) -> Dict[str, int]:
        """
        How many flights sit in each logbook.

        One query for every logbook rather than one per logbook: the list
        endpoint is on the settings screen, and N+1 there is gratuitous.
        """
        resp = (
            supabase_client.table("flights")
            .select("logbook_id")
            .eq("user_id", user_id)
            .execute()
        )
        counts: Dict[str, int] = {}
        for row in resp.data or []:
            key = row.get("logbook_id")
            if key:
                counts[key] = counts.get(key, 0) + 1
        return counts

    @get()
    async def list_logbooks(self, request: Request, supabase_client: Client) -> List[Logbook]:
        user_id = str(request.state.user.id)
        resp = (
            supabase_client.table("logbooks")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at")
            .execute()
        )
        counts = self._counts_by_logbook(user_id, supabase_client)
        return [
            Logbook(**row, flight_count=counts.get(row["id"], 0))
            for row in (resp.data or [])
        ]

    @post()
    async def create_logbook(
        self, request: Request, supabase_client: Client, data: LogbookCreate
    ) -> Logbook:
        user_id = str(request.state.user.id)

        insert: Dict[str, Any] = {
            "user_id": user_id,
            "name": data.name,
            "description": data.description,
            **_opening_to_columns(data.opening),
        }

        # The first logbook a pilot creates becomes the default, so that the
        # flight form has something to preselect without asking.
        existing = (
            supabase_client.table("logbooks").select("id").eq("user_id", user_id).limit(1).execute()
        )
        insert["is_default"] = not bool(existing.data)

        resp = supabase_client.table("logbooks").insert(insert).execute()
        return Logbook(**resp.data[0], flight_count=0)

    @patch("/{logbook_id:uuid}")
    async def update_logbook(
        self, request: Request, supabase_client: Client, logbook_id: UUID, data: LogbookUpdate
    ) -> Logbook:
        user_id = str(request.state.user.id)

        update: Dict[str, Any] = {}
        if data.name is not None:
            update["name"] = data.name
        if data.description is not None:
            update["description"] = data.description
        update.update(_opening_to_columns(data.opening))

        if not update:
            raise ClientException(detail="No hay cambios para aplicar.")

        resp = (
            supabase_client.table("logbooks")
            .update(update)
            .eq("id", str(logbook_id))
            .eq("user_id", user_id)
            .execute()
        )
        if not resp.data:
            raise NotFoundException(detail="Libro de vuelo no encontrado.")

        counts = self._counts_by_logbook(user_id, supabase_client)
        return Logbook(**resp.data[0], flight_count=counts.get(str(logbook_id), 0))

    @delete("/{logbook_id:uuid}", status_code=200)
    async def delete_logbook(
        self, request: Request, supabase_client: Client, logbook_id: UUID
    ) -> Dict[str, Any]:
        """
        Deletes an empty logbook.

        A logbook holding flights is refused rather than cascaded. Deleting a
        book is a settings-screen action; wiping a pilot's flight history as a
        side effect of it is the most destructive thing this API could do, and
        the confirmation dialog would not be nearly loud enough to justify it.
        The client is expected to offer moving the flights first.
        """
        user_id = str(request.state.user.id)

        owned = (
            supabase_client.table("logbooks")
            .select("id")
            .eq("id", str(logbook_id))
            .eq("user_id", user_id)
            .execute()
        )
        if not owned.data:
            raise NotFoundException(detail="Libro de vuelo no encontrado.")

        in_use = (
            supabase_client.table("flights")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .eq("logbook_id", str(logbook_id))
            .limit(1)
            .execute()
        )
        if in_use.count:
            raise ClientException(
                detail=f"El libro tiene {in_use.count} vuelos. Movelos a otro libro antes de borrarlo."
            )

        supabase_client.table("logbooks").delete().eq("id", str(logbook_id)).eq(
            "user_id", user_id
        ).execute()
        return {"deleted": str(logbook_id)}
