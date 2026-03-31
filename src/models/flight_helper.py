from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime

class FlightSessionStart(BaseModel):
    aircraft_id: UUID
    route: Optional[str] = None
    landings: Optional[int] = 0

class FlightSessionResponse(BaseModel):
    message: str
    start_time: Optional[datetime] = None
    flight_time: Optional[str] = None
    aircraft_id: Optional[UUID] = None
