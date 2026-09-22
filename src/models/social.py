from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, field_validator

from src.services.social import validar_handle

Visibilidad = Literal["publico", "privado"]
Relacion = Literal["anonimo", "propio", "siguiendo", "pendiente", "ninguna"]


def _texto_opcional(valor: Optional[str]) -> Optional[str]:
    """Vacío es "no lo cargó", no un string en blanco guardado para siempre."""
    if valor is None:
        return None
    limpio = valor.strip()
    return limpio or None


class PerfilPublicoIn(BaseModel):
    """
    Lo que el piloto publica al crear o editar su @.

    **Ningún `user_id` entra ni sale por acá.** Es interno: el dueño es siempre el de
    la sesión, y hacia afuera un piloto se identifica por su @.
    """

    handle: str
    nombre_visible: str
    licencia: Optional[str] = None
    bio: Optional[str] = None
    visibilidad: Visibilidad = "publico"

    @field_validator("handle")
    @classmethod
    def _handle(cls, valor: str) -> str:
        # `HandleInvalido` es un `ValueError`: Litestar lo devuelve como 400 con el
        # mensaje, que es lo que el formulario muestra.
        return validar_handle(valor)

    @field_validator("nombre_visible")
    @classmethod
    def _nombre(cls, valor: str) -> str:
        limpio = (valor or "").strip()
        if not limpio:
            raise ValueError("Poné el nombre con el que querés aparecer.")
        if len(limpio) > 60:
            raise ValueError("El nombre puede tener como mucho 60 caracteres.")
        return limpio

    @field_validator("licencia")
    @classmethod
    def _licencia(cls, valor: Optional[str]) -> Optional[str]:
        limpio = _texto_opcional(valor)
        if limpio and len(limpio) > 20:
            raise ValueError("La licencia puede tener como mucho 20 caracteres.")
        return limpio

    @field_validator("bio")
    @classmethod
    def _bio(cls, valor: Optional[str]) -> Optional[str]:
        limpio = _texto_opcional(valor)
        if limpio and len(limpio) > 160:
            raise ValueError("La bio puede tener como mucho 160 caracteres.")
        return limpio


class PerfilPublicoOut(BaseModel):
    handle: str
    nombre_visible: str
    licencia: Optional[str] = None
    bio: Optional[str] = None
    visibilidad: Visibilidad
    created_at: Optional[datetime] = None


class MiPerfilPublico(BaseModel):
    """`perfil` es `None` si el piloto todavía no creó su @. No es un error."""

    perfil: Optional[PerfilPublicoOut] = None


class HorasPublicas(BaseModel):
    total: float
    pic: float
    travesia: float
    noche: float
    instrumentos: float


class PilotoResumen(BaseModel):
    """Una fila de búsqueda o de lista. Sin horas: para eso está el perfil."""

    handle: str
    nombre_visible: str
    licencia: Optional[str] = None
    visibilidad: Visibilidad
    relacion: Relacion


class PilotoPublico(BaseModel):
    """
    El perfil de `/u/{handle}`.

    `horas` es `None` cuando el que mira no puede verlas —privado y sin seguir—, y eso
    es distinto de "cero horas". El frontend dice "Perfil privado", no "0.0".
    """

    handle: str
    nombre_visible: str
    licencia: Optional[str] = None
    bio: Optional[str] = None
    visibilidad: Visibilidad
    seguidores: int
    siguiendo: int
    relacion: Relacion
    horas: Optional[HorasPublicas] = None


class ResumenSocial(BaseModel):
    """Para el layout: si el piloto tiene @ y cuántas solicitudes lo esperan."""

    handle: Optional[str] = None
    solicitudes_pendientes: int = 0


class EstadoSeguimiento(BaseModel):
    relacion: Relacion
