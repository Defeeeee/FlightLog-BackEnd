from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import date
from uuid import UUID

class Profile(BaseModel):
    id: UUID
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    license_type: Optional[str] = None
    cma_expiry: Optional[date] = None

    model_config = ConfigDict(from_attributes=True)

class ProfileCreate(BaseModel):
    first_name: str
    last_name: str
    license_type: Optional[str] = None
    cma_expiry: Optional[date] = None

class ProfileUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    license_type: Optional[str] = None
    cma_expiry: Optional[date] = None
