from datetime import date, datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

#: Mirrors the CHECK constraint on public.planned_flights.status.
PLANNED_STATUSES = ("programado", "completado", "descartado")


class PlannedFlightBase(BaseModel):
    """
    Un vuelo que el piloto planea hacer.

    Vive en su propia tabla y **nunca** se mezcla con `flights`: un plan es una
    intención y un vuelo es el registro legal de algo que ocurrió. Ver el
    comentario de `migrations/009_planned_flights.sql` para por qué esa separación
    no es estilística.

    Casi todo es opcional salvo la fecha, porque un plan a diez días vista puede ser
    "el sábado vuelo" y nada más. Lo que falte se completa al confirmarlo.
    """

    date: date
    aircraft_id: Optional[UUID] = None
    #: Mismo formato que `flights.route`: ICAO separados por espacio.
    route: Optional[str] = None
    notes: Optional[str] = None


class PlannedFlightCreate(PlannedFlightBase):
    pass


class PlannedFlightUpdate(BaseModel):
    """
    Todo opcional: el PATCH usa `exclude_unset`, así que mandar `null` es cómo se
    borra un campo y no mandarlo es cómo se lo deja como está.
    """

    date: Optional[date] = None
    aircraft_id: Optional[UUID] = None
    route: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[Literal["programado", "completado", "descartado"]] = None
    flight_id: Optional[UUID] = None
    postponed_until: Optional[date] = None


class PlannedFlight(PlannedFlightBase):
    id: UUID
    user_id: UUID
    status: str = "programado"
    #: Con qué vuelo se cerró el plan. Presente sólo cuando `status` es
    #: `completado`, y lo que hace imposible convertirlo dos veces.
    flight_id: Optional[UUID] = None
    postponed_until: Optional[date] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
