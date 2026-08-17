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


#: Qué pasa cuando el documento vence. Mirrors the CHECK on documents.blocking.
#:
#: El semáforo de RAAC 61.060(a)(1) tiene cuatro condiciones fijas, pero un piloto
#: de escuela vive con exigencias que la norma no enumera —cuota del aeroclub,
#: autorización del instructor, curso interno—. Esto deja que cualquier documento
#: declare si condiciona el vuelo, sin que Vector tenga que conocer cada caso.
#:
#: De menos a más restrictivo: 'pasajeros' deja volar solo; 'solo' obliga a volar
#: con instructor —la misma semántica que el repaso de 61.135, y ese vuelo es el
#: que lo renueva—; 'vuelo' no deja volar.
BLOCKING_LEVELS = ("nada", "pasajeros", "solo", "vuelo")

#: Quién escribe `documents.expiry_date`. Mirrors the CHECK on documents.expiry_rule.
#:
#: 'fijo' es lo de siempre: el piloto escribe la fecha. Las otras dos las calcula el
#: backend sumando `expiry_offset_days` (en `expiry_offset_unit`) a la fecha de un
#: vuelo, y las recalcula cada vez que los vuelos del piloto cambian:
#:
#:   - 'ultimo_vuelo' cuenta desde el vuelo más reciente, así que la fecha se corre
#:     con cada vuelo nuevo. Es "60 días sin volar y necesitás adaptación", el
#:     requisito que escrito a mano está mal al día siguiente.
#:   - 'vuelo_ancla' cuenta desde el vuelo que señala `expiry_anchor_flight_id`. La
#:     fecha no se mueve salvo que se corrija la de ese vuelo. Es "24 meses desde
#:     aquel repaso", y lo que gana sobre escribir la fecha a mano es que queda
#:     registrado de dónde salió y que sigue las correcciones del vuelo.
#:
#: Ver `src/services/derived_expiries.py`.
EXPIRY_RULES = ("fijo", "ultimo_vuelo", "vuelo_ancla")

#: Reglas cuya fecha escribe el backend. `'fijo'` es la única que escribe el piloto.
DERIVED_EXPIRY_RULES = ("ultimo_vuelo", "vuelo_ancla")

#: En qué unidad se cuenta `expiry_offset_days`. Los meses saturan al último día del
#: mes destino — ver `derived_expiries.sumar_offset`.
EXPIRY_OFFSET_UNITS = ("dias", "meses")

#: Topes del offset por unidad, espejo del CHECK. No son regulatorios: son
#: guardarraíles contra un dedo de más en el formulario, los dos del orden de 10 años.
MAX_EXPIRY_OFFSET = {"dias": 3650, "meses": 120}

#: Compatibilidad: quedó de cuando la unidad no existía.
MAX_EXPIRY_OFFSET_DAYS = MAX_EXPIRY_OFFSET["dias"]



class Document(BaseModel):
    id: UUID
    user_id: UUID
    kind: str = "otro"
    blocking: str = "nada"
    name: str
    # Nullable: no todo documento caduca. Una licencia puede ser de por vida, y
    # sin fecha significa "no vence" — nunca vencido, nunca un aviso.
    expiry_date: Optional[date] = None
    # Con 'ultimo_vuelo', `expiry_date` de arriba es una caché que escribe el
    # backend: la fuente es esta regla más el offset. Ver EXPIRY_RULES.
    expiry_rule: str = "fijo"
    expiry_offset_days: Optional[int] = None
    expiry_offset_unit: str = "dias"
    #: Vuelo desde el que se cuenta, con `expiry_rule = 'vuelo_ancla'`. Referencia
    #: blanda: sin FK, para que borrar un vuelo nunca falle. Ver migración 013.
    expiry_anchor_flight_id: Optional[UUID] = None
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
    blocking: str = "nada"
    name: str
    expiry_date: Optional[date] = None
    expiry_rule: str = "fijo"
    expiry_offset_days: Optional[int] = None
    expiry_offset_unit: str = "dias"
    #: Vuelo desde el que se cuenta, con `expiry_rule = 'vuelo_ancla'`. Referencia
    #: blanda: sin FK, para que borrar un vuelo nunca falle. Ver migración 013.
    expiry_anchor_flight_id: Optional[UUID] = None
    issued_date: Optional[date] = None
    notes: Optional[str] = None
    alert_days: List[int] = Field(default_factory=lambda: [60, 30, 7])


class DocumentUpdate(BaseModel):
    kind: Optional[str] = None
    blocking: Optional[str] = None
    name: Optional[str] = None
    expiry_date: Optional[date] = None
    expiry_rule: Optional[str] = None
    expiry_offset_days: Optional[int] = None
    expiry_offset_unit: Optional[str] = None
    expiry_anchor_flight_id: Optional[UUID] = None
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
    # El nombre de pila va suelto además de embebido en `message`: la plantilla de
    # WhatsApp lo recibe como parámetro propio. Un envío proactivo tiene que ser
    # por plantilla —Meta no permite texto libre fuera de la ventana de 24 h— y
    # una plantilla recibe variables, no una frase ya armada.
    first_name: Optional[str] = None
    message: str
