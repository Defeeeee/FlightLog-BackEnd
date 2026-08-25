from typing import List

from litestar import Controller, Request, get
from litestar.exceptions import NotAuthorizedException, NotFoundException
from litestar.response import File
from supabase import Client

from src.auth.guards import auth_guard
from src.config import settings
from src.services import charts as charts_service
from src.services.charts import Carta


class ChartsController(Controller):
    """
    Cartas Jeppesen: sólo lista y descarga, y sólo para quien tiene el permiso.

    `jeppesen_access` en `profiles` decide todo acá. Hoy es un booleano que se pone
    a mano por SQL — no hay todavía flujo de pago ni niveles, y construirlos antes
    de tener un solo piloto pagando sería diseñar contra un requisito que no
    existe. Ver migración 016.
    """

    path = "/charts"
    guards = [auth_guard]

    async def _requiere_acceso(self, request: Request, supabase_client: Client) -> None:
        user_id = str(request.state.user.id)
        response = (
            supabase_client.table("profiles")
            .select("jeppesen_access")
            .eq("id", user_id)
            .execute()
        )
        tiene_acceso = bool(response.data) and bool(response.data[0].get("jeppesen_access"))
        if not tiene_acceso:
            raise NotAuthorizedException("No tenés acceso a las cartas Jeppesen.")

    @get("/{icao:str}")
    async def list_charts(
        self, request: Request, supabase_client: Client, icao: str
    ) -> List[Carta]:
        await self._requiere_acceso(request, supabase_client)
        return charts_service.listar_cartas(settings.jeppesen_charts_dir, icao)

    @get("/{icao:str}/{categoria:str}/{archivo:str}")
    async def download_chart(
        self,
        request: Request,
        supabase_client: Client,
        icao: str,
        categoria: str,
        archivo: str,
    ) -> File:
        await self._requiere_acceso(request, supabase_client)
        ruta = charts_service.resolver_carta(settings.jeppesen_charts_dir, icao, categoria, archivo)
        if ruta is None:
            raise NotFoundException("Carta no encontrada.")
        # `inline`, no `attachment`: el piloto la quiere ver, como las del AIP que
        # ya se abren en una pestaña nueva. Forzar la descarga sería peor UX sin
        # ganar nada en seguridad — el gate ya pasó.
        return File(path=ruta, filename=archivo, media_type="application/pdf", content_disposition_type="inline")
