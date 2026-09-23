from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator

from src.services.social import validar_handle

Visibilidad = Literal["publico", "privado"]
#: `bloqueado` es "vos lo bloqueaste". El que fue bloqueado nunca lo ve: para él, el
#: perfil de quien lo bloqueó no existe (404).
Relacion = Literal["anonimo", "propio", "siguiendo", "pendiente", "ninguna", "bloqueado"]


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
    avatar_url: Optional[str] = None
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
    avatar_url: Optional[str] = None


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
    avatar_url: Optional[str] = None


class ResumenSocial(BaseModel):
    """
    Para el layout: si el piloto tiene @, su foto, y el punto rojo de Pilotos —las
    solicitudes que esperan respuesta más lo nuevo en su Actividad—.
    """

    handle: Optional[str] = None
    avatar_url: Optional[str] = None
    solicitudes_pendientes: int = 0
    actividad_nueva: int = 0


class EstadoSeguimiento(BaseModel):
    relacion: Relacion


# ---------------------------------------------------------------------------
# Publicaciones
# ---------------------------------------------------------------------------

class AutorOut(BaseModel):
    """Quién publicó o comentó. Lo mismo que se ve de su @, nada más."""

    handle: str
    nombre_visible: str
    licencia: Optional[str] = None
    avatar_url: Optional[str] = None


class FotoOut(BaseModel):
    """`url` es firmada y vence (6 h): no se guarda, se pide de nuevo."""

    url: str
    ancho: int
    alto: int


class VueloChip(BaseModel):
    """Lo que el piloto eligió mostrar de un vuelo. Nunca la matrícula."""

    ruta: Optional[str] = None
    duracion: Optional[float] = None
    aeronave: Optional[str] = None
    fecha: Optional[str] = None


class PublicacionOut(BaseModel):
    id: UUID
    autor: AutorOut
    texto: Optional[str] = None
    vuelo: Optional[VueloChip] = None
    fotos: List[FotoOut] = []
    aplausos: int = 0
    aplaudida: bool = False
    comentarios: int = 0
    es_mia: bool = False
    #: Sólo para el autor: de qué vuelo salió. A nadie más se le devuelve.
    vuelo_id: Optional[UUID] = None
    created_at: datetime


class PaginaPublicaciones(BaseModel):
    """`siguiente` es el cursor de la próxima página, o `None` si no hay más."""

    publicaciones: List[PublicacionOut]
    siguiente: Optional[str] = None


class ComentarioIn(BaseModel):
    texto: str


class ComentarioOut(BaseModel):
    id: UUID
    autor: AutorOut
    texto: str
    created_at: datetime
    #: Su autor, o el de la publicación.
    puede_borrar: bool = False


class EstadoAplauso(BaseModel):
    aplausos: int
    aplaudida: bool


class AvatarOut(BaseModel):
    avatar_url: Optional[str] = None


TipoEvento = Literal["seguidor", "solicitud", "aplauso", "comentario"]


class EventoActividad(BaseModel):
    tipo: TipoEvento
    piloto: AutorOut
    created_at: datetime
    nuevo: bool = False
    #: Para un comentario, su texto; para un aplauso, el comienzo de la publicación.
    texto: Optional[str] = None


class Actividad(BaseModel):
    eventos: List[EventoActividad]


class MiComentario(BaseModel):
    """Un comentario propio, para la exportación: sin el autor, que sos vos."""

    id: UUID
    publicacion_id: UUID
    texto: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Cuidar la red: reportes y avisos push
# ---------------------------------------------------------------------------

TipoReporte = Literal["perfil", "publicacion", "comentario"]


class ReporteIn(BaseModel):
    """
    Qué se reporta y por qué. `objetivo` es el @ de un perfil o el id de una
    publicación o comentario: nunca un user_id.
    """

    tipo: TipoReporte
    objetivo: str
    motivo: str

    @field_validator("objetivo")
    @classmethod
    def _objetivo(cls, valor: str) -> str:
        limpio = (valor or "").strip()
        if not limpio or len(limpio) > 100:
            raise ValueError("No sabemos qué querés reportar.")
        return limpio

    @field_validator("motivo")
    @classmethod
    def _motivo(cls, valor: str) -> str:
        limpio = (valor or "").strip()
        if not limpio:
            raise ValueError("Contanos el motivo del reporte.")
        if len(limpio) > 500:
            raise ValueError("El motivo puede tener como mucho 500 caracteres.")
        return limpio


class ClavesPush(BaseModel):
    p256dh: str
    auth: str


class SuscripcionPushIn(BaseModel):
    """Lo que devuelve `PushManager.subscribe()` en el navegador, tal cual."""

    endpoint: str
    keys: ClavesPush

    @field_validator("endpoint")
    @classmethod
    def _endpoint(cls, valor: str) -> str:
        if not valor.startswith("https://") or len(valor) > 1000:
            raise ValueError("Suscripción inválida.")
        return valor


class BajaPushIn(BaseModel):
    endpoint: str


class ClavePush(BaseModel):
    """La clave pública VAPID, o `None` si los avisos no están configurados."""

    clave: Optional[str] = None

