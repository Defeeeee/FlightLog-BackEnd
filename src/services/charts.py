"""
Las cartas Jeppesen que viven en el disco del servidor, no en la base ni en git.

## Por qué esto no es lo mismo que las cartas del AIP

`src/lib/aip.ts`, del lado del frontend, enlaza directo al PDF que ANAC publica
gratis: ANAC lo aloja, Vector sólo apunta. Estas son distintas en las dos cosas que
importan — son de Jeppesen, contenido pago, y viven en un directorio propio del
servidor (`Charts/Argentina/<ICAO>/<categoría>/*.pdf`, cientos de archivos). No se
pueden enlazar a un tercero porque el tercero no las aloja para nosotros, y no se
suben a git porque un repositorio no es un lugar para cientos de PDF que además
cambian con cada revisión de Jeppesen.

## Por qué se lista el disco en cada pedido y no se mantiene un catálogo a mano

Porque el catálogo **es** el disco: agregar o sacar una carta es copiar o borrar un
archivo, y un índice aparte se desincroniza la primera vez que alguien lo hace sin
acordarse de tocar el índice también. Es la misma lección que dejaron las tablas de
frecuencias a mano del AIP, con un motivo más filesystem que dato: acá no hay
transcripción posible que verificar, sólo un directorio que leer.

## La parte que importa de verdad: nadie elige la ruta

`icao`, `categoria` y `nombre_archivo` llegan de la URL, o sea de cualquiera que
sepa armar un pedido. La defensa no es "filtrar caracteres raros" — es que el path
final se resuelve a un absoluto y se comprueba que siga **adentro** de la raíz
configurada (`Path.resolve()` + `relative_to`). Eso neutraliza cualquier `..`,
sea que venga tal cual o percent-encoded, sin tener que enumerar de antemano qué
caracteres son peligrosos.
"""

import re
from pathlib import Path
from typing import Dict, List, Optional, TypedDict

ICAO_RE = re.compile(r"^[A-Z0-9]{4}$")


class Carta(TypedDict):
    categoria: str
    archivo: str


def _raiz(configurada: Optional[str]) -> Optional[Path]:
    """
    La carpeta `Charts/Argentina`, o `None` si no está configurada o no existe.

    Sin `JEPPESEN_CHARTS_DIR` en el entorno, todo lo demás en este módulo devuelve
    "no hay nada" en vez de reventar — mismo criterio que `documents_alert_secret`
    en `config.py`: un servidor sin la carpeta montada todavía sirve el resto de
    la app.
    """
    if not configurada:
        return None
    raiz = Path(configurada).expanduser().resolve()
    return raiz if raiz.is_dir() else None


def listar_cartas(raiz_configurada: Optional[str], icao: str) -> List[Carta]:
    """Las cartas de un aeródromo, agrupadas por la categoría que ya trae Jeppesen."""
    icao = icao.strip().upper()
    if not ICAO_RE.match(icao):
        return []

    raiz = _raiz(raiz_configurada)
    if raiz is None:
        return []

    carpeta_aerodromo = raiz / icao
    if not carpeta_aerodromo.is_dir():
        return []

    cartas: List[Carta] = []
    for carpeta_categoria in sorted(p for p in carpeta_aerodromo.iterdir() if p.is_dir()):
        for pdf in sorted(carpeta_categoria.glob("*.pdf")):
            cartas.append({"categoria": carpeta_categoria.name, "archivo": pdf.name})
    return cartas


def _es_un_solo_segmento(valor: str) -> bool:
    """
    `categoria` y `archivo` tienen que nombrar exactamente una carpeta o un
    archivo, no una ruta. Sin esto, `archivo="../../secreto.pdf"` no *escapa* de
    la raíz configurada —sigue estando adentro, `Path.resolve()` sólo la lleva a
    otro lado dentro de ella— así que el chequeo de `relative_to(raiz)` de más
    abajo lo deja pasar. Sirve un archivo que no es una carta en vez de negarlo.

    Sí lo agarra esto: ni separador de ninguno de los dos sistemas operativos
    (el servidor es Linux, pero un `\` no tiene ningún uso legítimo acá tampoco),
    ni `.` ni `..` sueltos.
    """
    return bool(valor) and "/" not in valor and "\\" not in valor and valor not in (".", "..")


def resolver_carta(
    raiz_configurada: Optional[str], icao: str, categoria: str, archivo: str
) -> Optional[Path]:
    """
    La ruta absoluta de una carta puntual, o `None` si no corresponde servirla.

    `None` cubre a propósito los mismos casos que un 404: ICAO con forma rara,
    carpeta configurada ausente, archivo que no es un PDF, y — las que importan —
    cualquier intento de meter más de un segmento en `categoria` o `archivo`, o de
    escapar de la raíz una vez armada la ruta. El llamador no necesita distinguir
    entre estos motivos; todos terminan en "no está".
    """
    icao = icao.strip().upper()
    if not ICAO_RE.match(icao):
        return None
    if not _es_un_solo_segmento(categoria) or not _es_un_solo_segmento(archivo):
        return None

    raiz = _raiz(raiz_configurada)
    if raiz is None:
        return None

    candidata = (raiz / icao / categoria / archivo).resolve()
    try:
        candidata.relative_to(raiz)
    except ValueError:
        # Defensa de más: con el chequeo de arriba no debería quedar forma de
        # llegar hasta acá habiéndose ido de la raíz, pero que la comprobación
        # final sea "¿seguís adentro?" y no "¿el segmento se veía raro?" es lo
        # que la hace válida aunque a alguno de los dos de arriba se le escape un
        # caso.
        return None

    if candidata.suffix.lower() != ".pdf" or not candidata.is_file():
        return None

    return candidata
