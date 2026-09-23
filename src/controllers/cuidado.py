"""
Cuidar la red: los avisos push y los reportes (migración 021).

- `/push/...`: la clave pública para suscribirse, y dar de alta o de baja el navegador.
- `/reportes`: reportar un perfil, una publicación o un comentario. Se escribe y no se
  lee: lo revisa quien administra, al que se le manda un aviso push si está en
  `ADMINS_RED`.

Los dos exigen Bearer (`_token_o_401`): son cosas de una persona, no de una
integración con API key.
"""

from __future__ import annotations

import asyncio
from typing import Dict

from litestar import Controller, Request, get, post
from litestar.exceptions import HTTPException
from postgrest import ReturnMethod

from src.auth.guards import auth_guard
from src.config import settings
from src.controllers.publicaciones import _SIN_HANDLE, _fabrica, _hace_un_dia, _token_o_401
from src.controllers.social import _perfil_de, _yo
from src.models.social import BajaPushIn, ClavePush, ReporteIn, SuscripcionPushIn
from src.services.avisos import admins, armar_aviso, avisos_configurados, enviar_aviso
from src.supabase_client import SupabaseManager

#: Un tope de cordura: nadie reporta treinta cosas en un día de buena fe.
REPORTES_POR_DIA = 20


class PushController(Controller):
    path = "/push"
    guards = [auth_guard]

    @get("/clave")
    async def clave(self, request: Request) -> ClavePush:
        """La clave pública VAPID. `None` si los avisos no están configurados en este servidor."""
        _token_o_401(request)
        return ClavePush(clave=settings.vapid_public_key if avisos_configurados() else None)

    @post("/suscripcion", status_code=201)
    async def suscribir(self, request: Request, data: SuscripcionPushIn) -> Dict[str, bool]:
        """
        Dar de alta este navegador. Un `endpoint` es de un navegador, no de una persona:
        si antes estaba a nombre de otra cuenta —cerró sesión y entró otra—, pasa a ésta.
        Por eso va con el service role: el RLS no deja tocar la fila ajena, y está bien
        que no deje.
        """
        _token_o_401(request)
        yo = _yo(request)

        def _guardar() -> None:
            tabla = SupabaseManager.get_service_client().table("suscripciones_push")
            tabla.delete().eq("endpoint", data.endpoint).neq("user_id", yo).execute()
            SupabaseManager.get_service_client().table("suscripciones_push").upsert(
                {"user_id": yo, "endpoint": data.endpoint, "p256dh": data.keys.p256dh, "auth": data.keys.auth},
                on_conflict="endpoint",
            ).execute()

        await asyncio.to_thread(_guardar)
        return {"ok": True}

    @post("/baja", status_code=200)
    async def dar_de_baja(self, request: Request, data: BajaPushIn) -> Dict[str, bool]:
        """Dar de baja este navegador. Con el cliente del piloto: sólo puede borrar lo suyo."""
        token = _token_o_401(request)
        yo = _yo(request)
        await asyncio.to_thread(
            lambda: _fabrica(token)().table("suscripciones_push").delete()
            .eq("endpoint", data.endpoint).eq("user_id", yo).execute()
        )
        return {"ok": True}


class ReportesController(Controller):
    path = "/reportes"
    guards = [auth_guard]

    @post(status_code=201)
    async def reportar(self, request: Request, data: ReporteIn) -> Dict[str, bool]:
        token = _token_o_401(request)
        yo = _yo(request)

        def _guardar() -> None:
            cliente = _fabrica(token)()
            if not _perfil_de(cliente, yo):
                raise HTTPException(status_code=409, detail=_SIN_HANDLE)
            # El conteo con el service role: los reportes no tienen política de lectura.
            recientes = (
                SupabaseManager.get_service_client().table("reportes")
                .select("id", count="exact", head=True)
                .eq("denunciante", yo).gte("created_at", _hace_un_dia()).execute()
            )
            if (recientes.count or 0) >= REPORTES_POR_DIA:
                raise HTTPException(status_code=429, detail="Llegaste al máximo de reportes por hoy.")
            # `minimal`: sin política de lectura, pedir la fila de vuelta fallaría.
            cliente.table("reportes").insert(
                {"denunciante": yo, "tipo": data.tipo, "objetivo": data.objetivo, "motivo": data.motivo},
                returning=ReturnMethod.minimal,
            ).execute()

        await asyncio.to_thread(_guardar)
        aviso = armar_aviso("reporte", "", texto=f"{data.tipo} {data.objetivo}: {data.motivo}")
        for admin in admins():
            enviar_aviso(admin, aviso)
        return {"ok": True}
