"""
La red social: qué es un @ válido, quién puede ver las horas de quién, y cuáles son
esas horas.

Todo puro, sin base ni server, para poder testearlo offline (`test_social.py`). Los
controladores de `src/controllers/social.py` sólo consultan y deciden con esto.

**Las horas públicas son las mismas que el piloto ve en su Resumen.** Las reglas
salen de `headlineStats`, `openingTotals` y `soloVolados` del frontend
(`src/lib/summary.ts` y `src/lib/simulador.ts`): los simuladores no cuentan, y las
horas de apertura de los libros sí. Si un perfil público mostrara un total distinto
del de la pantalla del propio piloto, ninguno de los dos números se creería.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

# ---------------------------------------------------------------------------
# El @
# ---------------------------------------------------------------------------

#: El mismo formato que el CHECK de la migración 018. Acá además da mensajes que un
#: piloto entiende, que el CHECK no puede.
_FORMATO = re.compile(r"^[a-z0-9][a-z0-9._]{1,18}[a-z0-9]$")

#: Los que no puede tener nadie. O suenan a la app o a la autoridad —un "@anac" o un
#: "@soporte" en manos de cualquiera es una suplantación esperando pasar—, o son
#: segmentos de ruta. El frontend tiene la misma lista en `src/lib/handle.ts` para
#: avisar mientras se tipea; la que decide es ésta.
RESERVADOS = frozenset({
    "vector", "vectorapp", "admin", "administrador", "root", "soporte", "ayuda",
    "help", "staff", "equipo", "oficial", "anac", "api", "app", "u", "dashboard",
    "login", "register", "registro", "pilotos", "piloto", "perfil", "settings",
    "hangar", "null", "undefined", "www", "mail", "legal",
    # Las pantallas que cuelgan de `/dashboard/pilotos/`: un @ con ese nombre quedaría
    # tapado por la ruta fija y su perfil no se podría abrir.
    "buscar", "actividad", "publicar", "red", "solicitudes",
})


class HandleInvalido(ValueError):
    """El mensaje es para el piloto: se muestra tal cual al lado del campo."""


def normalizar_handle(crudo: Optional[str]) -> str:
    """Sin espacios, sin la arroba de adelante y en minúsculas."""
    return (crudo or "").strip().lstrip("@").lower()


def validar_handle(crudo: Optional[str]) -> str:
    """El @ normalizado, o `HandleInvalido` con el motivo."""
    h = normalizar_handle(crudo)
    if len(h) < 3:
        raise HandleInvalido("El @ tiene que tener al menos 3 caracteres.")
    if len(h) > 20:
        raise HandleInvalido("El @ puede tener como mucho 20 caracteres.")
    if not re.fullmatch(r"[a-z0-9._]+", h):
        raise HandleInvalido("Usá sólo letras sin acento, números, punto o guion bajo.")
    if not _FORMATO.fullmatch(h):
        raise HandleInvalido("Tiene que empezar y terminar con una letra o un número.")
    if ".." in h:
        raise HandleInvalido("No puede tener dos puntos seguidos.")
    if h in RESERVADOS:
        raise HandleInvalido("Ese @ está reservado.")
    return h


# ---------------------------------------------------------------------------
# Quién ve qué
# ---------------------------------------------------------------------------

#: Qué es el que mira respecto del perfil. `anonimo` es alguien sin sesión, el caso del
#: link compartido por WhatsApp.
RELACIONES = ("anonimo", "propio", "siguiendo", "pendiente", "ninguna")


def relacion_con(viewer_id: Optional[str], perfil_id: str, estado_seguimiento: Optional[str]) -> str:
    """
    La relación a partir del seguimiento del que mira hacia el perfil, si existe.

    Una solicitud `pendiente` **no** es seguir: hasta que el dueño la acepta, quien la
    mandó ve lo mismo que cualquier otro.
    """
    if not viewer_id:
        return "anonimo"
    if viewer_id == perfil_id:
        return "propio"
    if estado_seguimiento == "aceptado":
        return "siguiendo"
    if estado_seguimiento == "pendiente":
        return "pendiente"
    return "ninguna"


def puede_ver_horas(visibilidad: str, relacion: str) -> bool:
    """
    El dueño y sus seguidores aceptados, siempre. El resto, sólo si es público. Nunca a
    quien bloqueé: de un bloqueo, ninguno de los dos ve lo del otro.

    Cualquier `visibilidad` que no sea exactamente 'publico' cuenta como privada: ante
    un valor raro, esconder es el lado correcto del error.
    """
    if relacion == "bloqueado":
        return False
    if relacion in ("propio", "siguiendo"):
        return True
    return visibilidad == "publico"


# ---------------------------------------------------------------------------
# Las horas
# ---------------------------------------------------------------------------

_PIC = ("pic_day_loc", "pic_day_tra", "pic_night_loc", "pic_night_tra")
_SIC = ("sic_day_loc", "sic_day_tra", "sic_night_loc", "sic_night_tra")
_TRAVESIA = ("pic_day_tra", "pic_night_tra", "sic_day_tra", "sic_night_tra")
_NOCHE = ("pic_night_loc", "pic_night_tra", "sic_night_loc", "sic_night_tra")
#: Así se llaman las columnas en `flights`, con espacios. Ver `src/models/flight.py`.
_IMC = ("IMC Pil", "IMC Cop")

#: Las columnas que `estadisticas_publicas` necesita de `flights`, entre comillas las
#: que tienen espacios. Es lo único que se pide: ni fechas, ni rutas, ni horarios.
COLUMNAS_VUELO = ", ".join(
    ["aircraft_id", "duration", *_PIC, *_SIC] + [f'"{c}"' for c in _IMC]
)
COLUMNAS_LIBRO = ", ".join(
    [f"opening_{c}" for c in (*_PIC, *_SIC)] + ["opening_imc_pil", "opening_imc_cop"]
)


def _n(valor: Any) -> float:
    try:
        return float(valor or 0)
    except (TypeError, ValueError):
        return 0.0


def _suma(filas: Iterable[Dict[str, Any]], campos: Iterable[str], prefijo: str = "") -> float:
    campos = tuple(campos)
    return sum(_n(f.get(f"{prefijo}{c}")) for f in filas for c in campos)


def estadisticas_publicas(
    flights: List[Dict[str, Any]],
    logbooks: List[Dict[str, Any]],
    aircraft: List[Dict[str, Any]],
) -> Dict[str, float]:
    """
    Las cinco horas de un perfil: total, PIC, travesía, noche e instrumentos.

    - **Sin simuladores.** Una sesión de simulador es un renglón del libro, no un vuelo.
    - **Con las horas de apertura.** Un piloto que migró 500 horas del libro de papel
      no puede mostrar 46.
    - **El total es la duración más la apertura de PIC y SIC.** IMC y capota se
      superponen con el tiempo de vuelo en vez de particionarlo; sumarlas duplicaría.
    """
    simuladores = {a.get("id") for a in aircraft if a.get("is_simulator")}
    volados = [f for f in flights if f.get("aircraft_id") not in simuladores]

    apertura_pic = _suma(logbooks, _PIC, "opening_")
    apertura_sic = _suma(logbooks, _SIC, "opening_")

    horas = {
        "total": sum(_n(f.get("duration")) for f in volados) + apertura_pic + apertura_sic,
        "pic": _suma(volados, _PIC) + apertura_pic,
        "travesia": _suma(volados, _TRAVESIA) + _suma(logbooks, _TRAVESIA, "opening_"),
        "noche": _suma(volados, _NOCHE) + _suma(logbooks, _NOCHE, "opening_"),
        "instrumentos": _suma(volados, _IMC)
        + _suma(logbooks, ("imc_pil", "imc_cop"), "opening_"),
    }
    return {k: round(v, 1) for k, v in horas.items()}


# ---------------------------------------------------------------------------
# Búsqueda
# ---------------------------------------------------------------------------

def limpiar_busqueda(crudo: Optional[str]) -> str:
    """
    El texto de búsqueda, sin lo que rompería el filtro `or` de PostgREST.

    La coma y los paréntesis separan condiciones en ese filtro, y `%` y `*` son
    comodines: un piloto que escribe "ana, (" no puede cambiar qué se consulta.
    """
    texto = normalizar_handle(crudo)
    texto = re.sub(r"[,()%*\\\"'`:]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()[:40]


# ---------------------------------------------------------------------------
# Publicaciones
# ---------------------------------------------------------------------------

TEXTO_MAX = 1000
COMENTARIO_MAX = 500
FOTOS_MAX = 4
#: Por día y por piloto. Alcanza de sobra para usar la red y corta a un script.
PUBLICACIONES_POR_DIA = 30
COMENTARIOS_POR_DIA = 120

#: Lo que la ruta de un simulador dice en vez de aeródromos. Ver `soloVolados` del
#: frontend: `LOCAL` no es un aeródromo y no se muestra como uno.
_NO_AERODROMOS = {"LOCAL", "SIM", "???"}


def ruta_legible(route: Optional[str]) -> Optional[str]:
    """
    `"SADF SAAR"` → `"SADF → SAAR"`; un vuelo local → `"SADF · local"`.

    Sólo el primero y el último: los puntos intermedios de una travesía dicen por dónde
    pasó el piloto, y eso no lo eligió publicar.
    """
    puntos = [p.upper() for p in re.split(r"[\s,\-–>→]+", route or "") if p.strip()]
    puntos = [p for p in puntos if p not in _NO_AERODROMOS]
    if not puntos:
        return None
    origen, destino = puntos[0], puntos[-1]
    if origen == destino:
        return f"{origen} · local"
    return f"{origen} → {destino}"


def resumen_de_vuelo(
    flight: Dict[str, Any],
    aircraft: Optional[Dict[str, Any]],
    *,
    ruta: bool = True,
    duracion: bool = True,
    aeronave: bool = False,
    fecha: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    El chip de una publicación: sólo los campos que el piloto prendió.

    **Nunca la matrícula**, ni aunque se pida el avión: matrícula, aeródromo y hora
    juntos dicen dónde está un avión y cuándo. Del avión sale el tipo ("Cessna 152").
    `None` si no quedó nada que mostrar.
    """
    chip: Dict[str, Any] = {}
    if ruta:
        r = ruta_legible(flight.get("route"))
        if r:
            chip["ruta"] = r
    if duracion and _n(flight.get("duration")) > 0:
        chip["duracion"] = round(_n(flight.get("duration")), 1)
    if aeronave and aircraft:
        tipo = (aircraft.get("type") or "").strip()
        if tipo:
            chip["aeronave"] = tipo
    if fecha and flight.get("date"):
        chip["fecha"] = str(flight["date"])[:10]
    return chip or None


