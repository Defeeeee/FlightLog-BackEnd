"""
Las estadísticas del panel de administración (`GET /admin/estadisticas`).

Todo puro: recibe las filas crudas y el "ahora", y devuelve el JSON que dibuja el
panel. El controlador (`controllers/admin.py`) sólo lee las tablas con el service role.

Decisiones que no se deducen del código:

- **Sólo agregados y el @.** Del panel no sale un mail ni un nombre: las últimas altas
  se muestran por su @ (que ya es público) o como "sin @". Alcanza para saber cómo
  entra la gente, y no expone a nadie aunque el panel se abra en una pantalla ajena.
- **Los días son de Argentina (UTC-3, sin horario de verano).** Un alta a las 22 h del
  23 es del 23, no del 24 como diría UTC. Se usa un offset fijo en vez de `zoneinfo`
  para no depender de `tzdata` en el VPS.
- **Por defecto no cuenta a los admins.** Federico tiene casi todos los vuelos de la
  base: con él adentro, "vuelos del último mes" mide a Federico. `incluir_admins`
  lo devuelve al total.
- **Los vuelos van por fecha de vuelo**, porque `flights` no tiene `created_at`: un
  libro importado de papel aparece en los meses en que se voló, no en el día en que
  se cargó.
- **"Activación" no es un embudo.** Cada paso se cuenta por separado (hay quien carga
  vuelos sin haber cargado el CMA), así que las barras no tienen por qué decrecer.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set

ARGENTINA = timezone(timedelta(hours=-3))
_CODIGO = re.compile(r"^[A-Z0-9]{3,4}$")
_NO_ES_AERODROMO = {"LOCAL", "LOC"}


@dataclass
class Crudos:
    """Las filas tal como salen de la base, con sólo las columnas que hacen falta."""

    usuarios: List[dict] = field(default_factory=list)  # id, created_at, last_sign_in_at
    perfiles: List[dict] = field(default_factory=list)  # id, license_type, whatsapp (bool)
    aviones: List[dict] = field(default_factory=list)  # id, user_id, type, is_simulator
    documentos: List[dict] = field(default_factory=list)  # user_id, kind
    vuelos: List[dict] = field(default_factory=list)  # user_id, date, duration, route, aircraft_id
    arrobas: List[dict] = field(default_factory=list)  # user_id, handle
    publicaciones: List[dict] = field(default_factory=list)  # autor
    seguimientos: List[dict] = field(default_factory=list)  # seguidor, estado
    aplausos: List[dict] = field(default_factory=list)  # user_id
    comentarios: List[dict] = field(default_factory=list)  # autor
    push: List[dict] = field(default_factory=list)  # user_id
    transacciones: List[dict] = field(default_factory=list)  # user_id
    packs: List[dict] = field(default_factory=list)  # user_id
    programados: List[dict] = field(default_factory=list)  # user_id
    metricas: List[dict] = field(default_factory=list)  # user_id
    auditoria: List[dict] = field(default_factory=list)  # user_id
    reportes: int = 0
    chats_whatsapp: int = 0
    #: Las tablas que no se pudieron leer. "No sé" no es "no hay": el panel las nombra.
    no_disponible: List[str] = field(default_factory=list)


def _momento(valor: Any) -> Optional[datetime]:
    """Un timestamp de Supabase (str o datetime, con o sin zona) como datetime en UTC."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        dt = valor
    else:
        texto = str(valor).strip().replace(" ", "T", 1)
        if texto.endswith("Z"):
            texto = texto[:-1] + "+00:00"
        # Postgres manda "+00" a secas; fromisoformat quiere "+00:00".
        texto = re.sub(r"([+-]\d{2})$", r"\1:00", texto)
        try:
            dt = datetime.fromisoformat(texto)
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _dia(valor: Any) -> Optional[date]:
    """El día en Argentina de un timestamp, o la fecha tal cual si ya es una fecha."""
    if isinstance(valor, date) and not isinstance(valor, datetime):
        return valor
    if isinstance(valor, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor.strip()):
        return date.fromisoformat(valor.strip())
    dt = _momento(valor)
    return dt.astimezone(ARGENTINA).date() if dt else None


def _iso(valor: Any) -> Optional[str]:
    dt = _momento(valor)
    return dt.isoformat() if dt else None


def _sin(filas: Iterable[dict], excluir: Set[str], clave: str = "user_id") -> List[dict]:
    return [f for f in filas if str(f.get(clave)) not in excluir]


def _pct(parte: int, total: int) -> float:
    return round(100 * parte / total, 1) if total else 0.0


def aerodromos_de(ruta: Optional[str]) -> List[str]:
    """Los códigos de una ruta ("SADF SAAK", "SADF-SADF", "ASG LOCAL"), sin "LOCAL"."""
    if not ruta:
        return []
    fichas = re.split(r"[\s\-–→>/,]+", ruta.upper())
    return [f for f in fichas if _CODIGO.match(f) and f not in _NO_ES_AERODROMO]


