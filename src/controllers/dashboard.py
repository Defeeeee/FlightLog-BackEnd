from litestar import Controller, get, Request
from supabase import Client
from typing import Dict, Any
from src.auth.guards import auth_guard
from src.controllers.flight_packs import FlightPacksController
from src.models.flight import Flight
from src.models.transaction import Transaction

class DashboardController(Controller):
    path = "/dashboard"
    guards = [auth_guard]

    @get()
    async def get_dashboard_data(self, request: Request, supabase_client: Client) -> Dict[str, Any]:
        """Fetch all data needed for the dashboard in a single optimized request."""
        user_id = str(request.state.user.id)
        
        # 1. Profile
        profile_resp = supabase_client.table("profiles").select("*").eq("id", user_id).execute()
        profile = profile_resp.data[0] if profile_resp.data else None
        
        # 2. Aircraft
        aircraft_resp = supabase_client.table("aircraft").select("*").eq("user_id", user_id).execute()
        aircraft = aircraft_resp.data

        # 3. Flights
        flights_resp = supabase_client.table("flights").select("*").eq("user_id", user_id).execute()
        flights = [Flight(**data).model_dump(mode="json") for data in flights_resp.data]
        
        # 4. Active Session
        session_resp = supabase_client.table("flight_sessions").select("*").eq("user_id", user_id).execute()
        session_data = session_resp.data[0] if session_resp.data else None
        
        # 5. Flight Packs (Static call)
        packs_data = []
        try:
            packs = await FlightPacksController._get_packs_with_hours(user_id, supabase_client)
            packs_data = [p.model_dump(mode="json") for p in packs]
        except Exception as e:
            print(f"Consolidated dashboard packs error: {str(e)}")
            
        # 6. Transactions & Balance
        transactions_data = []
        balance = 0.0
        try:
            transactions_resp = supabase_client.table("transactions").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
            transactions_data = [Transaction(**tx).model_dump(mode="json") for tx in transactions_resp.data]
            balance = sum(tx["amount"] for tx in transactions_data)
        except Exception as e:
            print(f"Consolidated dashboard transactions error: {str(e)}")

        # 7. Audit counters and documents. Folded into this endpoint rather than
        # fetched separately because the dashboard renders both the "Salud del
        # logbook" card and the expiry widget on first paint, and the nav badge
        # needs the audit count on every page anyway.
        audit_summary = {"critical": 0, "warning": 0, "suppressed": 0, "open_total": 0}
        try:
            findings_resp = supabase_client.table("audit_findings").select("severity, suppressed").eq("user_id", user_id).execute()
            for row in findings_resp.data or []:
                if row.get("suppressed"):
                    audit_summary["suppressed"] += 1
                elif row.get("severity") == "critical":
                    audit_summary["critical"] += 1
                else:
                    audit_summary["warning"] += 1
            audit_summary["open_total"] = audit_summary["critical"] + audit_summary["warning"]
        except Exception as e:
            print(f"Consolidated dashboard audit error: {str(e)}")

        documents_data = []
        try:
            documents_resp = supabase_client.table("documents").select("*").eq("user_id", user_id).order("expiry_date").execute()
            documents_data = documents_resp.data or []
        except Exception as e:
            print(f"Consolidated dashboard documents error: {str(e)}")

        return {
            "profile": profile,
            "aircraft": aircraft,
            "flights": flights,
            "session": {"active": bool(session_data), "session": session_data},
            "packs": packs_data,
            "transactions": transactions_data,
            "balance": balance,
            "audit": audit_summary,
            "documents": documents_data
        }
