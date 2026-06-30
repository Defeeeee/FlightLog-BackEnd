from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime
from uuid import UUID

class Transaction(BaseModel):
    id: UUID
    user_id: UUID
    flight_id: Optional[UUID] = None
    amount: float
    type: str
    description: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class TransactionCreate(BaseModel):
    amount: float
    type: str
    description: Optional[str] = None
    flight_id: Optional[UUID] = None
