from litestar import Controller, get, post, patch, delete, Request
from litestar.exceptions import NotFoundException, ClientException
from supabase import Client
from typing import List, Dict, Any
from uuid import UUID

from src.models.custom_stat import CustomStat, CustomStatCreate, CustomStatUpdate
from src.auth.guards import auth_guard


class CustomStatsController(Controller):
    """
    Métricas que define el piloto.

    Sólo guarda la definición: **el cálculo pasa entero en el cliente**, que ya
    tiene los vuelos cargados para el dashboard. Eso evita recalcular en el
    servidor lo que el navegador puede hacer solo, y —más importante— deja el
    regex del piloto corriendo en su propia pestaña en lugar del proceso que
    atiende a todos.

    Usa el cliente por usuario, no el service role, así la policy de RLS es la que
    protege de verdad y no una condición `eq("user_id", ...)` que alguien pueda
    olvidar en un endpoint nuevo.
    """

    path = "/custom-stats"
    guards = [auth_guard]

    @get()
    async def list_stats(self, request: Request, supabase_client: Client) -> List[CustomStat]:
        user_id = str(request.state.user.id)
        resp = (
            supabase_client.table("custom_stats")
            .select("*")
            .eq("user_id", user_id)
            .order("position")
            .order("created_at")
            .execute()
        )
        return [CustomStat(**row) for row in (resp.data or [])]

    @post()
    async def create_stat(
        self, request: Request, supabase_client: Client, data: CustomStatCreate
    ) -> CustomStat:
        user_id = str(request.state.user.id)
        insert: Dict[str, Any] = data.model_dump(mode="json", exclude_none=True)
        insert["user_id"] = user_id

        resp = supabase_client.table("custom_stats").insert(insert).execute()
        if not resp.data:
            raise ClientException(detail="No se pudo crear la métrica.")
        return CustomStat(**resp.data[0])

    @patch("/{stat_id:uuid}")
    async def update_stat(
        self, request: Request, supabase_client: Client, stat_id: UUID, data: CustomStatUpdate
    ) -> CustomStat:
        user_id = str(request.state.user.id)

        # `exclude_unset` y no `exclude_none`: mandar null es cómo se borra un
        # filtro. Con `exclude_none` no habría forma de sacar una ventana o un
        # objetivo una vez puestos.
        update = data.model_dump(mode="json", exclude_unset=True)
        if not update:
            raise ClientException(detail="No hay cambios para aplicar.")

        resp = (
            supabase_client.table("custom_stats")
            .update(update)
            .eq("id", str(stat_id))
            .eq("user_id", user_id)
            .execute()
        )
        if not resp.data:
            raise NotFoundException(detail="Métrica no encontrada.")
        return CustomStat(**resp.data[0])

    @delete("/{stat_id:uuid}", status_code=204)
    async def delete_stat(
        self, request: Request, supabase_client: Client, stat_id: UUID
    ) -> None:
        user_id = str(request.state.user.id)
        resp = (
            supabase_client.table("custom_stats")
            .delete()
            .eq("id", str(stat_id))
            .eq("user_id", user_id)
            .execute()
        )
        if not resp.data:
            raise NotFoundException(detail="Métrica no encontrada.")
