from pydantic import BaseModel, ConfigDict
from typing import Optional
from uuid import UUID

class Aircraft(BaseModel):
    id: UUID
    user_id: UUID
    registration: str
    icao: str
    type: str
    type_acft: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class AircraftCreate(BaseModel):
    registration: str
    icao: str
    type: str
    type_acft: Optional[str] = None

class AircraftUpdate(BaseModel):
    registration: Optional[str] = None
    icao: Optional[str] = None
    type: Optional[str] = None
    type_acft: Optional[str] = None
