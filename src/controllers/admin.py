"""
El panel de administración: `GET /admin/estadisticas`.

**Sólo para los user ids de `ADMINS_RED`**, la misma lista que recibe los avisos de los
reportes (hoy, Federico). A cualquier otro le contesta 404 y no 403: que el panel
exista tampoco es algo que un piloto tenga por qué saber.

Lee con el service role, porque cuenta filas de todos los pilotos y el RLS está para
que eso no pase. Por eso mismo lo que devuelve son agregados: las cuentas se muestran
por su @ o como "sin @", nunca por mail ni nombre (ver `services/estadisticas.py`).

Cada tabla se lee por separado y en paralelo. Una que falle no tira abajo el panel: va
a `no_disponible` y el frontend la nombra, en vez de mostrar un cero que no es cierto.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List

from litestar import Controller, Request, get
from litestar.exceptions import HTTPException, NotFoundException

from src.auth.guards import auth_guard
from src.controllers.social import _yo
from src.services.avisos import admins
from src.services.estadisticas import Crudos, armar
from src.supabase_client import SupabaseManager

log = logging.getLogger(__name__)

_LOTE = 1000


def _todas(tabla: str, columnas: str) -> List[dict]:
    """Todas las filas de una tabla, de a mil: PostgREST corta en 1000 sin avisar."""
    cliente = SupabaseManager.get_service_client()
    filas: List[dict] = []
    desde = 0
    while True:
        lote = cliente.table(tabla).select(columnas).range(desde, desde + _LOTE - 1).execute().data or []
        filas.extend(lote)
        if len(lote) < _LOTE:
            return filas
        desde += _LOTE


def _cuantas(tabla: str) -> int:
    r = SupabaseManager.get_service_client().table(tabla).select("*", count="exact").limit(1).execute()
    return int(r.count or 0)


def _usuarios() -> List[dict]:
    """Las cuentas de auth: sólo id, alta y último ingreso. El mail no sale de acá."""
    admin = SupabaseManager.get_service_client().auth.admin
    salida: List[dict] = []
    pagina = 1
    while True:
        lote = admin.list_users(page=pagina, per_page=_LOTE) or []
        for u in lote:
            salida.append({
                "id": str(u.id),
                "created_at": getattr(u, "created_at", None),
                "last_sign_in_at": getattr(u, "last_sign_in_at", None),
            })
        if len(lote) < _LOTE:
            return salida
        pagina += 1


def _perfiles() -> List[dict]:
    # El teléfono no viaja: sólo si hay uno.
    return [
        {"id": p["id"], "license_type": p.get("license_type"), "whatsapp": bool(p.get("whatsapp_phone"))}
        for p in _todas("profiles", "id,license_type,whatsapp_phone")
    ]


LECTURAS: Dict[str, Callable[[], Any]] = {
    "usuarios": _usuarios,
    "perfiles": _perfiles,
    "aviones": lambda: _todas("aircraft", "id,user_id,type,is_simulator"),
    "documentos": lambda: _todas("documents", "user_id,kind"),
    "vuelos": lambda: _todas("flights", "user_id,date,duration,route,aircraft_id"),
    "arrobas": lambda: _todas("perfiles_publicos", "user_id,handle"),
    "publicaciones": lambda: _todas("publicaciones", "autor"),
    "seguimientos": lambda: _todas("seguimientos", "seguidor,estado"),
    "aplausos": lambda: _todas("aplausos", "user_id"),
    "comentarios": lambda: _todas("comentarios", "autor"),
    "push": lambda: _todas("suscripciones_push", "user_id"),
    "transacciones": lambda: _todas("transactions", "user_id"),
    "packs": lambda: _todas("flight_packs", "user_id"),
    "programados": lambda: _todas("planned_flights", "user_id"),
    "metricas": lambda: _todas("custom_stats", "user_id"),
    "auditoria": lambda: _todas("audit_findings", "user_id"),
    "reportes": lambda: _cuantas("reportes"),
    "chats_whatsapp": lambda: _cuantas("whatsapp_chats"),
}


async def leer_crudos() -> Crudos:
    nombres = list(LECTURAS)
    resultados = await asyncio.gather(*(asyncio.to_thread(LECTURAS[n]) for n in nombres), return_exceptions=True)
    crudos = Crudos()
    for nombre, r in zip(nombres, resultados):
        if isinstance(r, BaseException):
            log.warning("[admin] no se pudo leer %s: %r", nombre, r)
            crudos.no_disponible.append(nombre)
            continue
        setattr(crudos, nombre, r)
    return crudos


class AdminController(Controller):
    path = "/admin"
    guards = [auth_guard]

    @get("/estadisticas")
    async def estadisticas(self, request: Request, incluir_admins: bool = False) -> Dict[str, Any]:
        lista = admins()
        if _yo(request) not in lista:
            raise NotFoundException()
        crudos = await leer_crudos()
        # Sin las cuentas, no hay panel: todo se cuenta sobre ellas.
        if "usuarios" in crudos.no_disponible:
            raise HTTPException(status_code=503, detail="No se pudieron leer las cuentas.")
        return armar(crudos, datetime.now(timezone.utc), excluir=set() if incluir_admins else set(lista))
