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
    cost_per_hour: Optional[float] = None
    # Performance de crucero. Los tres son opcionales y **sin default**: un 110
    # inventado se vería igual que uno cargado por el piloto. Null es "no lo sé", y
    # el planificador lo dice en pantalla en vez de taparlo.
    cruise_tas_kt: Optional[float] = None
    fuel_burn_lph: Optional[float] = None
    fuel_capacity_l: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)

class AircraftCreate(BaseModel):
    registration: str
    icao: str
    type: str
    type_acft: Optional[str] = None
    cost_per_hour: Optional[float] = None
    # Performance de crucero. Los tres son opcionales y **sin default**: un 110
    # inventado se vería igual que uno cargado por el piloto. Null es "no lo sé", y
    # el planificador lo dice en pantalla en vez de taparlo.
    cruise_tas_kt: Optional[float] = None
    fuel_burn_lph: Optional[float] = None
    fuel_capacity_l: Optional[float] = None

class AircraftUpdate(BaseModel):
    registration: Optional[str] = None
    icao: Optional[str] = None
    type: Optional[str] = None
    type_acft: Optional[str] = None
    cost_per_hour: Optional[float] = None
    # Performance de crucero. Los tres son opcionales y **sin default**: un 110
    # inventado se vería igual que uno cargado por el piloto. Null es "no lo sé", y
    # el planificador lo dice en pantalla en vez de taparlo.
    cruise_tas_kt: Optional[float] = None
    fuel_burn_lph: Optional[float] = None
    fuel_capacity_l: Optional[float] = None
