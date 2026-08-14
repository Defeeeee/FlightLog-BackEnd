from typing import Any, Dict, List
from uuid import UUID

from litestar import Controller, Request, delete, get, patch, post
from litestar.exceptions import ClientException, NotFoundException
from supabase import Client

from src.auth.guards import auth_guard
from src.models.planned_flight import (
    PlannedFlight,
    PlannedFlightCreate,
    PlannedFlightUpdate,
)


class PlannedFlightsController(Controller):
    """
    Vuelos que el piloto planea hacer.

    **No son vuelos.** Viven en su propia tabla justamente para que ninguna
    consulta de horas los vea nunca: sumar una intención a un libro de vuelo es
    inventar horas en un registro regulatorio. Ver el comentario de
    `migrations/009_planned_flights.sql`.

    Usa el cliente por usuario y no el service role, así la que protege de verdad
    es la policy de RLS y no un `eq("user_id", ...)` que alguien pueda olvidar en
    un endpoint nuevo — mismo criterio que `custom_stats.py`.
    """

    path = "/planned-flights"
    guards = [auth_guard]

    @get()
    async def list_planned(self, request: Request, supabase_client: Client) -> List[PlannedFlight]:
        """
        Todos los planes del piloto, del más viejo al más nuevo.

        Sin filtrar por estado ni por fecha: quien llama —el calendario, la tarjeta
        del dashboard— decide qué mostrar, y esa decisión vive en
        `src/lib/planned-flights.ts`, que es puro y por lo tanto testeable. Filtrar
        acá partiría esa lógica en dos lugares.
        """
        user_id = str(request.state.user.id)
        resp = (
            supabase_client.table("planned_flights")
            .select("*")
            .eq("user_id", user_id)
            .order("date")
            .execute()
        )
        return [PlannedFlight(**row) for row in (resp.data or [])]

    @post()
    async def create_planned(
        self, request: Request, supabase_client: Client, data: PlannedFlightCreate
    ) -> PlannedFlight:
        user_id = str(request.state.user.id)
        insert: Dict[str, Any] = data.model_dump(mode="json", exclude_none=True)
        insert["user_id"] = user_id

        resp = supabase_client.table("planned_flights").insert(insert).execute()
        if not resp.data:
            raise ClientException(detail="No se pudo crear el vuelo programado.")
        return PlannedFlight(**resp.data[0])

    @patch("/{planned_id:uuid}")
    async def update_planned(
        self,
        request: Request,
        supabase_client: Client,
        planned_id: UUID,
        data: PlannedFlightUpdate,
    ) -> PlannedFlight:
        """
        Cambia el plan, o lo cierra.

        Por acá pasan las tres salidas de la tarjeta del dashboard: completarlo
        (`status` + `flight_id`), descartarlo, y posponerlo (`postponed_until`).
        """
        user_id = str(request.state.user.id)

        # `exclude_unset` y no `exclude_none`: mandar null es cómo se limpia un
        # campo. Con `exclude_none` no habría forma de sacar una fecha de postergado
        # ni de desvincular un vuelo una vez puestos.
        update = data.model_dump(mode="json", exclude_unset=True)
        if not update:
            raise ClientException(detail="No hay cambios para aplicar.")

        resp = (
            supabase_client.table("planned_flights")
            .update(update)
            .eq("id", str(planned_id))
            .eq("user_id", user_id)
            .execute()
        )
        if not resp.data:
            raise NotFoundException(detail="Vuelo programado no encontrado.")
        return PlannedFlight(**resp.data[0])

    @delete("/{planned_id:uuid}", status_code=204)
    async def delete_planned(
        self, request: Request, supabase_client: Client, planned_id: UUID
    ) -> None:
        """
        Borra el plan de verdad.

        Distinto de descartarlo: `descartado` deja constancia de que el piloto dijo
        "no lo volé", y el calendario lo puede mostrar en gris. Esto es para el que
        se cargó por error.
        """
        user_id = str(request.state.user.id)
        resp = (
            supabase_client.table("planned_flights")
            .delete()
            .eq("id", str(planned_id))
            .eq("user_id", user_id)
            .execute()
        )
        if not resp.data:
            raise NotFoundException(detail="Vuelo programado no encontrado.")
