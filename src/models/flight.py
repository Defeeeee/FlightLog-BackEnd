from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Any
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

    model_config = ConfigDict(populate_by_name=True)
