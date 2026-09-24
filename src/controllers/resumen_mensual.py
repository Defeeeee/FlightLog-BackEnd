"""
El resumen del mes por mail (`/resumen-mensual`).

Mismo reparto que el briefing y el recordatorio del alta: **el backend dice a quién** y
con qué datos, el frontend arma el mail y lo manda (las credenciales de Resend viven
allá), y después avisa acá a quiénes les llegó para marcarlos.

A diferencia del recordatorio, el mail lleva números: horas, aterrizajes, lo que falta
para la PPA o la PCA y lo gastado. Esos cálculos ya existen en el frontend y están
testeados (`lib/pca-progress.ts`, `lib/ppa-progress.ts`, `lib/costos.ts`), y son los
mismos que ve el piloto en el inicio. **Por eso esto devuelve las filas y no los
números**: calcularlos de nuevo acá, en Python, sería tener dos versiones de la RAAC 61
que pueden no coincidir, y la del mail diría una cosa y la del inicio otra.

Sin guard de sesión, con el secreto de los barridos (`X-Cron-Secret`): un cron no tiene
sesión. Todo con el service role, así que filtra por `user_id` a mano en cada tabla.
"""

from __future__ import annotations

import asyncio
import hmac
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from litestar import Controller, Request, get, post
from litestar.exceptions import NotAuthorizedException, ValidationException
from pydantic import BaseModel, Field

from src.config import settings
from src.controllers.admin import _todas
from src.controllers.flight_packs import FlightPacksController
from src.controllers.onboarding import _usuarios_completos
from src.services.estadisticas import ARGENTINA
from src.services.resumen_mensual import BAJA, MARCA, mes_anterior, mes_valido, pendientes_de_resumen
from src.supabase_client import SupabaseManager


class Enviados(BaseModel):
    mes: str
    user_ids: List[str] = Field(default_factory=list, max_length=500)


class Baja(BaseModel):
    user_id: str
    # `False` es volver a suscribirse, desde la misma página de la baja.
    baja: bool = True


def _por_usuario(filas: List[dict], ids: set) -> Dict[str, List[dict]]:
    agrupadas: Dict[str, List[dict]] = defaultdict(list)
    for f in filas:
        uid = str(f.get("user_id"))
        if uid in ids:
            agrupadas[uid].append(f)
    return agrupadas


def _escribir_meta(uid: str, cambios: Dict[str, Any]) -> None:
    """Mezcla `cambios` en el `app_metadata` de la cuenta, sin pisar lo demás."""
    admin = SupabaseManager.get_service_client().auth.admin
    actual = admin.get_user_by_id(uid)
    meta = dict(getattr(getattr(actual, "user", None), "app_metadata", None) or {})
    meta.update(cambios)
    admin.update_user_by_id(uid, {"app_metadata": meta})


class ResumenMensualController(Controller):
    path = "/resumen-mensual"

    SECRET_HEADER = "X-Cron-Secret"

    def _verify_secret(self, request: Request) -> None:
        expected = settings.documents_alert_secret
        recibido = request.headers.get(self.SECRET_HEADER) or ""
        if not expected:
            raise NotAuthorizedException("El barrido no está configurado.")
        if not recibido or not hmac.compare_digest(recibido, expected):
            raise NotAuthorizedException("Invalid secret token.")

    @get("/pendientes")
    async def pendientes(self, request: Request, mes: Optional[str] = None) -> Dict[str, Any]:
        """
        A quién le toca el resumen de `mes` ("YYYY-MM"; por defecto, el mes anterior en
        Argentina), con todo lo que el frontend necesita para armarlo.
        """
        self._verify_secret(request)
        mes = mes or mes_anterior(datetime.now(ARGENTINA).date())
        if not mes_valido(mes):
            raise ValidationException("mes tiene que ser YYYY-MM")

        usuarios, vuelos = await asyncio.gather(
            asyncio.to_thread(_usuarios_completos),
            asyncio.to_thread(lambda: _todas("flights", "*")),
        )
        elegidos = pendientes_de_resumen(usuarios, {str(v["user_id"]) for v in vuelos}, mes)
        if not elegidos:
            return {"mes": mes, "pilotos": []}
        ids = {e["user_id"] for e in elegidos}

        perfiles, aviones, libros, movimientos, documentos = await asyncio.gather(
            asyncio.to_thread(lambda: _todas("profiles", "id,first_name,license_type,fecha_ppa,tracking_mode")),
            asyncio.to_thread(lambda: _todas("aircraft", "*")),
            asyncio.to_thread(lambda: _todas("logbooks", "*")),
            asyncio.to_thread(lambda: _todas("transactions", "*")),
            asyncio.to_thread(lambda: _todas("documents", "user_id,kind,expiry_date")),
        )
        cliente = SupabaseManager.get_service_client()
        packs = await asyncio.gather(
            *(FlightPacksController._get_packs_with_hours(uid, cliente) for uid in ids),
            return_exceptions=True,
        )
        packs_por_id = {
            uid: [] if isinstance(p, Exception) else [x.model_dump(mode="json") for x in p]
            for uid, p in zip(ids, packs)
        }

        perfil_de = {str(p["id"]): p for p in perfiles}
        vuelos_de = _por_usuario(vuelos, ids)
        aviones_de = _por_usuario(aviones, ids)
        libros_de = _por_usuario(libros, ids)
        movimientos_de = _por_usuario(movimientos, ids)
        documentos_de = _por_usuario(documentos, ids)

        pilotos = []
        for e in elegidos:
            uid = e["user_id"]
            perfil = perfil_de.get(uid) or {}
            pilotos.append({
                **e,
                "first_name": perfil.get("first_name") or None,
                "license_type": perfil.get("license_type"),
                "fecha_ppa": perfil.get("fecha_ppa"),
                "tracking_mode": perfil.get("tracking_mode"),
                "flights": vuelos_de.get(uid, []),
                "aircraft": aviones_de.get(uid, []),
                "logbooks": libros_de.get(uid, []),
                "transactions": movimientos_de.get(uid, []),
                "documents": documentos_de.get(uid, []),
                "packs": packs_por_id.get(uid, []),
            })
        return {"mes": mes, "pilotos": pilotos}

    @post("/enviados", status_code=200)
    async def marcar(self, request: Request, data: Enviados) -> Dict[str, int]:
        """Marca a quiénes les llegó el resumen de `mes`."""
        self._verify_secret(request)
        if not mes_valido(data.mes):
            raise ValidationException("mes tiene que ser YYYY-MM")

        def _marcar() -> int:
            for uid in data.user_ids:
                _escribir_meta(uid, {MARCA: data.mes})
            return len(data.user_ids)

        return {"marcados": await asyncio.to_thread(_marcar)}

    @post("/baja", status_code=200)
    async def baja(self, request: Request, data: Baja) -> Dict[str, bool]:
        """
        Da de baja (o vuelve a suscribir) a un piloto. El frontend ya verificó el link
        firmado del mail: acá sólo llega con el secreto de los barridos.
        """
        self._verify_secret(request)
        await asyncio.to_thread(lambda: _escribir_meta(data.user_id, {BAJA: data.baja}))
        return {"baja": data.baja}
