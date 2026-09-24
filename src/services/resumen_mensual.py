"""
El resumen del mes por mail: a quién mandárselo.

El frontend (`/api/cron/resumen-mensual`) lo manda el día 1 con el mes anterior: horas,
aterrizajes, aeródromos, lo que falta para la PPA o la PCA, y lo gastado. Esto elige a
quién:

- tiene mail confirmado (a un mail sin confirmar no se le escribe);
- cargó **al menos un vuelo**, en cualquier fecha. A quien no cargó nunca, un resumen
  vacío no le dice nada: para eso está el mail del día siguiente al alta. A quien voló
  antes y este mes no, sí se le manda: "¿volaste y no lo cargaste?" es la razón de ser
  del mail;
- no se dio de baja (`BAJA` en el `app_metadata`, desde el link del mismo mail);
- y no recibió todavía el de ese mes (`MARCA` guarda el último mes mandado, "YYYY-MM").
  Correr el barrido dos veces no manda dos mails.

Las marcas viven en el `app_metadata` de la cuenta de auth, como la del recordatorio:
sólo el service role las escribe y no hace falta una migración.

Es puro: el controlador (`controllers/resumen_mensual.py`) trae las filas y marca.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, Iterable, List, Set

from src.services.estadisticas import _momento

MARCA = "resumen_mensual"
BAJA = "resumen_mensual_baja"

_MES = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def mes_valido(mes: str) -> bool:
    return bool(_MES.match(mes or ""))


def mes_anterior(hoy: date) -> str:
    """El mes que se resume: el anterior a `hoy` (que llega en hora argentina)."""
    anio, mes = (hoy.year, hoy.month - 1) if hoy.month > 1 else (hoy.year - 1, 12)
    return f"{anio:04d}-{mes:02d}"


def pendientes_de_resumen(
    usuarios: Iterable[Dict[str, Any]],
    con_vuelos: Set[str],
    mes: str,
) -> List[Dict[str, Any]]:
    """`usuarios`: id, email, email_confirmed_at, app_metadata. Devuelve id y email."""
    salida = []
    for u in usuarios:
        uid = str(u.get("id"))
        meta = u.get("app_metadata") or {}
        if not u.get("email") or not _momento(u.get("email_confirmed_at")):
            continue
        if uid not in con_vuelos:
            continue
        if meta.get(BAJA):
            continue
        if meta.get(MARCA) == mes:
            continue
        salida.append({"user_id": uid, "email": u["email"]})
    return salida
