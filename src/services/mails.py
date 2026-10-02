"""
El seguimiento de los mails: a quién le toca el de novedades, y las métricas del panel.

Vector mide sus propios mails (migración 023): cada envío deja un renglón, cada apertura
y cada clic, un evento. Acá está lo que se calcula con eso, **puro**: el controlador
(`controllers/mails.py`) y el panel (`controllers/admin.py`) traen las filas.

**Cómo leer los números, y por qué el panel lo aclara:**
- Una *apertura* es que alguien pidió la imagen de 1×1 del mail. Gmail la pide cuando el
  piloto abre el mail; Apple Mail la baja solo aunque nadie lo abra. Sirve para comparar
  un mail con otro, no como cuenta exacta de lectores.
- Un *clic* es que alguien pasó por la redirección de un link. Los filtros de correo de
  algunas empresas abren todos los links: un clic a los dos segundos del envío no fue
  una persona.
- Por eso todo se cuenta **por envío** (¿este mail tuvo al menos una apertura?) y no por
  evento: abrir el mismo mail cinco veces es un mail abierto.
- **Lo que pasa en el primer minuto no es una persona** (`SEGUNDOS_AUTOMATICO`). En la
  primera tanda de novedades (2026-10-02), 5 de 15 mails "se abrieron" entre 6 y 21
  segundos después de salir: es el correo, o su antispam, bajando las imágenes al
  recibirlo. Esos eventos se cuentan aparte, como automáticos, y no como aperturas ni
  clics. Se pierde al que de verdad abre en menos de un minuto; se prefiere eso a un
  33 % de apertura que no existió.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Set

from src.services.estadisticas import ARGENTINA, _iso, _momento, _pct

TIPOS = ("primer-vuelo", "resumen-mensual", "briefing", "novedades")
EVENTOS = ("apertura", "clic")

#: La baja de los mails de novedades, en el `app_metadata` de la cuenta. La del resumen
#: del mes es otra (`resumen_mensual_baja`): darse de baja de uno no saca del otro.
BAJA_NOVEDADES = "novedades_baja"


def pendientes_de_novedades(
    usuarios: Iterable[Dict[str, Any]],
    ya_enviados: Set[str],
) -> List[Dict[str, Any]]:
    """
    A quién mandarle una tanda de novedades: mail confirmado, sin baja, y que no la haya
    recibido (`ya_enviados`: los `user_id` con un envío de esa tanda en `mail_envios`).
    Correr el envío dos veces no manda dos mails.
    """
    salida = []
    for u in usuarios:
        uid = str(u.get("id"))
        meta = u.get("app_metadata") or {}
        if not u.get("email") or not _momento(u.get("email_confirmed_at")):
            continue
        if meta.get(BAJA_NOVEDADES) or uid in ya_enviados:
            continue
        salida.append({"user_id": uid, "email": u["email"]})
    return salida


def _mas_tocados(cuenta: Counter, n: int) -> List[Dict[str, Any]]:
    """Los destinos con más clics. En empate, por nombre: el orden no puede bailar."""
    orden = sorted(cuenta.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
    return [{"destino": d, "clics": c} for d, c in orden]


def _tramo(minutos: float) -> str:
    if minutos < 60:
        return "menos de 1 h"
    if minutos < 6 * 60:
        return "1 a 6 h"
    if minutos < 24 * 60:
        return "6 a 24 h"
    return "más de 1 día"


TRAMOS = ("menos de 1 h", "1 a 6 h", "6 a 24 h", "más de 1 día")

#: Antes de esto, una apertura o un clic se toma por automático (ver el encabezado).
SEGUNDOS_AUTOMATICO = 60


def mails_del_panel(
    envios: Iterable[Dict[str, Any]],
    eventos: Iterable[Dict[str, Any]],
    ids: Set[str],
    arroba_de: Dict[str, Optional[str]],
    ahora: datetime,
    dias: int = 30,
) -> Dict[str, Any]:
    """
    `envios`: id, user_id, tipo, clave, enviado_at. `eventos`: envio_id, tipo, destino,
    creado_at. `ids`: las cuentas que cuentan (el panel saca a los administradores).
    """
    ahora = ahora if ahora.tzinfo else ahora.replace(tzinfo=timezone.utc)
    hoy = ahora.astimezone(ARGENTINA).date()

    propios = {str(e["id"]): e for e in envios if e.get("id") and str(e.get("user_id")) in ids}
    aperturas: Dict[str, List[datetime]] = defaultdict(list)
    clics: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    #: Los envíos con algún evento en el primer minuto: los tocó una máquina.
    automaticos: Set[str] = set()
    for ev in eventos:
        eid = str(ev.get("envio_id"))
        cuando = _momento(ev.get("creado_at"))
        if eid not in propios or not cuando:
            continue
        enviado = _momento(propios[eid].get("enviado_at"))
        if enviado and (cuando - enviado).total_seconds() < SEGUNDOS_AUTOMATICO:
            automaticos.add(eid)
            continue
        if ev.get("tipo") == "apertura":
            aperturas[eid].append(cuando)
        elif ev.get("tipo") == "clic":
            clics[eid].append({"cuando": cuando, "destino": ev.get("destino") or "(sin destino)"})

    def resumen(grupo: List[str]) -> Dict[str, Any]:
        abiertos = [e for e in grupo if aperturas[e]]
        con_clic = [e for e in grupo if clics[e]]
        demoras = []
        for e in abiertos:
            enviado = _momento(propios[e].get("enviado_at"))
            if enviado:
                demoras.append(max(0.0, (min(aperturas[e]) - enviado).total_seconds() / 60))
        return {
            "enviados": len(grupo),
            "abiertos": len(abiertos),
            "con_clic": len(con_clic),
            "tasa_apertura": _pct(len(abiertos), len(grupo)),
            "tasa_clic": _pct(len(con_clic), len(grupo)),
            # Sobre los que lo abrieron: ¿el mail convence a quien lo ve?
            "clic_sobre_abiertos": _pct(len(con_clic), len(abiertos)),
            "minutos_hasta_abrir": round(median(demoras)) if demoras else None,
            # Mails que una máquina tocó en el primer minuto. No dice nada del piloto.
            "automaticos": sum(1 for e in grupo if e in automaticos),
        }

    por_campana: Dict[tuple, List[str]] = defaultdict(list)
    for eid, e in propios.items():
        por_campana[(e.get("tipo") or "", e.get("clave"))].append(eid)

    def ultimo_envio(grupo: List[str]) -> datetime:
        return max((_momento(propios[e].get("enviado_at")) or datetime.min.replace(tzinfo=timezone.utc)) for e in grupo)

    campanas = []
    for (tipo, clave), grupo in sorted(por_campana.items(), key=lambda kv: ultimo_envio(kv[1]), reverse=True):
        destinos: Counter = Counter()
        for e in grupo:
            # Un mismo link tocado tres veces en un mail es un clic a ese destino.
            destinos.update({c["destino"] for c in clics[e]})
        campanas.append({
            "tipo": tipo,
            "clave": clave,
            "ultimo_envio": _iso(ultimo_envio(grupo)),
            **resumen(grupo),
            "destinos": _mas_tocados(destinos, 6),
        })

    destinos_totales: Counter = Counter()
    for e in propios:
        destinos_totales.update({c["destino"] for c in clics[e]})

    # Por día, en Argentina: lo que salió, lo que se abrió por primera vez y los clics.
    desde = hoy - timedelta(days=dias - 1)
    serie = {desde + timedelta(days=i): {"enviados": 0, "abiertos": 0, "clics": 0} for i in range(dias)}
    for eid, e in propios.items():
        enviado = _momento(e.get("enviado_at"))
        if enviado and enviado.astimezone(ARGENTINA).date() in serie:
            serie[enviado.astimezone(ARGENTINA).date()]["enviados"] += 1
        if aperturas[eid]:
            d = min(aperturas[eid]).astimezone(ARGENTINA).date()
            if d in serie:
                serie[d]["abiertos"] += 1
        if clics[eid]:
            d = min(c["cuando"] for c in clics[eid]).astimezone(ARGENTINA).date()
            if d in serie:
                serie[d]["clics"] += 1

    # A qué hora se abren (hora argentina de la primera apertura): cuándo conviene mandar.
    horas = Counter(min(a).astimezone(ARGENTINA).hour for a in aperturas.values() if a)
    tramos = Counter()
    for eid, lista in aperturas.items():
        enviado = _momento(propios[eid].get("enviado_at"))
        if lista and enviado:
            tramos[_tramo(max(0.0, (min(lista) - enviado).total_seconds() / 60))] += 1

    recientes = sorted(propios, key=lambda e: _momento(propios[e].get("enviado_at")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)[:25]
    ultimos = [{
        "enviado": _iso(_momento(propios[e].get("enviado_at"))),
        "tipo": propios[e].get("tipo"),
        "clave": propios[e].get("clave"),
        "arroba": arroba_de.get(str(propios[e].get("user_id"))),
        "abierto": _iso(min(aperturas[e])) if aperturas[e] else None,
        "aperturas": len(aperturas[e]),
        "clics": len(clics[e]),
        "destinos": sorted({c["destino"] for c in clics[e]}),
    } for e in recientes]

    # Quién abrió alguno y quién nunca: la lista de a quién no le llega nada.
    por_piloto: Dict[str, List[str]] = defaultdict(list)
    for eid, e in propios.items():
        por_piloto[str(e.get("user_id"))].append(eid)
    pilotos = {
        "con_mails": len(por_piloto),
        "abrieron_alguno": sum(1 for g in por_piloto.values() if any(aperturas[e] for e in g)),
        "hicieron_clic": sum(1 for g in por_piloto.values() if any(clics[e] for e in g)),
        "nunca_abrieron": sum(1 for g in por_piloto.values() if not any(aperturas[e] for e in g)),
    }

    return {
        "totales": resumen(list(propios)),
        "pilotos": pilotos,
        "campanas": campanas,
        "destinos": _mas_tocados(destinos_totales, 8),
        "por_dia": [{"dia": d.isoformat(), **v} for d, v in serie.items()],
        "por_hora": [{"hora": h, "aperturas": horas.get(h, 0)} for h in range(24)],
        "hasta_abrir": [{"tramo": t, "mails": tramos.get(t, 0)} for t in TRAMOS],
        "ultimos": ultimos,
    }
