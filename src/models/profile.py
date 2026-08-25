from pydantic import BaseModel, ConfigDict
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

class ProfileUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    license_type: Optional[str] = None
    tracking_mode: Optional[str] = None
    api_key: Optional[UUID] = None
    whatsapp_phone: Optional[str] = None
