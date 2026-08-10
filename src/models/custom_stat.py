from pydantic import BaseModel, ConfigDict, Field
from typing import Literal, Optional
from datetime import datetime
from uuid import UUID

#: Mirrors the CHECK constraints on public.custom_stats.
STAT_METRICS = ("horas", "aterrizajes", "vuelos")
REGEX_FIELDS = ("route", "purpose", "remarks")

#: Same cap the frontend enforces. Declared in both places on purpose: the base
#: must not accept what the UI rejects, or a stat saved elsewhere would come back
#: and hang the pilot's tab.
MAX_PATTERN_LENGTH = 200


class CustomStatBase(BaseModel):
    """
    A metric the pilot defines.

    Filters are plain columns instead of a jsonb blob: the set is small and closed,
    and a column can be indexed, checked and read from SQL. A jsonb here would buy
    flexibility nobody asked for at the cost of all three.
    """

    name: str
    metric: Literal["horas", "aterrizajes", "vuelos"]

    aircraft_id: Optional[UUID] = None
    clase: Optional[str] = None
    purpose: Optional[str] = None
    airport: Optional[str] = None
    window_days: Optional[int] = Field(default=None, gt=0)

    #: No target means it is a counter rather than a progress bar.
    target: Optional[float] = Field(default=None, gt=0)

    regex_field: Optional[Literal["route", "purpose", "remarks"]] = None
    regex_pattern: Optional[str] = Field(default=None, max_length=MAX_PATTERN_LENGTH)

    position: int = 0


class CustomStatCreate(CustomStatBase):
    pass


class CustomStatUpdate(BaseModel):
    name: Optional[str] = None
    metric: Optional[Literal["horas", "aterrizajes", "vuelos"]] = None
    aircraft_id: Optional[UUID] = None
    clase: Optional[str] = None
    purpose: Optional[str] = None
    airport: Optional[str] = None
    window_days: Optional[int] = Field(default=None, gt=0)
    target: Optional[float] = Field(default=None, gt=0)
    regex_field: Optional[Literal["route", "purpose", "remarks"]] = None
    regex_pattern: Optional[str] = Field(default=None, max_length=MAX_PATTERN_LENGTH)
    position: Optional[int] = None


class CustomStat(CustomStatBase):
    id: UUID
    user_id: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
