"""
Las pegatinas con QR (migración 033, `services/qr.py`).

- `POST /qr/escaneos`: alguien escaneó una pegatina. Lo llama la ruta pública `/q/[codigo]`
  del frontend, con el secreto de los barridos (`X-Cron-Secret`), como los eventos de los
  mails. Contesta si el código existe y dónde está pegado.
- `POST /qr/origen`: la cuenta con sesión viene de una pegatina. Lo llama el frontend la
  primera vez que la cuenta entra al dashboard con la cookie del escaneo. Sólo se anota si
  la cuenta se creó después de escanear y dentro de los 30 días, y nunca se pisa.

Lo de administrar (crear un lote, asignar, el panel) está en `controllers/admin.py`.
"""

from __future__ import annotations

import asyncio
import hmac
from datetime import datetime
from typing import Any, Dict

from litestar import Controller, Request, post
from litestar.exceptions import NotAuthorizedException
from pydantic import BaseModel, Field

from src.auth.guards import auth_guard
from src.config import settings
from src.controllers.social import _yo
from src.services.qr import atribuible, normalizar
from src.supabase_client import SupabaseManager


def verificar_secreto(request: Request) -> None:
    esperado = settings.documents_alert_secret
    recibido = request.headers.get("X-Cron-Secret") or ""
    if not esperado:
        raise NotAuthorizedException("El barrido no está configurado.")
    if not recibido or not hmac.compare_digest(recibido, esperado):
        raise NotAuthorizedException("Invalid secret token.")


class Escaneo(BaseModel):
    codigo: str = Field(max_length=12)
    con_sesion: bool = False


class Origen(BaseModel):
    codigo: str = Field(max_length=12)
    escaneado_at: datetime


class QrController(Controller):
    path = "/qr"

    @post("/escaneos", status_code=200)
    async def escaneo(self, request: Request, data: Escaneo) -> Dict[str, Any]:
        """Anota el escaneo. Un código que no existe no se anota y no es un error."""
        verificar_secreto(request)
        codigo = normalizar(data.codigo)
        if not codigo:
            return {"existe": False, "etiqueta": None}

        def _anotar() -> Dict[str, Any]:
            cliente = SupabaseManager.get_service_client()
            filas = cliente.table("qr_codigos").select("etiqueta").eq("codigo", codigo).limit(1).execute().data or []
            if not filas:
                return {"existe": False, "etiqueta": None}
            cliente.table("qr_escaneos").insert({"codigo": codigo, "con_sesion": data.con_sesion}).execute()
            return {"existe": True, "etiqueta": filas[0].get("etiqueta")}

        return await asyncio.to_thread(_anotar)

    @post("/origen", status_code=200, guards=[auth_guard])
    async def origen(self, request: Request, data: Origen) -> Dict[str, bool]:
        codigo = normalizar(data.codigo)
        if not codigo:
            return {"anotado": False}
        yo = _yo(request)

        def _anotar() -> bool:
            cliente = SupabaseManager.get_service_client()
            perfil = cliente.table("profiles").select("origen_qr").eq("id", yo).limit(1).execute().data or []
            if not perfil or perfil[0].get("origen_qr"):
                return False
            if not cliente.table("qr_codigos").select("codigo").eq("codigo", codigo).limit(1).execute().data:
                return False
            usuario = cliente.auth.admin.get_user_by_id(yo).user
            if not atribuible(getattr(usuario, "created_at", None), data.escaneado_at):
                return False
            cliente.table("profiles").update({"origen_qr": codigo}).eq("id", yo).is_("origen_qr", "null").execute()
            return True

        return {"anotado": await asyncio.to_thread(_anotar)}
