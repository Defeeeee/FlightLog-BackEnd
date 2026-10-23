"""
Los recorridos ADS-B de los aviones del Hangar (migración 034), la parte pura: qué aviones
del tráfico en vivo son nuestros y qué posiciones vale la pena guardar.

El grabador (`grabador_adsb.py`) le pide a adsb.lol el tráfico alrededor de Buenos Aires
cada pocos segundos. Un avión es nuestro si su indicativo es la matrícula de algún Hangar sin
el guión (`LVS114`, así transmiten los livianos de escuela) o si su código ADS-B ya se
aprendió de una vez anterior (por si un día no manda el indicativo).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Set, Tuple

#: Una posición más vieja que esto en la respuesta no se guarda: es de hace rato.
SEGUNDOS_MAX_POSICION = 60
#: Lo que se guarda de un avión quieto: una posición cada tanto, no una cada 10 s.
SEGUNDOS_ENTRE_QUIETAS = 120
DIAS_DE_RETENCION = 30


def normalizar_matricula(crudo: Optional[str]) -> Optional[str]:
    """`LV-S114`, `lv s114`, `LVS114 ` → `LVS114`. None si no parece una matrícula."""
    m = re.sub(r"[^A-Z0-9]", "", (crudo or "").upper())
    return m if 2 <= len(m) <= 10 else None


def matriculas_del_hangar(aviones: Iterable[dict]) -> Set[str]:
    """Las matrículas de los aviones de verdad (sin simuladores), normalizadas."""
    salida: Set[str] = set()
    for a in aviones:
        if a.get("is_simulator"):
            continue
        m = normalizar_matricula(a.get("registration"))
        if m:
            salida.add(m)
    return salida


def _hex(v) -> Optional[str]:
    h = str(v or "").strip().lower().lstrip("~")
    return h if re.fullmatch(r"[0-9a-f]{6}", h) else None


def nuestros(trafico: Iterable[dict], matriculas: Set[str], hex_conocidos: Dict[str, str]) -> List[Tuple[str, str, dict]]:
    """
    Los aviones del tráfico que son de algún Hangar: `(matrícula, hex, avión)`.
    `hex_conocidos` es hex → matrícula, lo aprendido antes.
    """
    salida = []
    for a in trafico:
        h = _hex(a.get("hex"))
        if not h:
            continue
        por_indicativo = normalizar_matricula(a.get("flight"))
        if por_indicativo in matriculas:
            salida.append((por_indicativo, h, a))
        elif h in hex_conocidos:
            salida.append((hex_conocidos[h], h, a))
    return salida


def posicion(a: dict, ahora: datetime) -> Optional[dict]:
    """
    La fila para `adsb_posiciones`, o None si no hay posición fresca. La hora es la de la
    posición (`ahora - seen_pos`), no la del pedido. `alt_baro` es "ground" en tierra.
    """
    lat, lon = a.get("lat"), a.get("lon")
    visto = a.get("seen_pos")
    if lat is None or lon is None or visto is None or float(visto) > SEGUNDOS_MAX_POSICION:
        return None
    alt = a.get("alt_baro")
    en_tierra = alt == "ground"
    return {
        "visto_at": (ahora - timedelta(seconds=float(visto))).replace(microsecond=0).isoformat(),
        "lat": round(float(lat), 6),
        "lon": round(float(lon), 6),
        "altitud": int(alt) if isinstance(alt, (int, float)) else None,
        "velocidad": round(float(a["gs"]), 1) if isinstance(a.get("gs"), (int, float)) else None,
        "en_tierra": en_tierra,
    }


def vale_guardar(nueva: dict, anterior: Optional[dict]) -> bool:
    """
    Se guarda si es la primera, si es de otro momento y el avión se movió, o si está quieto
    pero pasó un rato (para saber que seguía ahí). Así un avión en el hangar no llena la tabla.
    """
    if anterior is None:
        return True
    if nueva["visto_at"] == anterior["visto_at"]:
        return False
    movio = (nueva["lat"], nueva["lon"], nueva["altitud"]) != (anterior["lat"], anterior["lon"], anterior["altitud"])
    if movio:
        return True
    t0 = datetime.fromisoformat(anterior["visto_at"])
    t1 = datetime.fromisoformat(nueva["visto_at"])
    return (t1 - t0).total_seconds() >= SEGUNDOS_ENTRE_QUIETAS


def limite_de_retencion(ahora: datetime) -> str:
    return (ahora - timedelta(days=DIAS_DE_RETENCION)).astimezone(timezone.utc).isoformat()


def latido_del_grabador(ruta: str, ahora: datetime) -> Dict:
    """
    Lo que `GET /health` dice del grabador: cuándo fue su última vuelta, si salió bien y si
    está vivo (una vuelta en el último minuto). Nunca tira: si no hay latido, lo dice.
    """
    import json

    try:
        with open(ruta) as f:
            d = json.load(f)
        vuelta = datetime.fromisoformat(d["vuelta"])
    except (OSError, ValueError, KeyError, TypeError):
        return {"vivo": False, "detalle": "sin latido"}
    return {
        "vivo": (ahora - vuelta).total_seconds() < 60,
        "ultima_vuelta": d["vuelta"],
        "ok": bool(d.get("ok")),
        "trafico": d.get("trafico"),
        "nuestros_en_el_aire": d.get("nuestros_en_el_aire"),
        "vueltas_ok": d.get("vueltas_ok"),
        "vueltas_fallidas": d.get("vueltas_fallidas"),
        **({"ultimo_error": d["ultimo_error"]} if d.get("ultimo_error") else {}),
    }
