from litestar import Controller, get, post
from litestar.exceptions import NotFoundException, NotAuthorizedException
from supabase import Client
from typing import Dict, Any
from datetime import datetime, timezone
from src.supabase_client import SupabaseManager
from src.controllers.flight_packs import FlightPacksController
from src.models.flight import Flight
from src.models.transaction import Transaction
from src.config import settings

class WhatsAppController(Controller):
    path = "/whatsapp"

    def _verify_secret(self, secret: str) -> None:
        expected = getattr(settings, "whatsapp_webhook_secret", None) or "shared-vector-secret-2026"
        if secret != expected and secret != settings.supabase_anon_key:
            raise NotAuthorizedException("Invalid secret token.")

    @get("/user-data")
    async def get_user_data_by_phone(self, phone: str, secret: str) -> Dict[str, Any]:
        """Fetch dashboard context for a user by their WhatsApp phone number."""
        self._verify_secret(secret)

        service_client = SupabaseManager.get_service_client()
        
        # Normalize phone (digits only)
        clean_phone = "".join(c for c in phone if c.isdigit())
        print(f"[DEBUG WHATSAPP] Fetching user data for phone: {phone} (clean: {clean_phone})")
        print(f"[DEBUG WHATSAPP] Service role key configured: {bool(settings.supabase_service_role_key)}")
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
            print(f"[DEBUG WHATSAPP] Profile query returned no data for phone: {clean_phone}")
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

        # 6. Documents, so the copilot can answer "¿cuándo vence mi CMA?" without
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
            "documents": documents_data
        }

    @get("/chat-history")
    async def get_chat_history(self, phone: str, secret: str) -> Dict[str, Any]:
        """Fetch chat history for a WhatsApp phone number."""
        self._verify_secret(secret)
        
        service_client = SupabaseManager.get_service_client()
        clean_phone = "".join(c for c in phone if c.isdigit())
        
        resp = service_client.table("whatsapp_chats").select("history").eq("phone", clean_phone).execute()
        if not resp.data:
            return {"history": []}
        return {"history": resp.data[0]["history"]}

    @post("/chat-history")
    async def update_chat_history(self, phone: str, secret: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Update chat history for a WhatsApp phone number."""
        self._verify_secret(secret)
        
        service_client = SupabaseManager.get_service_client()
        clean_phone = "".join(c for c in phone if c.isdigit())
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