def validar_publicacion(texto: Optional[str], n_fotos: int, tiene_vuelo: bool) -> Optional[str]:
    """El motivo por el que no se puede publicar, o `None`."""
    limpio = (texto or "").strip()
    if not limpio and n_fotos == 0 and not tiene_vuelo:
        return "Escribí algo, subí una foto o elegí un vuelo."
    if len(limpio) > TEXTO_MAX:
        return f"El texto puede tener como mucho {TEXTO_MAX} caracteres."
    if n_fotos > FOTOS_MAX:
        return f"Podés subir hasta {FOTOS_MAX} fotos."
    return None


def validar_comentario(texto: Optional[str]) -> str:
    """El comentario limpio, o `ValueError` con el motivo."""
    limpio = (texto or "").strip()
    if not limpio:
        raise ValueError("El comentario está vacío.")
    if len(limpio) > COMENTARIO_MAX:
        raise ValueError(f"El comentario puede tener como mucho {COMENTARIO_MAX} caracteres.")
    return limpio


# ---------------------------------------------------------------------------
# Actividad
# ---------------------------------------------------------------------------

def ordenar_actividad(eventos: List[Dict[str, Any]], vista_at: Optional[str]) -> List[Dict[str, Any]]:
    """
    Lo más nuevo primero, y `nuevo` en lo que pasó después de la última vez que el
    piloto abrió su Actividad.

    Las fechas llegan como ISO de Postgres; comparadas como texto fallan cuando un lado
    trae microsegundos y el otro no, así que se parsean.
    """
    vista = _instante(vista_at)

    def clave(e: Dict[str, Any]) -> datetime:
        return _instante(e.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc)

    ordenados = sorted(eventos, key=clave, reverse=True)
    for e in ordenados:
        momento = _instante(e.get("created_at"))
        e["nuevo"] = bool(momento and vista and momento > vista)
    return ordenados


def _instante(valor: Any) -> Optional[datetime]:
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    try:
        momento = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


def url_avatar(base_url: str, path: Optional[str]) -> Optional[str]:
    """La URL pública de una foto de perfil. El bucket `avatares` es público (ver 019)."""
    if not path:
        return None
    return f"{base_url.rstrip('/')}/storage/v1/object/public/avatares/{path}"
