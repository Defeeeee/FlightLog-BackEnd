"""
Las pegatinas con QR (migración 033), la parte pura: los códigos, cuándo una cuenta vino de
una pegatina y lo que muestra el panel.

Cada pegatina impresa lleva su código (`/q/K7P2`). Se imprimen iguales y se asignan después
a un lugar, escaneándolas (ver `controllers/qr.py` y la ruta `/q/[codigo]` del frontend).
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Set

#: Sin 0/O, 1/I/L ni 5/S: el código va impreso abajo del QR y alguien lo puede tipear.
ALFABETO = "2346789ABCDEFGHJKMNPQRTUVWXYZ"
LARGO = 4
#: Hasta cuántos días después del escaneo una cuenta nueva cuenta como de esa pegatina.
DIAS_DE_ATRIBUCION = 30
FORMATO = re.compile(r"^[A-Z0-9]{4,8}$")


def normalizar(codigo: str) -> Optional[str]:
    """El código en mayúsculas, o None si no tiene forma de código."""
    c = (codigo or "").strip().upper()
    return c if FORMATO.match(c) else None


def generar(cantidad: int, existentes: Iterable[str]) -> List[str]:
    """`cantidad` códigos nuevos, distintos entre sí y de los que ya existen."""
    usados: Set[str] = set(existentes)
    nuevos: List[str] = []
    while len(nuevos) < cantidad:
        c = "".join(secrets.choice(ALFABETO) for _ in range(LARGO))
        if c not in usados:
            usados.add(c)
            nuevos.append(c)
    return nuevos


def _fecha(v) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def atribuible(alta, escaneo) -> bool:
    """
    Si una cuenta creada en `alta` vino de un escaneo en `escaneo`: se creó después de
    escanear (con un minuto de margen por los relojes) y dentro de los 30 días. Un piloto
    que ya tenía cuenta y escaneó la pegatina no es un alta de esa pegatina.
    """
    a, e = _fecha(alta), _fecha(escaneo)
    if not a or not e:
        return False
    return e - timedelta(minutes=1) <= a <= e + timedelta(days=DIAS_DE_ATRIBUCION)


def panel(codigos: List[dict], escaneos: List[dict], origenes: List[dict]) -> List[Dict]:
    """
    Una fila por pegatina: dónde está, cuántos la escanearon (con y sin sesión), el último
    escaneo y cuántas cuentas salieron de ella. Primero las asignadas, por escaneos.
    """
    filas: Dict[str, Dict] = {
        c["codigo"]: {
            "codigo": c["codigo"],
            "etiqueta": c.get("etiqueta"),
            "lote": c.get("lote"),
            "creado_at": c.get("creado_at"),
            "asignado_at": c.get("asignado_at"),
            "escaneos": 0,
            "escaneos_sin_sesion": 0,
            "ultimo_escaneo": None,
            "cuentas": 0,
        }
        for c in codigos
    }
    for e in escaneos:
        f = filas.get(e.get("codigo"))
        if not f:
            continue
        f["escaneos"] += 1
        if not e.get("con_sesion"):
            f["escaneos_sin_sesion"] += 1
        if e.get("creado_at") and (f["ultimo_escaneo"] is None or str(e["creado_at"]) > str(f["ultimo_escaneo"])):
            f["ultimo_escaneo"] = e["creado_at"]
    for p in origenes:
        f = filas.get(p.get("origen_qr"))
        if f:
            f["cuentas"] += 1
    return sorted(filas.values(), key=lambda f: (f["etiqueta"] is None, -f["escaneos"], f["codigo"]))
