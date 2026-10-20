from pydantic import BaseModel, ConfigDict, Field, model_validator
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


class AperturaPPA(BaseModel):
    """
    Las horas de antes de un alumno piloto, con el desglose de RAAC 61.520(a) (migración
    028). El alumno no lleva libro: sus horas se cuentan contra la PPA, y eso no entra en
    las columnas `opening_*`, que son las del libro de papel.

    Topes holgados (un alumno no trae mil horas) para que un error de tipeo no quede como
    dato.
    """

    doble_mando: float = Field(default=0, ge=0, le=300)
    #: Vuelo solo, de día (61.520(a)(1)(ii)).
    solo: float = Field(default=0, ge=0, le=300)
    #: De las de vuelo solo, cuántas de travesía.
    solo_travesia: float = Field(default=0, ge=0, le=300)
    #: De las de doble mando, cuántas de noche (61.520(a)(1)(v)).
    instruccion_nocturna: float = Field(default=0, ge=0, le=300)
    aterrizajes_nocturnos: int = Field(default=0, ge=0, le=500)
    #: Ya hizo la travesía de 150 NM con dos aterrizajes (61.520(a)(1)(iii)).
    travesia_larga: bool = False

    @model_validator(mode="after")
    def _partes(self) -> "AperturaPPA":
        if self.solo_travesia > self.solo:
            raise ValueError("Las horas de solo de travesía no pueden ser más que las de vuelo solo.")
        if self.instruccion_nocturna > self.doble_mando:
            raise ValueError("Las horas de instrucción nocturna no pueden ser más que las de doble mando.")
        return self


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

    #: Renglones por hoja del libro de papel, para cortar el PDF donde corta el libro
    #: (migración 020). La hoja del Adjunto A de la Res. ANAC 147/2013 tiene 15.
    renglones_por_hoja: int = 15

    #: Las horas de antes de un alumno, con el desglose de la PPA (migración 028).
    apertura_ppa: Optional[AperturaPPA] = None

    #: How many flights point at this logbook. Computed, not stored — the UI
    #: needs it to warn before a delete.
    flight_count: Optional[int] = None

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class LogbookCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: Optional[str] = None
    opening: Optional[OpeningBalance] = None
    renglones_por_hoja: Optional[int] = Field(default=None, ge=5, le=40)
    apertura_ppa: Optional[AperturaPPA] = None


class LogbookUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = None
    opening: Optional[OpeningBalance] = None
    renglones_por_hoja: Optional[int] = Field(default=None, ge=5, le=40)
    apertura_ppa: Optional[AperturaPPA] = None
