from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from uuid import UUID

class Profile(BaseModel):
    id: UUID
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    license_type: Optional[str] = None
    tracking_mode: Optional[str] = None
    api_key: Optional[UUID] = None
    whatsapp_phone: Optional[str] = None
    #: Para el encabezado de la hoja del libro de vuelo de ANAC (Res. 147/2013):
    #: el número de la licencia y el legajo que asigna Licencias al Personal.
    licencia_numero: Optional[str] = Field(default=None, max_length=30)
    legajo: Optional[str] = Field(default=None, max_length=30)
    #: Cuándo rindió la PPA (migración 022). Antes de esa fecha, sus vuelos son de alumno.
    fecha_ppa: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    #: Ver migración 016. A propósito ausente de `ProfileUpdate`: no es un campo
    #: que el piloto pueda tocar de sí mismo.
    jeppesen_access: bool = False

    model_config = ConfigDict(from_attributes=True)

class ProfileCreate(BaseModel):
    first_name: str
    last_name: str
    license_type: Optional[str] = None
    tracking_mode: Optional[str] = None
    api_key: Optional[UUID] = None
    whatsapp_phone: Optional[str] = None
    #: Para el encabezado de la hoja del libro de vuelo de ANAC (Res. 147/2013):
    #: el número de la licencia y el legajo que asigna Licencias al Personal.
    licencia_numero: Optional[str] = Field(default=None, max_length=30)
    legajo: Optional[str] = Field(default=None, max_length=30)
    #: Cuándo rindió la PPA (migración 022). Antes de esa fecha, sus vuelos son de alumno.
    fecha_ppa: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")

class ProfileUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    license_type: Optional[str] = None
    tracking_mode: Optional[str] = None
    api_key: Optional[UUID] = None
    whatsapp_phone: Optional[str] = None
    #: Para el encabezado de la hoja del libro de vuelo de ANAC (Res. 147/2013):
    #: el número de la licencia y el legajo que asigna Licencias al Personal.
    licencia_numero: Optional[str] = Field(default=None, max_length=30)
    legajo: Optional[str] = Field(default=None, max_length=30)
    #: Cuándo rindió la PPA (migración 022). Antes de esa fecha, sus vuelos son de alumno.
    fecha_ppa: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