def _mes(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _meses_hasta(hoy: date, n: int) -> List[str]:
    y, m = hoy.year, hoy.month
    salida = []
    for _ in range(n):
        salida.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(salida))


def armar(c: Crudos, ahora: datetime, excluir: Optional[Set[str]] = None, dias: int = 60, meses: int = 12) -> Dict[str, Any]:
    excluir = {str(x) for x in (excluir or set())}
    ahora = ahora if ahora.tzinfo else ahora.replace(tzinfo=timezone.utc)
    hoy = ahora.astimezone(ARGENTINA).date()

    usuarios = [u for u in c.usuarios if str(u.get("id")) not in excluir]
    ids = {str(u["id"]) for u in usuarios}
    total = len(ids)

    def de_usuarios(filas: Iterable[dict], clave: str = "user_id") -> Set[str]:
        return {str(f[clave]) for f in filas if f.get(clave) and str(f[clave]) in ids}

    perfiles = {str(p["id"]): p for p in c.perfiles if str(p.get("id")) in ids}
    con_licencia = {i for i, p in perfiles.items() if p.get("license_type")}
    con_whatsapp = {i for i, p in perfiles.items() if p.get("whatsapp")}
    con_avion = de_usuarios(a for a in c.aviones if not a.get("is_simulator"))
    con_cma = de_usuarios(d for d in c.documentos if d.get("kind") == "cma")
    con_documentos = de_usuarios(c.documentos)
    arroba_de = {str(a["user_id"]): a.get("handle") for a in c.arrobas if str(a.get("user_id")) in ids}

    vuelos = [v for v in c.vuelos if str(v.get("user_id")) in ids]
    vuelos_por = Counter(str(v["user_id"]) for v in vuelos)
    horas = round(sum(float(v.get("duration") or 0) for v in vuelos), 1)
    hace_30 = hoy - timedelta(days=30)
    vuelos_30 = [v for v in vuelos if (_dia(v.get("date")) or date.min) >= hace_30]

    alta_de = {str(u["id"]): _momento(u.get("created_at")) for u in usuarios}
    ingreso_de = {str(u["id"]): _momento(u.get("last_sign_in_at")) for u in usuarios}
    dia_alta = {i: (m.astimezone(ARGENTINA).date() if m else None) for i, m in alta_de.items()}

    def altas_desde(n_dias: int) -> int:
        corte = hoy - timedelta(days=n_dias - 1)
        return sum(1 for d in dia_alta.values() if d and d >= corte)

    def activos_desde(n_dias: int) -> int:
        corte = ahora - timedelta(days=n_dias)
        return sum(1 for m in ingreso_de.values() if m and m >= corte)

    totales = {
        "cuentas": total,
        "altas_hoy": altas_desde(1),
        "altas_7d": altas_desde(7),
        "altas_30d": altas_desde(30),
        "activos_7d": activos_desde(7),
        "activos_30d": activos_desde(30),
        "con_vuelos": sum(1 for i in ids if vuelos_por[i] > 0),
        "vuelos": len(vuelos),
        "vuelos_30d": len(vuelos_30),
        "horas": horas,
        "con_arroba": len(arroba_de),
        "con_whatsapp": len(con_whatsapp),
        "con_push": len(de_usuarios(c.push)),
        "publicaciones": len(_sin(c.publicaciones, excluir, "autor")),
        "seguimientos": sum(1 for s in _sin(c.seguimientos, excluir, "seguidor") if s.get("estado") in (None, "aceptado")),
        "aplausos": len(_sin(c.aplausos, excluir)),
        "comentarios": len(_sin(c.comentarios, excluir, "autor")),
        "reportes": c.reportes,
        "chats_whatsapp": c.chats_whatsapp,
    }

    # Altas por día, con el acumulado: las cuentas que había al terminar ese día.
    primero = hoy - timedelta(days=dias - 1)
    por_dia = Counter(d for d in dia_alta.values() if d)
    previas = sum(n for d, n in por_dia.items() if d < primero)
    serie_altas, acumulado = [], previas
    for k in range(dias):
        d = primero + timedelta(days=k)
        acumulado += por_dia.get(d, 0)
        serie_altas.append({"fecha": d.isoformat(), "altas": por_dia.get(d, 0), "acumulado": acumulado})

    # Cuándo entró cada uno por última vez.
    tramos = [("Hoy", 0, 1), ("1 a 7 días", 1, 8), ("8 a 30 días", 8, 31), ("Más de 30 días", 31, 10**6)]
    ultimo_ingreso = []
    for nombre, desde, hasta in tramos:
        n = 0
        for m in ingreso_de.values():
            if m is None:
                continue
            dias_atras = (hoy - m.astimezone(ARGENTINA).date()).days
            if desde <= dias_atras < hasta:
                n += 1
        ultimo_ingreso.append({"tramo": nombre, "cuentas": n})
    ultimo_ingreso.append({"tramo": "Nunca", "cuentas": sum(1 for m in ingreso_de.values() if m is None)})

    pasos = [
        ("Cuenta creada", ids),
        ("Licencia cargada", con_licencia),
        ("Avión cargado", con_avion),
        ("CMA cargado", con_cma),
        ("Primer vuelo", {i for i in ids if vuelos_por[i] >= 1}),
        ("5 vuelos o más", {i for i in ids if vuelos_por[i] >= 5}),
        ("WhatsApp conectado", con_whatsapp),
        ("@ creado", set(arroba_de)),
    ]
    activacion = [{"paso": n, "cuentas": len(s), "pct": _pct(len(s), total)} for n, s in pasos]

    funciones = [
        ("Vuelos", {i for i in ids if vuelos_por[i]}),
        ("Documentos", con_documentos),
        ("Saldo y pagos", de_usuarios(c.transacciones)),
        ("Packs de horas", de_usuarios(c.packs)),
        ("Vuelos programados", de_usuarios(c.programados)),
        ("Métricas propias", de_usuarios(c.metricas)),
        ("Auditoría", de_usuarios(c.auditoria)),
        ("Copiloto por WhatsApp", con_whatsapp),
        ("Perfil en la red (@)", set(arroba_de)),
        ("Publicaciones", de_usuarios(c.publicaciones, "autor")),
        ("Sigue a alguien", de_usuarios(c.seguimientos, "seguidor")),
        ("Avisos push", de_usuarios(c.push)),
    ]
    uso = sorted(({"funcion": n, "cuentas": len(s), "pct": _pct(len(s), total)} for n, s in funciones), key=lambda x: (-x["cuentas"], x["funcion"]))

    licencias = Counter((perfiles.get(i) or {}).get("license_type") or "Sin cargar" for i in ids)
    licencias_lista = [{"licencia": k, "cuentas": v} for k, v in sorted(licencias.items(), key=lambda kv: (-kv[1], kv[0]))]

    etiquetas_mes = _meses_hasta(hoy, meses)
    por_mes: Dict[str, Dict[str, Any]] = {m: {"vuelos": 0, "horas": 0.0, "pilotos": set()} for m in etiquetas_mes}
    for v in vuelos:
        d = _dia(v.get("date"))
        if d and _mes(d) in por_mes:
            b = por_mes[_mes(d)]
            b["vuelos"] += 1
            b["horas"] += float(v.get("duration") or 0)
            b["pilotos"].add(str(v["user_id"]))
    vuelos_por_mes = [{"mes": m, "vuelos": b["vuelos"], "horas": round(b["horas"], 1), "pilotos": len(b["pilotos"])} for m, b in por_mes.items()]

    aerodromos: Counter = Counter()
    for v in vuelos:
        aerodromos.update(set(aerodromos_de(v.get("route"))))
    tipo_de = {str(a["id"]): (a.get("type") or "Sin tipo").strip().upper() for a in c.aviones if a.get("id")}
    tipos = Counter(tipo_de.get(str(v.get("aircraft_id")), "Sin tipo") for v in vuelos if v.get("aircraft_id"))

    # Cohortes semanales (lunes a domingo, en Argentina): cuántos de los que entraron esa
    # semana ya cargaron un avión y un vuelo.
    lunes = hoy - timedelta(days=hoy.weekday())
    cohortes = []
    for k in range(7, -1, -1):
        inicio = lunes - timedelta(weeks=k)
        fin = inicio + timedelta(days=7)
        grupo = {i for i, d in dia_alta.items() if d and inicio <= d < fin}
        cohortes.append({
            "semana": inicio.isoformat(),
            "altas": len(grupo),
            "con_avion": len(grupo & con_avion),
            "con_vuelo": sum(1 for i in grupo if vuelos_por[i] > 0),
        })

    recientes = sorted(ids, key=lambda i: alta_de.get(i) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)[:15]
    ultimas_altas = [{
        "alta": _iso(alta_de.get(i)),
        "ultimo_ingreso": _iso(ingreso_de.get(i)),
        "arroba": arroba_de.get(i),
        "licencia": (perfiles.get(i) or {}).get("license_type"),
        "avion": i in con_avion,
        "cma": i in con_cma,
        "whatsapp": i in con_whatsapp,
        "vuelos": vuelos_por[i],
    } for i in recientes]

    return {
        "generado": ahora.isoformat(),
        "hoy": hoy.isoformat(),
        "admins_excluidos": len(excluir & {str(u.get("id")) for u in c.usuarios}),
        "no_disponible": sorted(set(c.no_disponible)),
        "totales": totales,
        "altas_por_dia": serie_altas,
        "ultimo_ingreso": ultimo_ingreso,
        "activacion": activacion,
        "uso_funciones": uso,
        "licencias": licencias_lista,
        "vuelos_por_mes": vuelos_por_mes,
        "top_aerodromos": [{"codigo": k, "vuelos": v} for k, v in aerodromos.most_common(8)],
        "top_aeronaves": [{"tipo": k, "vuelos": v} for k, v in tipos.most_common(6)],
        "cohortes": cohortes,
        "ultimas_altas": ultimas_altas,
    }
