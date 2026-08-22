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
    #: `true` = dispositivo de entrenamiento, no aeronave.
    #:
    #: El piloto anota el simulador en el libro como cualquier vuelo —fecha, horarios,
    #: el equipo— y las horas van a la columna de instrucción terrestre. Esta marca es
    #: lo que le permite al tracker de 61.620 **no** sumar esas horas a la experiencia
    #: total: las 200 h son horas de vuelo, y una sesión de simulador no lo es.
    #:
    #: Va en la aeronave y no en el vuelo porque así no se puede olvidar: se carga una
    #: vez al dar de alta el equipo y cada fila que lo use queda marcada sola.
    is_simulator: bool = False

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
    #: `true` = dispositivo de entrenamiento, no aeronave.
    #:
    #: El piloto anota el simulador en el libro como cualquier vuelo —fecha, horarios,
    #: el equipo— y las horas van a la columna de instrucción terrestre. Esta marca es
    #: lo que le permite al tracker de 61.620 **no** sumar esas horas a la experiencia
    #: total: las 200 h son horas de vuelo, y una sesión de simulador no lo es.
    #:
    #: Va en la aeronave y no en el vuelo porque así no se puede olvidar: se carga una
    #: vez al dar de alta el equipo y cada fila que lo use queda marcada sola.
    is_simulator: bool = False

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
    is_simulator: Optional[bool] = None
