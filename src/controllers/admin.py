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

from litestar import Controller, Request, get, patch, post
from litestar.exceptions import HTTPException, NotFoundException
from pydantic import BaseModel, Field

from src.auth.guards import auth_guard
from src.controllers.social import _yo
from src.services.avisos import admins
from src.services.estadisticas import Crudos, armar
from src.services import qr
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
    "mail_envios": lambda: _todas("mail_envios", "id,user_id,tipo,clave,enviado_at"),
    "mail_eventos": lambda: _todas("mail_eventos", "envio_id,tipo,destino,creado_at"),
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


class LoteQr(BaseModel):
    cantidad: int = Field(ge=1, le=200)
    lote: str | None = Field(default=None, max_length=40)


class AsignacionQr(BaseModel):
    # Dónde se pegó. Vacío la desasigna.
    etiqueta: str | None = Field(default=None, max_length=80)


def _admin_o_404(request: Request) -> None:
    if _yo(request) not in admins():
        raise NotFoundException()


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

    # --- Las pegatinas con QR (migración 033, `services/qr.py`) ---

    @get("/qr")
    async def pegatinas(self, request: Request) -> Dict[str, Any]:
        """Cada pegatina con dónde está, sus escaneos y las cuentas que salieron de ella."""
        _admin_o_404(request)
        codigos, escaneos, origenes = await asyncio.gather(
            asyncio.to_thread(_todas, "qr_codigos", "codigo,etiqueta,lote,creado_at,asignado_at"),
            asyncio.to_thread(_todas, "qr_escaneos", "codigo,con_sesion,creado_at"),
            asyncio.to_thread(lambda: SupabaseManager.get_service_client().table("profiles").select("origen_qr").not_.is_("origen_qr", "null").execute().data or []),
        )
        return {"pegatinas": qr.panel(codigos, escaneos, origenes)}

    @post("/qr", status_code=200)
    async def crear_pegatinas(self, request: Request, data: LoteQr) -> Dict[str, List[str]]:
        """Un lote de códigos nuevos, para imprimir. Se asignan después, escaneándolos."""
        _admin_o_404(request)

        def _crear() -> List[str]:
            existentes = [c["codigo"] for c in _todas("qr_codigos", "codigo")]
            nuevos = qr.generar(data.cantidad, existentes)
            lote = (data.lote or "").strip() or None
            SupabaseManager.get_service_client().table("qr_codigos").insert(
                [{"codigo": c, "lote": lote} for c in nuevos]
            ).execute()
            return nuevos

        return {"codigos": await asyncio.to_thread(_crear)}

    @get("/qr/{codigo:str}")
    async def pegatina(self, request: Request, codigo: str) -> Dict[str, Any]:
        _admin_o_404(request)
        c = qr.normalizar(codigo)

        def _leer() -> Dict[str, Any] | None:
            cliente = SupabaseManager.get_service_client()
            filas = cliente.table("qr_codigos").select("codigo,etiqueta,lote,creado_at,asignado_at").eq("codigo", c).limit(1).execute().data or []
            if not filas:
                return None
            escaneos = cliente.table("qr_escaneos").select("codigo,con_sesion,creado_at").eq("codigo", c).execute().data or []
            origenes = cliente.table("profiles").select("origen_qr").eq("origen_qr", c).execute().data or []
            return qr.panel(filas, escaneos, origenes)[0]

        fila = await asyncio.to_thread(_leer) if c else None
        if not fila:
            raise NotFoundException()
        return fila

    @patch("/qr/{codigo:str}")
    async def asignar_pegatina(self, request: Request, codigo: str, data: AsignacionQr) -> Dict[str, Any]:
        _admin_o_404(request)
        c = qr.normalizar(codigo)
        etiqueta = (data.etiqueta or "").strip() or None

        def _asignar() -> bool:
            r = (
                SupabaseManager.get_service_client().table("qr_codigos")
                .update({"etiqueta": etiqueta, "asignado_at": datetime.now(timezone.utc).isoformat() if etiqueta else None})
                .eq("codigo", c).execute()
            )
            return bool(r.data)

        if not c or not await asyncio.to_thread(_asignar):
            raise NotFoundException()
        return {"codigo": c, "etiqueta": etiqueta}
