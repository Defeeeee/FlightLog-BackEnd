"""
El recordatorio del día siguiente al alta (`/onboarding/recordatorios`).

Mismo reparto que el briefing y los vencimientos: **el backend dice a quién**, el
frontend arma el mail y lo manda (las credenciales de Resend viven allá), y después
avisa acá a quiénes les llegó para marcarlos. El que falla no se marca y queda para el
día siguiente... pero al día siguiente ya no es "el día después del alta", así que no se
le vuelve a mandar: el recordatorio es uno o ninguno, nunca dos.

Sin guard de sesión, con el secreto de los barridos (`X-Cron-Secret`): un cron no tiene
sesión. Controlador aparte por la misma razón que `FlightBriefingsController`.
"""

from __future__ import annotations

import asyncio
import hmac
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from litestar import Controller, Request, get, post
from litestar.exceptions import NotAuthorizedException
from pydantic import BaseModel, Field
from supabase import Client

from src.auth.guards import auth_guard

from src.config import settings
from src.controllers.admin import _todas
from src.services.estadisticas import ARGENTINA
from src.services.recordatorios import MARCA, pendientes_de_recordatorio
from src.supabase_client import SupabaseManager


class Enviados(BaseModel):
    user_ids: List[str] = Field(default_factory=list, max_length=500)


def _usuarios_completos() -> List[Dict[str, Any]]:
    admin = SupabaseManager.get_service_client().auth.admin
    salida: List[Dict[str, Any]] = []
    pagina = 1
    while True:
        lote = admin.list_users(page=pagina, per_page=1000) or []
        for u in lote:
            salida.append({
                "id": str(u.id),
                "email": getattr(u, "email", None),
                "created_at": getattr(u, "created_at", None),
                "email_confirmed_at": getattr(u, "email_confirmed_at", None),
                "app_metadata": getattr(u, "app_metadata", None) or {},
            })
        if len(lote) < 1000:
            return salida
        pagina += 1


class OnboardingController(Controller):
    path = "/onboarding"

    SECRET_HEADER = "X-Cron-Secret"

    def _verify_secret(self, request: Request) -> None:
        expected = settings.documents_alert_secret
        recibido = request.headers.get(self.SECRET_HEADER) or ""
        if not expected:
            raise NotAuthorizedException("El barrido no está configurado.")
        if not recibido or not hmac.compare_digest(recibido, expected):
            raise NotAuthorizedException("Invalid secret token.")

    @get("/recordatorios")
    async def recordatorios(self, request: Request, dia: Optional[date] = None) -> List[Dict[str, Any]]:
        """Quiénes se registraron `dia` (por defecto, ayer en Argentina) y no cargaron vuelos."""
        self._verify_secret(request)
        objetivo = dia or (datetime.now(ARGENTINA).date() - timedelta(days=1))
        usuarios, perfiles, vuelos, aviones = await asyncio.gather(
            asyncio.to_thread(_usuarios_completos),
            asyncio.to_thread(lambda: _todas("profiles", "id,first_name,whatsapp_phone")),
            asyncio.to_thread(lambda: _todas("flights", "user_id")),
            asyncio.to_thread(lambda: _todas("aircraft", "user_id,is_simulator")),
        )
        por_id = {str(p["id"]): {"first_name": p.get("first_name"), "whatsapp": bool(p.get("whatsapp_phone"))} for p in perfiles}
        return pendientes_de_recordatorio(
            usuarios,
            por_id,
            con_vuelos={str(v["user_id"]) for v in vuelos},
            con_avion={str(a["user_id"]) for a in aviones if not a.get("is_simulator")},
            dia=objetivo,
        )

    @post("/recordatorios/enviados", status_code=200)
    async def marcar(self, request: Request, data: Enviados) -> Dict[str, int]:
        """Marca a quiénes les llegó, en el `app_metadata` de su cuenta."""
        self._verify_secret(request)
        admin = SupabaseManager.get_service_client().auth.admin
        ahora = datetime.now(timezone.utc).isoformat()

        def _marcar() -> int:
            n = 0
            for uid in data.user_ids:
                actual = admin.get_user_by_id(uid)
                meta = dict(getattr(getattr(actual, "user", None), "app_metadata", None) or {})
                meta[MARCA] = ahora
                admin.update_user_by_id(uid, {"app_metadata": meta})
                n += 1
            return n

        return {"marcados": await asyncio.to_thread(_marcar)}


class OnboardingEstadoController(Controller):
    """
    `GET /onboarding/estado`: qué pasos del alta tiene hechos el piloto que pregunta.

    Desde el 2026-09-24 el alta es obligatoria y **retoma donde quedó** (decisión de
    Federico): el frontend bloquea el dashboard hasta completarla y arranca en el primer
    paso sin hacer. Por eso se calcula con los datos, no con una marca: si alguien cargó
    el avión desde el Hangar, el paso 2 ya está.

    Con el cliente del piloto (RLS) y sólo conteos: un piloto con 500 vuelos no trae 500
    filas para saber si tiene uno.
    """

    path = "/onboarding/estado"
    guards = [auth_guard]

    @get()
    async def estado(self, request: Request, supabase_client: Client) -> Dict[str, bool]:
        uid = str(request.state.user.id)

        def contar(tabla: str, **filtros: Any) -> int:
            q = supabase_client.table(tabla).select("id", count="exact").eq("user_id", uid)
            for k, v in filtros.items():
                q = q.eq(k, v)
            return int(q.limit(1).execute().count or 0)

        def aviones_reales() -> int:
            # `is_simulator` puede ser NULL en aeronaves viejas, y `= false` no las cuenta.
            q = (
                supabase_client.table("aircraft").select("id", count="exact").eq("user_id", uid)
                .or_("is_simulator.is.null,is_simulator.eq.false")
            )
            return int(q.limit(1).execute().count or 0)

        def perfil() -> Dict[str, Any]:
            r = supabase_client.table("profiles").select("license_type,whatsapp_phone").eq("id", uid).limit(1).execute()
            return (r.data or [{}])[0]

        p, cma, aviones, libros, vuelos = await asyncio.gather(
            asyncio.to_thread(perfil),
            asyncio.to_thread(lambda: contar("documents", kind="cma")),
            asyncio.to_thread(aviones_reales),
            asyncio.to_thread(lambda: contar("logbooks")),
            asyncio.to_thread(lambda: contar("flights")),
        )
        return {
            "licencia": (p.get("license_type") or "-").strip() not in ("", "-"),
            "cma": cma > 0,
            "aeronave": aviones > 0,
            "libro": libros > 0,
            "vuelos": vuelos > 0,
            "whatsapp": bool(p.get("whatsapp_phone")),
        }
