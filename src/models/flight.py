from pydantic import BaseModel, ConfigDict, Field
from typing import Literal, Optional, Any
from datetime import date, datetime
from uuid import UUID

class Flight(BaseModel):
    id: UUID
    user_id: UUID
    logbook_id: Optional[UUID] = None
    aircraft_id: Optional[UUID] = None
    date: date
    route: str
    landings: int
    duration: float
    takeoff: datetime
    landing: datetime
    
    # New logging columns
    pic_day_loc: Optional[float] = None
    pic_day_tra: Optional[float] = None
    pic_night_loc: Optional[float] = None
    pic_night_tra: Optional[float] = None
    sic_day_loc: Optional[float] = None
    sic_day_tra: Optional[float] = None
    sic_night_loc: Optional[float] = None
    sic_night_tra: Optional[float] = None
    
    # Handling columns with spaces
    imc_pil: Optional[float] = Field(default=None, alias="IMC Pil")
    imc_cop: Optional[float] = Field(default=None, alias="IMC Cop")
    capota: Optional[float] = Field(default=None, alias="Capota")
    sim_instructor: Optional[float] = Field(default=None, alias="Sim Instructor")
    sim_pil_en_inst: Optional[float] = Field(default=None, alias="Sim Pil en Inst")
    
    # Discount columns
    discount_type: Optional[str] = None
    discount_amount: Optional[float] = None
    purpose: str = "VP"
    #: Free-text note, as the paper ANAC logbook's observations column.
    remarks: Optional[str] = None
    #: Este vuelo es el último renglón de su hoja en el libro de papel: lo que queda en
    #: blanco se tacha (migración 020). Lo usa el PDF del libro.
    cierra_hoja: bool = False
    #: El id del vuelo en el CAD de ANAC y cuándo se anotó (migración 029).
    cad_vuelo_id: Optional[int] = None
    cad_cargado_at: Optional[datetime] = None
    #: Traído del CAD a Vector (migración 030): no genera cobro.
    traido_del_cad: bool = False
    #: Por qué no se pasa al CAD (migración 031): "foliado" o "ignorado". None: pendiente.
    cad_omitido: Optional[str] = None
    #: Quién certifica el vuelo en el CAD (migración 032): id de la lista del CAD y nombre.
    cad_autoridad_id: Optional[int] = None
    cad_autoridad_nombre: Optional[str] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

class FlightCreate(BaseModel):
    #: Optional: when omitted the backend files the flight in the pilot's
    #: default logbook, so a client that knows nothing about logbooks keeps
    #: working unchanged.
    logbook_id: Optional[UUID] = None
    aircraft_id: Optional[UUID] = None
    date: date
    route: str
    landings: int
    duration: float
    takeoff: datetime
    landing: datetime
    
    # New logging columns for creation
    pic_day_loc: Optional[float] = None
    pic_day_tra: Optional[float] = None
    pic_night_loc: Optional[float] = None
    pic_night_tra: Optional[float] = None
    sic_day_loc: Optional[float] = None
    sic_day_tra: Optional[float] = None
    sic_night_loc: Optional[float] = None
    sic_night_tra: Optional[float] = None
    
    imc_pil: Optional[float] = Field(default=None, alias="IMC Pil")
    imc_cop: Optional[float] = Field(default=None, alias="IMC Cop")
    capota: Optional[float] = Field(default=None, alias="Capota")
    sim_instructor: Optional[float] = Field(default=None, alias="Sim Instructor")
    sim_pil_en_inst: Optional[float] = Field(default=None, alias="Sim Pil en Inst")
    
    discount_type: Optional[str] = None
    discount_amount: Optional[float] = None
    purpose: str = "VP"
    remarks: Optional[str] = None
    cierra_hoja: bool = False
    #: Traído del CAD de ANAC (migración 030): ya está allá, con este id, y no genera cobro.
    cad_vuelo_id: Optional[int] = Field(default=None, ge=1)
    traido_del_cad: bool = False
    #: Quién certifica el vuelo en el CAD (migración 032). Opcional.
    cad_autoridad_id: Optional[int] = Field(default=None, ge=1, le=999)
    cad_autoridad_nombre: Optional[str] = Field(default=None, max_length=120)
    
    model_config = ConfigDict(populate_by_name=True)

class FlightUpdate(BaseModel):
    aircraft_id: Optional[UUID] = None
    # Use Any to maintain compatibility with remote's fix
    date: Optional[Any] = None
    route: Optional[str] = None
    landings: Optional[int] = None
    duration: Optional[float] = None
    takeoff: Optional[datetime] = None
    landing: Optional[datetime] = None
    
    # New logging columns for updates
    pic_day_loc: Optional[float] = None
    pic_day_tra: Optional[float] = None
    pic_night_loc: Optional[float] = None
    pic_night_tra: Optional[float] = None
    sic_day_loc: Optional[float] = None
    sic_day_tra: Optional[float] = None
    sic_night_loc: Optional[float] = None
    sic_night_tra: Optional[float] = None
    
    imc_pil: Optional[float] = Field(default=None, alias="IMC Pil")
    imc_cop: Optional[float] = Field(default=None, alias="IMC Cop")
    capota: Optional[float] = Field(default=None, alias="Capota")
    sim_instructor: Optional[float] = Field(default=None, alias="Sim Instructor")
    sim_pil_en_inst: Optional[float] = Field(default=None, alias="Sim Pil en Inst")
    
    discount_type: Optional[str] = None
    discount_amount: Optional[float] = None
    purpose: Optional[str] = None
    cierra_hoja: Optional[bool] = None
    #: El id del vuelo en el CAD de ANAC (migración 029). La hora la pone el servidor.
    cad_vuelo_id: Optional[int] = Field(default=None, ge=1)
    #: Por qué no se pasa al CAD (migración 031). Mandar null lo devuelve a la lista.
    cad_omitido: Optional[Literal["foliado", "ignorado"]] = None
    #: Quién certifica el vuelo en el CAD (migración 032). Null lo borra.
    cad_autoridad_id: Optional[int] = Field(default=None, ge=1, le=999)
    cad_autoridad_nombre: Optional[str] = Field(default=None, max_length=120)

    model_config = ConfigDict(populate_by_name=True)
