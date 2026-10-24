"""
Los recorridos ADS-B de los aviones del Hangar (migración 034), la parte pura: qué aviones
del tráfico en vivo son nuestros y qué posiciones vale la pena guardar.

El grabador (`grabador_adsb.py`) le pide a adsb.lol el tráfico alrededor de Buenos Aires
cada pocos segundos. Un avión es nuestro si su indicativo es la matrícula de algún Hangar sin
el guión (`LVS114`, así transmiten los livianos de escuela) o si su código ADS-B ya se
aprendió de una vez anterior (por si un día no manda el indicativo), o si la fuente trae la
matrícula de su base (`r`, adsb.fi).
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
        # adsb.fi trae la matrícula de su base (`r`) cuando la conoce, aunque no haya indicativo.
        por_registro = normalizar_matricula(a.get("r"))
        if por_indicativo in matriculas:
            salida.append((por_indicativo, h, a))
        elif por_registro in matriculas:
            salida.append((por_registro, h, a))
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
        "fuente": d.get("fuente"),
        "vueltas_ok": d.get("vueltas_ok"),
        "vueltas_fallidas": d.get("vueltas_fallidas"),
        **({"ultimo_error": d["ultimo_error"]} if d.get("ultimo_error") else {}),
    }


# --- Etapa 2: los vuelos dentro de las posiciones (2026-10-24) ---------------------------

#: Más de 5 minutos sin posiciones separa dos vuelos: en tierra, a nivel del piso, no llega la
#: señal a ningún receptor (medido el 2026-10-24: adentro de un vuelo, el corte más largo fue
#: de 2 min 37 s, y entre vuelos del mismo avión pasó al menos media hora).
HUECO_ENTRE_VUELOS = 300
#: Por debajo de esto, cerca del final de un vuelo o entre dos subidas, es un aterrizaje (o un
#: tocar y despegar). Los livianos nunca informan "en tierra": su transpondedor no lo sabe.
PIES_DE_ATERRIZAJE = 250
#: Cuánto antes del despegue y después del aterrizaje cargados se busca el tramo.
MARGEN_DEL_VUELO = timedelta(minutes=15)


def _t(p: dict) -> datetime:
    v = p["visto_at"]
    return v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def tramos(posiciones: Iterable[dict]) -> List[List[dict]]:
    """Las posiciones partidas en vuelos: un corte de más de 5 minutos es otro vuelo."""
    ordenadas = sorted(posiciones, key=_t)
    salida: List[List[dict]] = []
    for p in ordenadas:
        if salida and (_t(p) - _t(salida[-1][-1])).total_seconds() <= HUECO_ENTRE_VUELOS:
            salida[-1].append(p)
        else:
            salida.append([p])
    # Un tramo de una o dos posiciones es un avión que pasó lejos, no un vuelo para mostrar.
    return [t for t in salida if len(t) >= 3]


def aterrizajes(tramo: List[dict]) -> int:
    """
    Cuántas veces bajó por debajo de 250 pies viniendo de más arriba: el aterrizaje final y
    cada tocar y despegar. Un motor y al aire bajo también cuenta: por eso se presenta como
    estimado. Las primeras posiciones, recién despegado, no cuentan.
    """
    n, arriba = 0, False
    for p in tramo:
        alt = p.get("altitud")
        if alt is None:
            continue
        if alt > PIES_DE_ATERRIZAJE:
            arriba = True
        elif arriba:
            n += 1
            arriba = False
    return max(n, 1)


def _millas(tramo: List[dict]) -> float:
    import math

    total = 0.0
    for a, b in zip(tramo, tramo[1:]):
        la1, lo1, la2, lo2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
        h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
        total += 2 * 3440.065 * math.asin(math.sqrt(h))
    return total


def resumen(tramo: List[dict]) -> Dict:
    """Lo que se muestra de un tramo. Las horas son de la primera y la última posición en el aire."""
    alts = [p["altitud"] for p in tramo if p.get("altitud") is not None]
    vels = [p["velocidad"] for p in tramo if p.get("velocidad") is not None]
    return {
        "despegue": _t(tramo[0]).astimezone(timezone.utc).isoformat(timespec="seconds"),
        "aterrizaje": _t(tramo[-1]).astimezone(timezone.utc).isoformat(timespec="seconds"),
        "minutos": round((_t(tramo[-1]) - _t(tramo[0])).total_seconds() / 60),
        "aterrizajes": aterrizajes(tramo),
        "altitud_max": max(alts) if alts else None,
        "velocidad_max": round(max(vels)) if vels else None,
        "millas": round(_millas(tramo), 1),
        "posiciones": len(tramo),
        "inicio": [round(tramo[0]["lat"], 5), round(tramo[0]["lon"], 5)],
        "fin": [round(tramo[-1]["lat"], 5), round(tramo[-1]["lon"], 5)],
    }


def compactar(tramo: List[dict], fuente: str = "adsb.fi") -> Dict:
    """El recorrido para guardar con el vuelo: segundos desde el primero, para que pese poco."""
    t0 = _t(tramo[0])
    return {
        "t0": int(t0.timestamp()),
        "fuente": fuente,
        "p": [
            [
                int((_t(p) - t0).total_seconds()),
                round(p["lat"], 5),
                round(p["lon"], 5),
                p.get("altitud"),
                round(p["velocidad"]) if p.get("velocidad") is not None else None,
            ]
            for p in tramo
        ],
    }


def tramo_del_vuelo(posiciones: Iterable[dict], despegue: datetime, aterrizaje: datetime) -> Optional[List[dict]]:
    """
    El tramo que corresponde al vuelo cargado: el que más se superpone con su despegue y su
    aterrizaje. Nunca se devuelve otro tramo del mismo avión (el de otro piloto, en un avión
    de escuela): si ninguno se superpone, no hay recorrido.
    """
    mejor, mejor_s = None, 0.0
    for t in tramos(p for p in posiciones if despegue - MARGEN_DEL_VUELO <= _t(p) <= aterrizaje + MARGEN_DEL_VUELO):
        ini, fin = _t(t[0]), _t(t[-1])
        s = (min(fin, aterrizaje) - max(ini, despegue)).total_seconds()
        if s > mejor_s:
            mejor, mejor_s = t, s
    return mejor


#: Desde cuándo las posiciones son de adsb.fi; antes, de adsb.lol (ver `grabador_adsb.py`).
DESDE_ADSB_FI = datetime(2026, 10, 23, 20, 47, tzinfo=timezone.utc)


def fuente_de(tramo: List[dict]) -> str:
    return "adsb.fi" if _t(tramo[0]) >= DESDE_ADSB_FI else "adsb.lol"


def expandir(compacto: Dict) -> List[dict]:
    """El recorrido guardado, otra vez como posiciones (para el resumen)."""
    t0 = datetime.fromtimestamp(int(compacto["t0"]), timezone.utc)
    return [
        {"visto_at": t0 + timedelta(seconds=dt), "lat": la, "lon": lo, "altitud": alt, "velocidad": v}
        for dt, la, lo, alt, v in compacto.get("p", [])
    ]


def ventana_del_dia(fecha: str) -> Tuple[datetime, datetime]:
    """El día en hora argentina (UTC−3, sin horario de verano) como intervalo UTC."""
    d = datetime.fromisoformat(fecha).replace(tzinfo=timezone.utc) + timedelta(hours=3)
    return d, d + timedelta(days=1)
