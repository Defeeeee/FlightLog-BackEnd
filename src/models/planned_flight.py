import datetime as dt
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

#: Los tipos de fecha y hora se usan **calificados** (`dt.date`, `dt.time`), y no
#: importados sueltos, porque este modelo tiene un campo que se llama `date`.
#:
#: Con `from datetime import date`, la línea `date: Optional[date] = None` se rompe
#: sola: Python asigna el default antes de evaluar la anotación, así que para cuando
#: mira `Optional[date]` el nombre `date` ya vale `None` en el cuerpo de la clase y
#: el campo queda tipado `NoneType`. Pydantic entonces **rechaza cualquier fecha**.
#:
#: Y no avisa. `PlannedFlightUpdate` quedó así desde que se escribió: editar un vuelo
#: programado y posponerlo fallaban los dos con "Validation failed", sin ninguna pista
#: de cuál era el campo. Lo agarró un piloto intentando corregir un horario.
#:
#: `PlannedFlightBase` zafaba de casualidad, porque ahí `date: date` no tiene default
#: y sin asignación no hay nada que ensombrezca el nombre.

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

    date: dt.date
    aircraft_id: Optional[UUID] = None
    #: Mismo formato que `flights.route`: ICAO separados por espacio.
    route: Optional[str] = None
    notes: Optional[str] = None
    #: Horas tentativas, **en UTC** — misma convención que `flights.takeoff`.
    #: El interruptor local/UTC del frontend sólo cambia lo que se muestra.
    takeoff_time: Optional[dt.time] = None
    landing_time: Optional[dt.time] = None


class PlannedFlightCreate(PlannedFlightBase):
    pass


class PlannedFlightUpdate(BaseModel):
    """
    Todo opcional: el PATCH usa `exclude_unset`, así que mandar `null` es cómo se
    borra un campo y no mandarlo es cómo se lo deja como está.
    """

    date: Optional[dt.date] = None
    aircraft_id: Optional[UUID] = None
    route: Optional[str] = None
    notes: Optional[str] = None
    takeoff_time: Optional[dt.time] = None
    landing_time: Optional[dt.time] = None
    status: Optional[Literal["programado", "completado", "descartado"]] = None
    flight_id: Optional[UUID] = None
    postponed_until: Optional[dt.date] = None


class PlannedFlight(PlannedFlightBase):
    id: UUID
    user_id: UUID
    status: str = "programado"
    #: Con qué vuelo se cerró el plan. Presente sólo cuando `status` es
    #: `completado`, y lo que hace imposible convertirlo dos veces.
    flight_id: Optional[UUID] = None
    postponed_until: Optional[dt.date] = None
    created_at: dt.datetime
    updated_at: dt.datetime

    model_config = ConfigDict(from_attributes=True)
