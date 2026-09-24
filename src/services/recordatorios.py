"""
El recordatorio del día siguiente al alta: a quién mandárselo.

El 2026-09-23 entraron cuatro pilotos desde un grupo de WhatsApp. Ninguno cargó un vuelo
y ninguno volvió a entrar: nada los traía de vuelta. Esto elige a quién escribirle al día
siguiente, **una sola vez**:

- se registró ese día (en hora argentina, como el panel de administración);
- confirmó el mail (a un mail sin confirmar no se le escribe);
- todavía no tiene vuelos;
- y no se le mandó antes. La marca vive en el `app_metadata` de la cuenta de auth
  (`recordatorio_primer_vuelo`), que sólo el service role puede escribir, así que no
  hace falta una migración y el piloto no la puede tocar.

Es puro: el controlador (`controllers/onboarding.py`) trae las filas y marca los enviados.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Iterable, List, Set

from src.services.estadisticas import _dia, _momento

MARCA = "recordatorio_primer_vuelo"


def pendientes_de_recordatorio(
    usuarios: Iterable[Dict[str, Any]],
    perfiles: Dict[str, Dict[str, Any]],
    con_vuelos: Set[str],
    con_avion: Set[str],
    dia: date,
) -> List[Dict[str, Any]]:
    """
    `usuarios`: id, email, created_at, email_confirmed_at, app_metadata.
    `perfiles`: por id, con first_name y whatsapp (bool).
    """
    salida = []
    for u in usuarios:
        uid = str(u.get("id"))
        if not u.get("email") or not _momento(u.get("email_confirmed_at")):
            continue
        if _dia(u.get("created_at")) != dia:
            continue
        if uid in con_vuelos:
            continue
        if (u.get("app_metadata") or {}).get(MARCA):
            continue
        perfil = perfiles.get(uid) or {}
        salida.append({
            "user_id": uid,
            "email": u["email"],
            "first_name": perfil.get("first_name") or None,
            "tiene_avion": uid in con_avion,
            "tiene_whatsapp": bool(perfil.get("whatsapp")),
        })
    return salida
