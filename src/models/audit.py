from pydantic import BaseModel, ConfigDict
from typing import Dict, Optional
from datetime import datetime
from uuid import UUID


class AuditFinding(BaseModel):
    id: UUID
    user_id: UUID
    flight_id: Optional[UUID] = None
    rule_type: str
    severity: str
    message: str
    suppressed: bool = False
    suppressed_reason: Optional[str] = None
    created_at: datetime
    recalculated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SuppressRequest(BaseModel):
    """Body of the suppress endpoint. `suppressed=False` un-suppresses."""

    suppressed: bool = True
    reason: Optional[str] = None


class AuditSummary(BaseModel):
    critical: int = 0
    warning: int = 0
    suppressed: int = 0
    """Open (unsuppressed) findings — what the nav badge counts."""
    open_total: int = 0
    by_rule: Dict[str, int] = {}
    last_recalculated_at: Optional[datetime] = None
