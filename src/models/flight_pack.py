from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime
from uuid import UUID

class FlightPack(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    total_hours: float
    created_at: datetime
    start_date: datetime
    is_active: bool
    aircraft_ids: List[UUID] = []
    remaining_hours: Optional[float] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

class FlightPackCreate(BaseModel):
    name: str
    total_hours: float
    aircraft_ids: List[UUID]
    start_date: Optional[datetime] = None
    is_active: bool = True

class FlightPackUpdate(BaseModel):
    name: Optional[str] = None
    total_hours: Optional[float] = None
    aircraft_ids: Optional[List[UUID]] = None
    start_date: Optional[datetime] = None
    is_active: Optional[bool] = None
