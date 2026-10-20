"""
El mail "¿Cargamos tu vuelo?" de un plan de vuelo presentado (migración 027).

Mismo reparto que el recordatorio del alta (`services/recordatorios.py`): el backend dice
qué planes **pueden** necesitarlo, y el frontend decide con la hora (la llegada estimada más
una hora y media, `lib/plan-cierre.ts`, la misma cuenta que el "¿Ya volaste?" del inicio),
arma el mail, lo manda y avisa cuáles salieron para marcarlos.

Un plan puede necesitarlo si está completo y presentado (mandado o con el PDF bajado), no
se cerró (registrado, cancelado o "no lo volé"), no tiene ya su mail, y es de los últimos
días. Va con los vuelos recientes del piloto, para no escribirle a quien ya cargó ese vuelo
por otro lado.

Es puro: el controlador trae las filas.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


def armar_pendientes(
    planes: Iterable[Dict[str, Any]],
    usuarios: Dict[str, Dict[str, Any]],
    perfiles: Dict[str, Dict[str, Any]],
    vuelos: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    `usuarios`: por id, con `email` y `email_confirmed_at` (de auth).
    `perfiles`: por id, con `first_name`.
    `vuelos`: user_id, date y route de los vuelos recientes.

    A un mail sin confirmar no se le escribe, como en el resto de los barridos.
    """
    por_usuario: Dict[str, List[Dict[str, Any]]] = {}
    for v in vuelos:
        por_usuario.setdefault(str(v.get("user_id")), []).append({"date": v.get("date"), "route": v.get("route")})
    salida = []
    for p in planes:
        uid = str(p.get("user_id"))
        u = usuarios.get(uid) or {}
        if not u.get("email") or not u.get("email_confirmed_at"):
            continue
        salida.append({
            "id": str(p["id"]),
            "user_id": uid,
            "email": u["email"],
            "first_name": (perfiles.get(uid) or {}).get("first_name") or None,
            "formulario": p.get("formulario") or {},
            "demoras": p.get("demoras") or [],
            "vuelos": por_usuario.get(uid, []),
        })
    return salida
