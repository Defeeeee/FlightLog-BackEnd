import datetime as dt
from typing import Any, Dict, List, Optional
from uuid import UUID

from litestar import Controller, Request, delete, get, patch, post, put
from litestar.exceptions import ClientException, NotFoundException
from supabase import Client

from src.auth.guards import auth_guard
from src.models.plan_vuelo import (
    FirmaPlanVuelo,
    PlanVuelo,
    PlanVueloCreate,
    PlanVueloResumen,
    PlanVueloUpdate,
    resumen_para_lista,
)

#: Cuántos planes trae la lista. FPL.AR muestra 30 en su plan pago; un piloto que vuela
#: tres veces por semana llega a 50 en cuatro meses.
LIMITE_LISTA = 50

COLUMNAS_LISTA = (
    "id,aircraft_id,completo,salida,destino,matricula,dof,eobt,descargado_at,created_at,updated_at"
)


class PlanesDeVueloController(Controller):
    """
    Los planes de vuelo (FPL) guardados del piloto, y su firma.

    Usa el cliente por usuario: lo que protege es el RLS de la migración 024, no un
    `eq("user_id", ...)`. El filtro igual va, para que la consulta use el índice.

    **Un plan de vuelo no es un vuelo**: nada de acá toca `flights` ni el saldo.
    """

    path = "/planes-de-vuelo"
    guards = [auth_guard]

    @get()
    async def listar(self, request: Request, supabase_client: Client) -> List[PlanVueloResumen]:
        user_id = str(request.state.user.id)
        resp = (
            supabase_client.table("planes_de_vuelo")
            .select(COLUMNAS_LISTA)
            .eq("user_id", user_id)
            .order("updated_at", desc=True)
            .limit(LIMITE_LISTA)
            .execute()
        )
        return [PlanVueloResumen(**fila) for fila in (resp.data or [])]

    @get("/{plan_id:uuid}")
    async def leer(self, request: Request, supabase_client: Client, plan_id: UUID) -> PlanVuelo:
        user_id = str(request.state.user.id)
        resp = (
            supabase_client.table("planes_de_vuelo")
            .select("*")
            .eq("id", str(plan_id))
            .eq("user_id", user_id)
            .execute()
        )
        if not resp.data:
            raise NotFoundException("Ese plan de vuelo no existe.")
        return PlanVuelo(**resp.data[0])

    @post()
    async def crear(self, request: Request, supabase_client: Client, data: PlanVueloCreate) -> PlanVuelo:
        user_id = str(request.state.user.id)
        fila: Dict[str, Any] = {
            "user_id": user_id,
            "formulario": data.formulario,
            "completo": data.completo,
            "aircraft_id": str(data.aircraft_id) if data.aircraft_id else None,
            **resumen_para_lista(data.formulario),
        }
        resp = supabase_client.table("planes_de_vuelo").insert(fila).execute()
        if not resp.data:
            raise ClientException(detail="No se pudo guardar el plan de vuelo.")
        return PlanVuelo(**resp.data[0])

    @patch("/{plan_id:uuid}")
    async def actualizar(
        self, request: Request, supabase_client: Client, plan_id: UUID, data: PlanVueloUpdate
    ) -> PlanVuelo:
        user_id = str(request.state.user.id)
        cambios: Dict[str, Any] = {}
        enviados = data.model_dump(exclude_unset=True, mode="json")
        if "formulario" in enviados and data.formulario is not None:
            cambios["formulario"] = data.formulario
            cambios.update(resumen_para_lista(data.formulario))
        if "aircraft_id" in enviados:
            cambios["aircraft_id"] = enviados["aircraft_id"]
        if data.completo is not None:
            cambios["completo"] = data.completo
        if data.descargado:
            # La hora del servidor: que no dependa del reloj del teléfono.
            cambios["descargado_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        if "demoras" in enviados and data.demoras is not None:
            cambios["demoras"] = enviados["demoras"]
        if not cambios:
            return await self.leer(request, supabase_client, plan_id)

        resp = (
            supabase_client.table("planes_de_vuelo")
            .update(cambios)
            .eq("id", str(plan_id))
            .eq("user_id", user_id)
            .execute()
        )
        if not resp.data:
            raise NotFoundException("Ese plan de vuelo no existe.")
        return PlanVuelo(**resp.data[0])

    @delete("/{plan_id:uuid}")
    async def borrar(self, request: Request, supabase_client: Client, plan_id: UUID) -> None:
        user_id = str(request.state.user.id)
        resp = (
            supabase_client.table("planes_de_vuelo")
            .delete()
            .eq("id", str(plan_id))
            .eq("user_id", user_id)
            .execute()
        )
        if not resp.data:
            raise NotFoundException("Ese plan de vuelo no existe.")

    # ------------------------------------------------------------------ firma

    @get("/firma")
    async def leer_firma(self, request: Request, supabase_client: Client) -> Optional[FirmaPlanVuelo]:
        user_id = str(request.state.user.id)
        resp = (
            supabase_client.table("firmas_plan_vuelo").select("png").eq("user_id", user_id).execute()
        )
        return FirmaPlanVuelo(png=resp.data[0]["png"]) if resp.data else None

    @put("/firma")
    async def guardar_firma(
        self, request: Request, supabase_client: Client, data: FirmaPlanVuelo
    ) -> FirmaPlanVuelo:
        user_id = str(request.state.user.id)
        resp = (
            supabase_client.table("firmas_plan_vuelo")
            .upsert(
                {"user_id": user_id, "png": data.png, "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()},
                on_conflict="user_id",
            )
            .execute()
        )
        if not resp.data:
            raise ClientException(detail="No se pudo guardar la firma.")
        return FirmaPlanVuelo(png=resp.data[0]["png"])

    @delete("/firma")
    async def borrar_firma(self, request: Request, supabase_client: Client) -> None:
        user_id = str(request.state.user.id)
        supabase_client.table("firmas_plan_vuelo").delete().eq("user_id", user_id).execute()
