from pydantic import BaseModel, ConfigDict
from typing import Optional, Any
from datetime import date as PyDate, datetime as PyDateTime
from uuid import UUID

class Flight(BaseModel):
    id: UUID
    user_id: UUID
    aircraft_id: Optional[UUID] = None
    date: PyDate
    route: str
    landings: int
    duration: float
    takeoff: PyDateTime
    landing: PyDateTime

    model_config = ConfigDict(from_attributes=True)

class FlightCreate(BaseModel):
    aircraft_id: Optional[UUID] = None
    date: PyDate
    route: str
    landings: int
    duration: float
    takeoff: PyDateTime
    landing: PyDateTime

class FlightUpdate(BaseModel):
    aircraft_id: Optional[UUID] = None
    # We use Any here and convert in controller to bypass "Input should be None" error
    date: Optional[Any] = None
    route: Optional[str] = None
    landings: Optional[int] = None
    duration: Optional[float] = None
    takeoff: Optional[PyDateTime] = None
    landing: Optional[PyDateTime] = None
