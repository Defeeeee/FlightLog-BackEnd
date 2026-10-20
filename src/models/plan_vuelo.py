"""
Los planes de vuelo (FPL) guardados, y la firma del piloto para el PDF.

El formulario es del frontend: ahí vive la validación de cada casilla (casillas 7 a 19
de la AIP ENR 1.10), pura y testeada. El backend guarda lo que recibe, con dos topes
para que nadie use la tabla de depósito: el tamaño del JSON y el de la firma.

**Un plan de vuelo no es un vuelo** (ver `migrations/024_planes_de_vuelo.sql`).
"""
import datetime as dt
import json
import re
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Tope del formulario serializado. Uno real anda en 2–3 KB.
MAX_FORMULARIO_BYTES = 32_000
#: Tope de la firma (data URL). Un PNG de firma anda en 10–40 KB.
MAX_FIRMA_CHARS = 250_000
#: Tope del perfil del avión para el plan.
MAX_PERFIL_AVION_BYTES = 8_000


def _tamano_json(valor: Any) -> int:
    return len(json.dumps(valor, ensure_ascii=False).encode("utf-8"))


def validar_formulario(valor: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(valor, dict):
        raise ValueError("El formulario tiene que ser un objeto.")
    if _tamano_json(valor) > MAX_FORMULARIO_BYTES:
        raise ValueError("El formulario es demasiado grande.")
    return valor


def validar_perfil_avion(valor: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if valor is None:
        return None
    if not isinstance(valor, dict):
        raise ValueError("El perfil del avión para el plan tiene que ser un objeto.")
    if _tamano_json(valor) > MAX_PERFIL_AVION_BYTES:
        raise ValueError("El perfil del avión para el plan es demasiado grande.")
    return valor


def _texto(valor: Any, largo: int) -> Optional[str]:
    if not isinstance(valor, str):
        return None
    limpio = valor.strip().upper()[:largo]
    return limpio or None


def resumen_para_lista(formulario: Dict[str, Any]) -> Dict[str, Any]:
    """
    Las columnas sueltas de la lista, sacadas del formulario: salida, destino, matrícula,
    fecha (DOF) y hora (EOBT, UTC). Lo que no tenga la forma esperada queda en NULL: la
    lista muestra "????" antes que un dato inventado.
    """

    def codigo(aerodromo: Any) -> Optional[str]:
        return _texto(aerodromo.get("codigo"), 8) if isinstance(aerodromo, dict) else None

    dof = None
    fecha = formulario.get("dofUtc")
    if isinstance(fecha, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha):
        try:
            dof = dt.date.fromisoformat(fecha).isoformat()
        except ValueError:
            dof = None

    eobt = formulario.get("eobtUtc")
    return {
        "salida": codigo(formulario.get("salida")),
        "destino": codigo(formulario.get("destino")),
        "matricula": _texto(formulario.get("matricula"), 10),
        "dof": dof,
        "eobt": eobt if isinstance(eobt, str) and re.fullmatch(r"\d{4}", eobt) else None,
    }


class Demora(BaseModel):
    """Una demora (DLA) avisada: la nueva hora y fecha de salida, en UTC."""

    eobt: str = Field(pattern=r"^\d{4}$")
    dof: dt.date
    creada: Optional[dt.datetime] = None


#: Tope de envíos por mail de un plan: es un plan, no una lista de correo.
MAX_ENVIOS = 20


class Envio(BaseModel):
    """
    Un envío por mail. `prueba` va al piloto; `aro`, a la oficina con copia al piloto.
    `tipo`: el plan (`fpl`) o un aviso de demora (`dla`); los anotados antes son del plan.
    """

    modo: Literal["prueba", "aro"]
    tipo: Literal["fpl", "dla"] = "fpl"
    a: str = Field(max_length=200)
    resend_id: Optional[str] = Field(default=None, max_length=100)
    at: Optional[dt.datetime] = None


class PlanVueloResumen(BaseModel):
    """Lo que muestra la lista: sin el formulario."""

    id: UUID
    aircraft_id: Optional[UUID] = None
    completo: bool = False
    salida: Optional[str] = None
    destino: Optional[str] = None
    matricula: Optional[str] = None
    dof: Optional[dt.date] = None
    eobt: Optional[str] = None
    descargado_at: Optional[dt.datetime] = None
    enviado_at: Optional[dt.datetime] = None
    created_at: dt.datetime
    updated_at: dt.datetime

    model_config = ConfigDict(from_attributes=True)


class PlanVuelo(PlanVueloResumen):
    formulario: Dict[str, Any]
    demoras: List[Demora] = []
    envios: List[Envio] = []


class PlanVueloCreate(BaseModel):
    formulario: Dict[str, Any]
    aircraft_id: Optional[UUID] = None
    completo: bool = False

    @field_validator("formulario")
    @classmethod
    def _formulario(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        return validar_formulario(v)


class PlanVueloUpdate(BaseModel):
    """
    Todo opcional, con `exclude_unset`. `descargado: true` anota la hora del servidor,
    para que la fecha no dependa del reloj del teléfono.
    """

    formulario: Optional[Dict[str, Any]] = None
    aircraft_id: Optional[UUID] = None
    completo: Optional[bool] = None
    descargado: Optional[bool] = None
    demoras: Optional[List[Demora]] = Field(default=None, max_length=3)
    #: Un envío que salió: se suma a la lista con la hora del servidor.
    envio: Optional[Envio] = None

    @field_validator("formulario")
    @classmethod
    def _formulario(cls, v: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        return None if v is None else validar_formulario(v)


class FirmaPlanVuelo(BaseModel):
    """La firma del piloto, como data URL de un PNG."""

    png: str = Field(max_length=MAX_FIRMA_CHARS)

    @field_validator("png")
    @classmethod
    def _png(cls, v: str) -> str:
        if not v.startswith("data:image/png;base64,"):
            raise ValueError("La firma tiene que ser un PNG.")
        return v
