from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional
from datetime import date, datetime
from uuid import UUID

#: Mirrors the CHECK constraint on public.documents.kind.
#:
#: `repaso_vuelo` es el repaso de RAAC 61.135: 24 meses, con instructor y firmado en
#: el libro. Es una de las cuatro condiciones de 61.060(a)(1) para ejercer las
#: atribuciones de la licencia, y la única que no se puede derivar de los vuelos —
#: la norma pide una firma, y el libro digital no tiene firmas.
DOCUMENT_KINDS = (
    "cma", "licencia", "habilitacion", "seguro", "aeronavegabilidad",
    "repaso_vuelo",
    "otro",
)


class Document(BaseModel):
    id: UUID
    user_id: UUID
    kind: str = "otro"
    name: str
    expiry_date: date
    issued_date: Optional[date] = None
    notes: Optional[str] = None
    alert_days: List[int] = Field(default_factory=lambda: [60, 30, 7])
    last_alert_threshold: Optional[int] = None
    last_alert_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentCreate(BaseModel):
    kind: str = "otro"
    name: str
    expiry_date: date
    issued_date: Optional[date] = None
    notes: Optional[str] = None
    alert_days: List[int] = Field(default_factory=lambda: [60, 30, 7])


class DocumentUpdate(BaseModel):
    kind: Optional[str] = None
    name: Optional[str] = None
    expiry_date: Optional[date] = None
    issued_date: Optional[date] = None
    notes: Optional[str] = None
    alert_days: Optional[List[int]] = None


class PendingAlert(BaseModel):
    """One due alert, as handed to the frontend cron for delivery."""

    document_id: UUID
    user_id: UUID
    name: str
    kind: str
    expiry_date: date
    threshold: int
    days_remaining: int
    whatsapp_phone: Optional[str] = None
    message: str
