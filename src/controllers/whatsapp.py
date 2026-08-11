from hmac import compare_digest
from litestar import Controller, Request, get, post
from litestar.exceptions import NotFoundException, NotAuthorizedException
from typing import Dict, Any
from datetime import datetime, timezone
from src.supabase_client import SupabaseManager
from src.controllers.flight_packs import FlightPacksController
from src.models.flight import Flight
from src.models.transaction import Transaction
from src.config import settings

class WhatsAppController(Controller):
    path = "/whatsapp"

    # H1.1, paso 1 de 3. El secreto pasa de la query string a un header porque
    # en la URL queda escrito en texto plano en los logs de nginx y de PM2, en
    # cada mensaje que recibe el bot, junto al teléfono del piloto.
    #
    # Esta versión acepta **las dos formas** a propósito. Cambiar los dos repos a
    # la vez corta el bot durante la ventana en que uno está desplegado y el otro
    # no — es exactamente lo que pasó el 2026-08-06 con el valor del secreto y
    # costó una hora y media. La secuencia es:
    #
    #   1. (esto) el backend acepta header y query.
    #   2. el frontend pasa a mandar el header.
    #   3. el backend deja de aceptar la query.
    #
    # El paso 3 va después de confirmar en los logs que no queda ninguna llamada
    # con `secret=` en la URL.
    # El teléfono se mueve por la misma razón y en la misma tanda. Sacar los
    # `print` no alcanzaba: **el access log de uvicorn registra la URL entera**,
    # así que mientras el número viaje en la query string queda escrito en disco
    # en cada request igual. Comprobado el 2026-08-06 — el número completo seguía
    # apareciendo dos veces en el log después de limpiar los prints.
    SECRET_HEADER = "x-vector-secret"
    PHONE_HEADER = "x-vector-phone"

    def _secret_from(self, request: Request, secret: str | None) -> str:
        return request.headers.get(self.SECRET_HEADER) or (secret or "")

    def _phone_from(self, request: Request, phone: str | None) -> str:
        return request.headers.get(self.PHONE_HEADER) or (phone or "")

    def _verify_secret(self, secret: str) -> None:
        """Guard for the WhatsApp endpoints, which read user data with the service
        role and therefore bypass RLS entirely.

        Fails closed when the secret is not configured. It used to fall back to a
        constant that lives in a public repository, and to also accept the Supabase
        anon key — which ships to every browser. Between the two, anyone with a
        pilot's phone number could read their whole logbook.

        `compare_digest` because this is a shared secret compared on every request.
        """
        expected = settings.whatsapp_webhook_secret
        if not expected:
            raise NotAuthorizedException("WhatsApp integration is not configured.")
        if not secret or not compare_digest(secret, expected):
            raise NotAuthorizedException("Invalid secret token.")

    @get("/user-data")
    async def get_user_data_by_phone(self, request: Request, phone: str | None = None, secret: str | None = None) -> Dict[str, Any]:
        """Fetch dashboard context for a user by their WhatsApp phone number."""
        self._verify_secret(self._secret_from(request, secret))

        service_client = SupabaseManager.get_service_client()
        
        # Normalize phone (digits only)
        clean_phone = "".join(c for c in self._phone_from(request, phone) if c.isdigit())
        if not clean_phone:
            raise NotFoundException("Número de teléfono inválido")

        # Query profiles
        profile_resp = service_client.table("profiles").select("*").eq("whatsapp_phone", clean_phone).execute()
        if not profile_resp.data:
            # Try alternate Argentine formats (with or without lead '9')
            if clean_phone.startswith("549"):
                alt_phone = "54" + clean_phone[3:]
                profile_resp = service_client.table("profiles").select("*").eq("whatsapp_phone", alt_phone).execute()
            elif clean_phone.startswith("54"):
                alt_phone = "549" + clean_phone[2:]
                profile_resp = service_client.table("profiles").select("*").eq("whatsapp_phone", alt_phone).execute()

        if not profile_resp.data:
            # Sin el número: que hubo una consulta que no resolvió es útil para
            # diagnosticar, de qué teléfono era no le hace falta a nadie y queda
            # escrito en el disco del server. El sufijo alcanza para correlacionar
            # con lo que reporte el piloto sin guardar el número entero.
            #
            # Largo y prefijo van además del sufijo porque **el sufijo solo no
            # alcanza para diagnosticar**: el 2026-08-11, al conectar el número de
            # producción, los últimos cuatro coincidían con el perfil guardado y
            # aun así no matcheaba. La diferencia estaba en el prefijo, y el log no
            # la mostraba. Tres dígitos de prefijo y el largo no identifican a
            # nadie —los comparten millones de números— y son justo lo que hace
            # falta para ver por qué falló la normalización.
            print(
                f"[whatsapp] consulta sin perfil: termina en …{clean_phone[-4:]}, "
                f"{len(clean_phone)} dígitos, empieza {clean_phone[:3]}"
            )
            raise NotFoundException("Usuario no registrado con ese número de WhatsApp")

        profile = profile_resp.data[0]
        user_id = profile["id"]

        # Fetch other user-scoped data using service_client
        # 1. Aircraft
        aircraft_resp = service_client.table("aircraft").select("*").eq("user_id", user_id).execute()
        aircraft = aircraft_resp.data

        # 2. Flights
        flights_resp = service_client.table("flights").select("*").eq("user_id", user_id).execute()
        flights = [Flight(**data).model_dump(mode="json") for data in flights_resp.data]

        # 3. Active Session
        session_resp = service_client.table("flight_sessions").select("*").eq("user_id", user_id).execute()
        session_data = session_resp.data[0] if session_resp.data else None

        # 4. Flight Packs
        packs_data = []
        try:
            packs = await FlightPacksController._get_packs_with_hours(user_id, service_client)
            packs_data = [p.model_dump(mode="json") for p in packs]
        except Exception as e:
            print(f"WhatsApp dashboard packs error: {str(e)}")

        # 5. Transactions & Balance
        transactions_data = []
        balance = 0.0
        try:
            transactions_resp = service_client.table("transactions").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
            transactions_data = [Transaction(**tx).model_dump(mode="json") for tx in transactions_resp.data]
            balance = sum(tx["amount"] for tx in transactions_data)
        except Exception as e:
            print(f"WhatsApp dashboard transactions error: {str(e)}")

        # 6. Logbooks, so the copilot can put a flight in the book the pilot names
        # instead of always defaulting. Without this the WhatsApp path is the only
        # way into the app that cannot choose a logbook.
        logbooks_data = []
        try:
            logbooks_resp = service_client.table("logbooks").select("*").eq("user_id", user_id).order("created_at").execute()
            logbooks_data = logbooks_resp.data or []
        except Exception as e:
            print(f"WhatsApp dashboard logbooks error: {str(e)}")

        # 7. Documents, so the copilot can answer "¿cuándo vence mi CMA?" without
        # the expiry having to live on the profile.
        documents_data = []
        try:
            documents_resp = service_client.table("documents").select("*").eq("user_id", user_id).order("expiry_date").execute()
            documents_data = documents_resp.data or []
        except Exception as e:
            print(f"WhatsApp dashboard documents error: {str(e)}")

        return {
            "profile": profile,
            "aircraft": aircraft,
            "flights": flights,
            "session": {"active": bool(session_data), "session": session_data},
            "packs": packs_data,
            "transactions": transactions_data,
            "balance": balance,
            "documents": documents_data,
            "logbooks": logbooks_data
        }

    @get("/chat-history")
    async def get_chat_history(self, request: Request, phone: str | None = None, secret: str | None = None) -> Dict[str, Any]:
        """Fetch chat history for a WhatsApp phone number."""
        self._verify_secret(self._secret_from(request, secret))
        
        service_client = SupabaseManager.get_service_client()
        clean_phone = "".join(c for c in self._phone_from(request, phone) if c.isdigit())
        
        resp = service_client.table("whatsapp_chats").select("history").eq("phone", clean_phone).execute()
        if not resp.data:
            return {"history": []}
        return {"history": resp.data[0]["history"]}

    @post("/chat-history")
    async def update_chat_history(self, request: Request, data: Dict[str, Any], phone: str | None = None, secret: str | None = None) -> Dict[str, Any]:
        """Update chat history for a WhatsApp phone number."""
        self._verify_secret(self._secret_from(request, secret))
        
        service_client = SupabaseManager.get_service_client()
        clean_phone = "".join(c for c in self._phone_from(request, phone) if c.isdigit())
        history = data.get("history", [])
        
        # Limit history to last 20 messages to keep context efficient
        history = history[-20:]
        
        # Upsert
        service_client.table("whatsapp_chats").upsert({
            "phone": clean_phone,
            "history": history,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }).execute()
        
        return {"success": True}
