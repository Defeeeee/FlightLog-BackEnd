"""
El recordatorio del día siguiente al alta: a quién mandárselo.

El 2026-09-23 entraron cuatro pilotos desde un grupo de WhatsApp. Ninguno cargó un vuelo
y ninguno volvió a entrar: nada los traía de vuelta. Esto elige a quién escribirle al día
siguiente, **una sola vez**:

- se registró en los últimos `ventana` días hasta ese día inclusive (en hora argentina,
  como el panel de administración). **Una ventana y no un solo día** porque el 25 y el
  26/09 el barrido falló (Supabase no contestó `list_users` a tiempo) y las altas de
  esos días se perdieron para siempre: con la ventana, la corrida siguiente las alcanza;
- confirmó el mail (a un mail sin confirmar no se le escribe);
- todavía no tiene vuelos;
- y no se le mandó antes. La marca vive en el `app_metadata` de la cuenta de auth
  (`recordatorio_primer_vuelo`), que sólo el service role puede escribir, así que no
  hace falta una migración y el piloto no la puede tocar.

Es puro: el controlador (`controllers/onboarding.py`) trae las filas y marca los enviados.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set

from src.services.estadisticas import _dia, _momento

MARCA = "recordatorio_primer_vuelo"


def pendientes_de_recordatorio(
    usuarios: Iterable[Dict[str, Any]],
    perfiles: Dict[str, Dict[str, Any]],
    con_vuelos: Set[str],
    con_avion: Set[str],
    dia: date,
    ventana: int = 1,
    hoy: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """
    `usuarios`: id, email, created_at, email_confirmed_at, app_metadata.
    `perfiles`: por id, con first_name y whatsapp (bool).
    `dia`: el último día de alta que entra (ayer, en el barrido diario).
    `ventana`: cuántos días hacia atrás desde `dia`, inclusive. La marca evita repetir.

    Cada pendiente lleva `dias_desde_el_alta`, contados desde `hoy` (por defecto, el día
    después de `dia`), para que el mail no diga "ayer" a quien se registró hace días.
    """
    hoy = hoy or dia + timedelta(days=1)
    desde = dia - timedelta(days=max(ventana, 1) - 1)
    salida = []
    for u in usuarios:
        uid = str(u.get("id"))
        if not u.get("email") or not _momento(u.get("email_confirmed_at")):
            continue
        alta = _dia(u.get("created_at"))
        if alta is None or not (desde <= alta <= dia):
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
            "dias_desde_el_alta": (hoy - alta).days,
        })
    return salida
