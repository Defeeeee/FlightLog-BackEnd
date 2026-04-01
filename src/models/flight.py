from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import date, datetime
from uuid import UUID

class Flight(BaseModel):
    id: UUID
    user_id: UUID
    aircraft_id: Optional[UUID] = None
    date: date
    route: str
    landings: int
    duration: float
    takeoff: datetime
    landing: datetime

    model_config = ConfigDict(from_attributes=True)

class FlightCreate(BaseModel):
    aircraft_id: Optional[UUID] = None
    date: date
    route: str
    landings: int
    duration: float
    takeoff: datetime
    landing: datetime

class FlightUpdate(BaseModel):
    aircraft_id: Optional[UUID] = None
    date: Optional[date] = None
    route: Optional[str] = None
    landings: Optional[int] = None
    duration: Optional[float] = None
    takeoff: Optional[datetime] = None
    landing: Optional[datetime] = None
