import hmac
import datetime as dt
from datetime import date, timedelta
from typing import List, Optional

from litestar import Controller, Request, get, post
from litestar.exceptions import NotAuthorizedException
from pydantic import BaseModel

from src.config import settings
from src.supabase_client import SupabaseManager


class PendingBriefing(BaseModel):
    """Un vuelo programado para mañana, con a quién avisarle."""

    planned_id: str
    user_id: str
    date: date
    route: Optional[str] = None
    registration: Optional[str] = None
    first_name: Optional[str] = None
    email: Optional[str] = None


class FlightBriefingsController(Controller):
    """
    Los vuelos programados para mañana, para que el barrido mande el briefing.

    **Controlador aparte y no un endpoint más en `PlannedFlightsController`**, por la misma
    razón que `DocumentAlertsController` está separado: ese controlador declara
    `guards = [auth_guard]` a nivel de clase y los guards de Litestar se acumulan hacia
    abajo, así que un handler adentro no puede optar por salirse. Un cron no tiene sesión.

    Y por la misma razón que el de vencimientos, **acá sólo se lee**. El envío ocurre en el
    frontend, que es donde viven las credenciales del proveedor de correo. El backend dice
    a quién hay que avisarle; el frontend avisa.
    """

    path = "/flight-briefings"

    SECRET_HEADER = "X-Cron-Secret"

    def _secret_from(self, request: Request, secret: Optional[str]) -> str:
        """
        Cabecera primero, query string como transición — igual que en `/document-alerts`.

        **Un secreto en la URL se escribe en los logs**: el access log de nginx registra la
        URL entera, así que programar el barrido con `?secret=` lo deja en texto plano en el
        server todos los días. Ya costó una rotación una vez.
        """
        return request.headers.get(self.SECRET_HEADER) or (secret or "")

    def _verify_secret(self, secret: str) -> None:
        expected = settings.documents_alert_secret
        if not expected:
            # Fail closed: sin secreto configurado esto sería una lectura sin autenticar de
            # los planes de vuelo de todos los pilotos.
            raise NotAuthorizedException("Flight briefing sweep is not configured.")
        if not secret or not hmac.compare_digest(secret, expected):
            raise NotAuthorizedException("Invalid secret token.")

    @get("/pending")
    async def pending_briefings(
        self, request: Request, secret: Optional[str] = None, days_ahead: int = 1
    ) -> List[PendingBriefing]:
        """
        Los vuelos programados dentro de `days_ahead` días que siguen en pie.

        Por defecto **mañana**: el vuelo del sábado se decide el viernes a la noche, que es
        cuando el TAF del día ya está publicado y todavía se está a tiempo de cambiar el
        plan. Un aviso el mismo día llega tarde para eso.

        Sólo los `programado`: un plan ya completado o descartado no necesita briefing, y
        mandarlo entrenaría a ignorar el aviso.
        """
        self._verify_secret(self._secret_from(request, secret))
        service_client = SupabaseManager.get_service_client()

        objetivo = date.today() + timedelta(days=max(days_ahead, 0))
        planned_resp = (
            service_client.table("planned_flights")
            .select("id, user_id, date, route, aircraft_id, status")
            .eq("date", objetivo.isoformat())
            .eq("status", "programado")
            .is_("briefing_sent_at", "null")
            .execute()
        )
        planned = planned_resp.data or []
        if not planned:
            return []

        user_ids = list({str(p["user_id"]) for p in planned})
        profiles_resp = (
            service_client.table("profiles").select("id, first_name").in_("id", user_ids).execute()
        )
        profiles = {str(p["id"]): p for p in profiles_resp.data or []}

        aircraft_ids = [str(p["aircraft_id"]) for p in planned if p.get("aircraft_id")]
        aircraft = {}
        if aircraft_ids:
            aircraft_resp = (
                service_client.table("aircraft").select("id, registration").in_("id", aircraft_ids).execute()
            )
            aircraft = {str(a["id"]): a.get("registration") for a in aircraft_resp.data or []}

        salida: List[PendingBriefing] = []
        for p in planned:
            uid = str(p["user_id"])
            # El mail no vive en `profiles` sino en `auth.users`, así que hay que pedirlo por
            # la API de administración. Se pide uno por uno y no la lista entera: son pocos
            # por día y listar todos los usuarios para quedarse con dos es traer de más.
            email = None
            try:
                usuario = service_client.auth.admin.get_user_by_id(uid)
                email = getattr(getattr(usuario, "user", None), "email", None)
            except Exception:
                # Sin mail no hay a quién avisarle, pero el resto del barrido sigue: que un
                # piloto no tenga correo no puede dejar sin briefing a los demás.
                email = None

            salida.append(
                PendingBriefing(
                    planned_id=str(p["id"]),
                    user_id=uid,
                    date=date.fromisoformat(str(p["date"])[:10]),
                    route=p.get("route"),
                    registration=aircraft.get(str(p.get("aircraft_id"))) if p.get("aircraft_id") else None,
                    first_name=(profiles.get(uid) or {}).get("first_name"),
                    email=email,
                )
            )

        return salida

    @post("/mark-sent")
    async def mark_sent(
        self, request: Request, data: List[str], secret: Optional[str] = None
    ) -> dict:
        """
        Marca un lote de vuelos programados como notificados, para que no salgan en
        el próximo barrido si el cron reintenta. `data` es una lista de UUIDs (`planned_id`).
        """
        self._verify_secret(self._secret_from(request, secret))
        if not data:
            return {"updated": 0}

        service_client = SupabaseManager.get_service_client()
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        
        # Supabase Python client can update multiple rows by using in_ filter.
        resp = (
            service_client.table("planned_flights")
            .update({"briefing_sent_at": now})
            .in_("id", data)
            .execute()
        )
        return {"updated": len(resp.data or [])}
