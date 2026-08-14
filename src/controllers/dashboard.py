import asyncio

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
        """
        Todo lo que el dashboard necesita, en un request y en paralelo.

        Las ocho consultas estaban encadenadas y ninguna depende de la anterior:
        alcanza con el `user_id`, que ya se tiene. Medido contra producción, una
        llamada trivial al backend (`/health`, una sola consulta) tarda ~547 ms,
        así que ocho en fila es lo que hacía lenta la pantalla más usada.

        **El cliente de supabase-py es sincrónico**, así que cada `.execute()`
        además bloqueaba el event loop: dos pilotos entrando a la vez se hacían
        cola entre ellos aunque sus consultas no tuvieran nada que ver.
        `asyncio.to_thread` las saca del loop y `gather` las junta, que arregla la
        latencia y la concurrencia de una.

        `return_exceptions=True` conserva el comportamiento anterior: cada sección
        tenía su propio try/except y una que falle no debe vaciar el resto de la
        pantalla.

        **Pero una sección que falla ya no se calla.** Devolver `[]` es una
        afirmación: "no hay filas". Cuando lo que pasó es "no pude preguntar", el
        frontend la creía y sacaba conclusiones sobre el piloto —el semáforo le
        decía "no tenés certificado médico" a alguien que sí lo tiene cargado—.
        `unavailable` lleva los nombres de las secciones que fallaron para que del
        otro lado se pueda distinguir "no hay" de "no sé".
        """
        user_id = str(request.state.user.id)

        def _profile():
            return supabase_client.table("profiles").select("*").eq("id", user_id).execute()

        def _aircraft():
            return supabase_client.table("aircraft").select("*").eq("user_id", user_id).execute()

        def _flights():
            return supabase_client.table("flights").select("*").eq("user_id", user_id).execute()

        def _session():
            return supabase_client.table("flight_sessions").select("*").eq("user_id", user_id).execute()

        def _transactions():
            return (
                supabase_client.table("transactions").select("*")
                .eq("user_id", user_id).order("created_at", desc=True).execute()
            )

        def _findings():
            return (
                supabase_client.table("audit_findings").select("severity, suppressed")
                .eq("user_id", user_id).execute()
            )

        def _documents():
            return (
                supabase_client.table("documents").select("*")
                .eq("user_id", user_id).order("expiry_date").execute()
            )

        (
            profile_resp, aircraft_resp, flights_resp, session_resp,
            packs_result, transactions_resp, findings_resp, documents_resp,
        ) = await asyncio.gather(
            asyncio.to_thread(_profile),
            asyncio.to_thread(_aircraft),
            asyncio.to_thread(_flights),
            asyncio.to_thread(_session),
            # Ya es async; entra directo al gather sin hilo propio.
            FlightPacksController._get_packs_with_hours(user_id, supabase_client),
            asyncio.to_thread(_transactions),
            asyncio.to_thread(_findings),
            asyncio.to_thread(_documents),
            return_exceptions=True,
        )

        unavailable: list[str] = []

        def _rows(name: str, resp) -> list:
            """
            Filas de una respuesta.

            Si esa consulta falló devuelve vacío **y anota la sección en
            `unavailable`**, que es lo que separa "el piloto no tiene documentos"
            de "no pudimos leer los documentos del piloto".
            """
            if isinstance(resp, Exception):
                print(f"Consolidated dashboard error [{name}]: {resp!r}")
                unavailable.append(name)
                return []
            return resp.data or []

        profile_rows = _rows("profile", profile_resp)
        profile = profile_rows[0] if profile_rows else None

        aircraft = _rows("aircraft", aircraft_resp)

        flights = [Flight(**data).model_dump(mode="json") for data in _rows("flights", flights_resp)]

        session_rows = _rows("session", session_resp)
        session_data = session_rows[0] if session_rows else None

        packs_data = []
        if isinstance(packs_result, Exception):
            print(f"Consolidated dashboard error [packs]: {packs_result!r}")
            unavailable.append("packs")
        else:
            packs_data = [p.model_dump(mode="json") for p in packs_result]

        transactions_data = [
            Transaction(**tx).model_dump(mode="json") for tx in _rows("transactions", transactions_resp)
        ]
        balance = sum(tx["amount"] for tx in transactions_data)

        audit_summary = {"critical": 0, "warning": 0, "suppressed": 0, "open_total": 0}
        for row in _rows("audit", findings_resp):
            if row.get("suppressed"):
                audit_summary["suppressed"] += 1
            elif row.get("severity") == "critical":
                audit_summary["critical"] += 1
            else:
                audit_summary["warning"] += 1
        audit_summary["open_total"] = audit_summary["critical"] + audit_summary["warning"]

        documents_data = _rows("documents", documents_resp)

        return {
            # Secciones que no se pudieron leer. Vacía en el caso normal.
            "unavailable": unavailable,
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
