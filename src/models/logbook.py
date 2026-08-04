from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from datetime import datetime
from uuid import UUID


class OpeningBalance(BaseModel):
    """
    Hours carried into a logbook without entering the flights one by one.

    This is NOT a single "total hours" number, and that is the whole point. A
    lone total would leave the ANAC matrix showing e.g. 500 h flown and 0 h as
    PIC, the PCA tracker reporting that no licence requirement is met, and the
    hours summary wrong on every card. The opening balance carries the same
    breakdown a flight does, so every aggregation stays truthful.
    """

    landings: int = 0

    pic_day_loc: float = 0
    pic_day_tra: float = 0
    pic_night_loc: float = 0
    pic_night_tra: float = 0
    sic_day_loc: float = 0
    sic_day_tra: float = 0
    sic_night_loc: float = 0
    sic_night_tra: float = 0

    imc_pil: float = 0
    imc_cop: float = 0
    capota: float = 0

    @property
    def total_hours(self) -> float:
        """
        Only the PIC/SIC buckets are summed.

        IMC and hood time overlap flight time instead of partitioning it — the
        same reason the log form keeps them out of the shared pool. Adding them
        here would double-count.
        """
        return (
            self.pic_day_loc + self.pic_day_tra + self.pic_night_loc + self.pic_night_tra
            + self.sic_day_loc + self.sic_day_tra + self.sic_night_loc + self.sic_night_tra
        )


class Logbook(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    description: Optional[str] = None
    is_default: bool = False
    created_at: datetime

    opening_landings: int = 0
    opening_pic_day_loc: float = 0
    opening_pic_day_tra: float = 0
    opening_pic_night_loc: float = 0
    opening_pic_night_tra: float = 0
    opening_sic_day_loc: float = 0
    opening_sic_day_tra: float = 0
    opening_sic_night_loc: float = 0
    opening_sic_night_tra: float = 0
    opening_imc_pil: float = 0
    opening_imc_cop: float = 0
    opening_capota: float = 0

    #: How many flights point at this logbook. Computed, not stored — the UI
    #: needs it to warn before a delete.
    flight_count: Optional[int] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class LogbookCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = None
    opening: Optional[OpeningBalance] = None


class LogbookUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = None
    opening: Optional[OpeningBalance] = None
