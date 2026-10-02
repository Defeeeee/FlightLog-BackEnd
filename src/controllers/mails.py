"""
El seguimiento de los mails y el mail de novedades (`/mails`).

Vector mide sus propios mails (migración 023). El frontend arma y manda cada mail —las
credenciales de Resend viven allá— y le avisa a esto:

- `POST /mails/envios`: qué mails salieron. El id lo genera el frontend antes de mandar,
  porque va adentro de los links.
- `POST /mails/eventos`: una apertura o un clic. Lo llaman las dos rutas públicas del
  frontend (`/api/mail/a` y `/api/mail/c`), que ya verificaron la firma del link.
- `GET /mails/novedades/pendientes`: a quién le toca una tanda de novedades.
- `POST /mails/baja`: la baja de un tipo de mail, desde el link firmado.

Todo con el secreto de los barridos (`X-Cron-Secret`) y el service role: ni un piloto ni
un visitante llegan a estas tablas. Las métricas se leen por `GET /admin/estadisticas`.
"""

from __future__ import annotations

import asyncio
import hmac
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from litestar import Controller, Request, get, post
from litestar.exceptions import NotAuthorizedException, ValidationException
from pydantic import BaseModel, Field

from src.config import settings
from src.controllers.admin import _todas
from src.controllers.onboarding import _usuarios_completos
from src.controllers.resumen_mensual import _escribir_meta
from src.services.mails import BAJA_NOVEDADES, EVENTOS, TIPOS, pendientes_de_novedades
from src.services.resumen_mensual import BAJA as BAJA_RESUMEN
from src.supabase_client import SupabaseManager

TipoMail = Literal["primer-vuelo", "resumen-mensual", "briefing", "novedades"]
assert set(TipoMail.__args__) == set(TIPOS)


class Envio(BaseModel):
    id: UUID
    # Sin cuenta sólo en las copias de prueba, que no entran en ninguna métrica.
    user_id: Optional[UUID] = None
    tipo: TipoMail
    clave: Optional[str] = Field(default=None, max_length=40)


class Envios(BaseModel):
    envios: List[Envio] = Field(default_factory=list, max_length=500)


class Evento(BaseModel):
    envio_id: UUID
    tipo: Literal["apertura", "clic"]
    destino: Optional[str] = Field(default=None, max_length=200)


class Baja(BaseModel):
    user_id: UUID
    tipo: Literal["resumen", "novedades"]
    # `False` es volver a suscribirse, desde la misma página de la baja.
    baja: bool = True


assert set(Evento.model_fields["tipo"].annotation.__args__) == set(EVENTOS)

#: Qué marca del `app_metadata` es la baja de cada mail.
MARCA_DE_BAJA = {"resumen": BAJA_RESUMEN, "novedades": BAJA_NOVEDADES}


class MailsController(Controller):
    path = "/mails"

    SECRET_HEADER = "X-Cron-Secret"

    def _verify_secret(self, request: Request) -> None:
        expected = settings.documents_alert_secret
        recibido = request.headers.get(self.SECRET_HEADER) or ""
        if not expected:
            raise NotAuthorizedException("El barrido no está configurado.")
        if not recibido or not hmac.compare_digest(recibido, expected):
            raise NotAuthorizedException("Invalid secret token.")

    @post("/envios", status_code=200)
    async def registrar_envios(self, request: Request, data: Envios) -> Dict[str, int]:
        """Anota los mails que salieron. Repetir un id no duplica."""
        self._verify_secret(request)
        if not data.envios:
            return {"registrados": 0}
        filas = [
            {"id": str(e.id), "user_id": str(e.user_id) if e.user_id else None, "tipo": e.tipo, "clave": e.clave}
            for e in data.envios
        ]

        def _guardar() -> int:
            r = (
                SupabaseManager.get_service_client().table("mail_envios")
                .upsert(filas, on_conflict="id", ignore_duplicates=True).execute()
            )
            return len(r.data or [])

        return {"registrados": await asyncio.to_thread(_guardar)}

    @post("/eventos", status_code=200)
    async def registrar_evento(self, request: Request, data: Evento) -> Dict[str, bool]:
        """
        Anota una apertura o un clic. Si el envío no existe —el link de una copia vieja, o
        un evento que le ganó al registro del envío— no se anota y no es un error: del
        otro lado hay un piloto esperando una imagen o una redirección.
        """
        self._verify_secret(request)

        def _guardar() -> bool:
            try:
                SupabaseManager.get_service_client().table("mail_eventos").insert({
                    "envio_id": str(data.envio_id), "tipo": data.tipo, "destino": data.destino,
                }).execute()
                return True
            except Exception:
                return False

        return {"registrado": await asyncio.to_thread(_guardar)}

    @get("/novedades/pendientes")
    async def novedades_pendientes(self, request: Request, clave: str) -> List[Dict[str, Any]]:
        """A quién le toca la tanda `clave` de novedades, con lo que el mail necesita."""
        self._verify_secret(request)
        if not clave or len(clave) > 40:
            raise ValidationException("clave es obligatoria (hasta 40 caracteres)")

        def _ya_enviados() -> set:
            r = (
                SupabaseManager.get_service_client().table("mail_envios")
                .select("user_id").eq("tipo", "novedades").eq("clave", clave).execute()
            )
            return {str(f["user_id"]) for f in (r.data or []) if f.get("user_id")}

        usuarios, enviados, perfiles, vuelos = await asyncio.gather(
            asyncio.to_thread(_usuarios_completos),
            asyncio.to_thread(_ya_enviados),
            asyncio.to_thread(lambda: _todas("profiles", "id,first_name,license_type")),
            asyncio.to_thread(lambda: _todas("flights", "user_id")),
        )
        perfil_de = {str(p["id"]): p for p in perfiles}
        con_vuelos = {str(v["user_id"]) for v in vuelos}
        salida = []
        for e in pendientes_de_novedades(usuarios, enviados):
            perfil = perfil_de.get(e["user_id"]) or {}
            salida.append({
                **e,
                "first_name": perfil.get("first_name") or None,
                "license_type": perfil.get("license_type"),
                "tiene_vuelos": e["user_id"] in con_vuelos,
            })
        return salida

    @post("/baja", status_code=200)
    async def baja(self, request: Request, data: Baja) -> Dict[str, Any]:
        """
        Da de baja (o vuelve a suscribir) de un tipo de mail. El frontend ya verificó el
        link firmado: acá sólo llega con el secreto de los barridos.
        """
        self._verify_secret(request)
        marca = MARCA_DE_BAJA[data.tipo]
        await asyncio.to_thread(lambda: _escribir_meta(str(data.user_id), {marca: data.baja}))
        return {"tipo": data.tipo, "baja": data.baja}
