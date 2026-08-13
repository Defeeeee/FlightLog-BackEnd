import hmac
from datetime import date, datetime, timezone
from typing import Any, Dict, List
from uuid import UUID

from litestar import Controller, delete, get, patch, post, Request
from litestar.exceptions import NotAuthorizedException, NotFoundException, ValidationException
from supabase import Client

from src.auth.guards import auth_guard
from src.config import settings
from src.models.document import DOCUMENT_KINDS, Document, DocumentCreate, DocumentUpdate, PendingAlert
from src.services import document_alerts
from src.supabase_client import SupabaseManager


class DocumentsController(Controller):
    """CRUD over the pilot's own documents. Scoped by RLS like everything else."""

    path = "/documents"
    guards = [auth_guard]

    @get()
    async def list_documents(self, request: Request, supabase_client: Client) -> List[Document]:
        """Documents ordered by how soon they expire — the only useful order."""
        user_id = str(request.state.user.id)
        response = (
            supabase_client.table("documents")
            .select("*")
            .eq("user_id", user_id)
            .order("expiry_date")
            .execute()
        )
        return [Document(**row) for row in response.data or []]

    @post()
    async def create_document(
        self, request: Request, supabase_client: Client, data: DocumentCreate
    ) -> Document:
        if data.kind not in DOCUMENT_KINDS:
            raise ValidationException(f"kind must be one of {', '.join(DOCUMENT_KINDS)}")

        insert_data = data.model_dump(mode="json")
        insert_data["user_id"] = str(request.state.user.id)

        response = supabase_client.table("documents").insert(insert_data).execute()
        return Document(**response.data[0])

    @patch("/{document_id:uuid}")
    async def update_document(
        self, request: Request, supabase_client: Client, document_id: UUID, data: DocumentUpdate
    ) -> Document:
        user_id = str(request.state.user.id)
        update_data = data.model_dump(exclude_unset=True, mode="json")

        if "kind" in update_data and update_data["kind"] not in DOCUMENT_KINDS:
            raise ValidationException(f"kind must be one of {', '.join(DOCUMENT_KINDS)}")
        if not update_data:
            raise ValidationException("No fields to update")

        response = (
            supabase_client.table("documents")
            .update(update_data)
            .eq("id", str(document_id))
            .eq("user_id", user_id)
            .execute()
        )
        if not response.data:
            raise NotFoundException(f"Document with ID {document_id} not found")
        return Document(**response.data[0])

    @delete("/{document_id:uuid}")
    async def delete_document(
        self, request: Request, supabase_client: Client, document_id: UUID
    ) -> None:
        user_id = str(request.state.user.id)
        response = (
            supabase_client.table("documents")
            .delete()
            .eq("id", str(document_id))
            .eq("user_id", user_id)
            .execute()
        )
        if not response.data:
            raise NotFoundException(f"Document with ID {document_id} not found")


class DocumentAlertsController(Controller):
    """
    The daily expiry sweep.

    Kept apart from `DocumentsController` because these run across *every* user
    under the service role, so they authenticate with a shared secret instead of
    a session — and Litestar guards accumulate down the layers, so a handler
    inside the guarded controller could not opt out of `auth_guard`.

    Split into read-then-mark on purpose: the backend has no WhatsApp
    credentials (they live in the Next app), so delivery happens in the frontend
    cron, which only calls `/sent` once Kapso has accepted the message. Marking
    the document as notified here, before it was actually delivered, would burn
    the 60-day warning on a failed send and never retry it.
    """

    path = "/document-alerts"

    SECRET_HEADER = "X-Cron-Secret"

    def _secret_from(self, request: Request, secret: str | None) -> str:
        """
        Cabecera primero, query string como transición.

        **Un secreto en la URL se escribe en los logs.** El access log de nginx y
        el de uvicorn registran la URL entera, así que programar el barrido diario
        con `?secret=` sería dejarlo en texto plano en el server todos los días.
        Ya costó una rotación: durante el plan 07, un log pegado en el chat para
        diagnosticar otra cosa traía el secreto del webhook en la URL.

        Se aceptan las dos formas a propósito, igual que en `H1.1`. El frontend y
        el backend se despliegan por separado: exigir la cabecera de entrada
        cortaría el barrido en la ventana entre un deploy y el otro. **El tercer
        paso —dejar de aceptar el query string— va después** de confirmar en los
        logs que no queda ninguna llamada vieja.
        """
        return request.headers.get(self.SECRET_HEADER) or (secret or "")

    def _verify_secret(self, secret: str) -> None:
        expected = settings.documents_alert_secret
        if not expected:
            # Fail closed: without a configured secret this endpoint would be an
            # unauthenticated read across every pilot's documents.
            raise NotAuthorizedException("Document alert sweep is not configured.")
        if not secret or not hmac.compare_digest(secret, expected):
            raise NotAuthorizedException("Invalid secret token.")

    @get("/pending")
    async def pending_alerts(self, request: Request, secret: str | None = None) -> List[PendingAlert]:
        """Documents that have crossed into a new alert bucket since last run."""
        self._verify_secret(self._secret_from(request, secret))
        service_client = SupabaseManager.get_service_client()

        documents_resp = service_client.table("documents").select("*").execute()
        documents = documents_resp.data or []
        if not documents:
            return []

        user_ids = list({str(doc["user_id"]) for doc in documents})
        profiles_resp = (
            service_client.table("profiles")
            .select("id, first_name, whatsapp_phone")
            .in_("id", user_ids)
            .execute()
        )
        profiles = {str(p["id"]): p for p in profiles_resp.data or []}

        today = date.today()
        pending: List[PendingAlert] = []

        for doc in documents:
            threshold = document_alerts.should_alert(doc, today)
            if threshold is None:
                continue

            profile = profiles.get(str(doc["user_id"]), {})
            expiry = date.fromisoformat(str(doc["expiry_date"])[:10])

            pending.append(
                PendingAlert(
                    document_id=doc["id"],
                    user_id=doc["user_id"],
                    name=doc["name"],
                    kind=doc.get("kind") or "otro",
                    expiry_date=expiry,
                    threshold=threshold,
                    days_remaining=document_alerts.days_until(expiry, today),
                    whatsapp_phone=profile.get("whatsapp_phone"),
                    first_name=profile.get("first_name"),
                    message=document_alerts.format_alert(doc, threshold, profile.get("first_name")),
                )
            )

        return pending

    @post("/{document_id:uuid}/sent")
    async def mark_alert_sent(
        self,
        request: Request,
        document_id: UUID,
        threshold: int,
        message_id: str | None = None,
        secret: str | None = None,
    ) -> Dict[str, Any]:
        """
        Records that `threshold` was handed to WhatsApp, so it isn't sent again.

        `message_id` es el wamid que devolvió Meta al aceptar el envío, y es lo que
        después permite deshacer esta marca: el webhook de `failed` sólo trae ese
        id. Es opcional a propósito —si el envío se aceptó pero la respuesta no
        traía id, marcar igual es mejor que mandarlo de nuevo todos los días— pero
        un documento marcado sin id **no se puede reintentar automáticamente**.
        """
        self._verify_secret(self._secret_from(request, secret))
        service_client = SupabaseManager.get_service_client()

        response = (
            service_client.table("documents")
            .update(
                {
                    "last_alert_threshold": threshold,
                    "last_alert_at": datetime.now(timezone.utc).isoformat(),
                    "last_alert_message_id": message_id,
                }
            )
            .eq("id", str(document_id))
            .execute()
        )
        if not response.data:
            raise NotFoundException(f"Document with ID {document_id} not found")
        return {"success": True, "document_id": str(document_id), "threshold": threshold}

    @post("/failed")
    async def mark_alert_failed(
        self, request: Request, message_id: str, secret: str | None = None
    ) -> Dict[str, Any]:
        """
        Deshace la marca de un aviso que Meta terminó no entregando.

        Kapso acepta el envío y responde 2xx mucho antes de que Meta resuelva la
        entrega. Cuando esa resolución es `failed`, el documento ya quedó marcado y
        `should_alert` no vuelve a disparar hasta el umbral siguiente: el aviso de
        los 60 días se pierde entero y el piloto se entera un mes tarde. Limpiar la
        marca devuelve el documento al estado de "nunca avisado" y el barrido del
        día siguiente lo reintenta solo.

        **No es un error que ningún documento coincida.** Meta manda un status por
        cada mensaje que sale, incluidos los del copiloto, y a este endpoint le
        llegan todos los `failed`. Un id desconocido responde 200 con
        `matched: false` — devolver 404 haría que el webhook loguee un fallo por
        cada respuesta del copiloto que no se entregó.

        Tampoco se restaura el umbral anterior: `should_alert` recalcula el bucket
        que corresponde hoy a partir de la fecha, así que dejar las columnas en NULL
        es suficiente y no hay que llevar historia.
        """
        self._verify_secret(self._secret_from(request, secret))
        if not message_id:
            raise ValidationException("message_id is required")

        service_client = SupabaseManager.get_service_client()
        response = (
            service_client.table("documents")
            .update(
                {
                    "last_alert_threshold": None,
                    "last_alert_at": None,
                    "last_alert_message_id": None,
                }
            )
            .eq("last_alert_message_id", message_id)
            .execute()
        )

        matched = list(response.data or [])
        if matched:
            # Vale un log: es un aviso que un piloto no recibió, y la única señal de
            # que el canal está fallando para alguien en particular.
            print(
                f"[document-alerts] entrega fallida, marca limpiada para "
                f"{len(matched)} documento(s): {[d.get('id') for d in matched]}"
            )
        return {"success": True, "matched": bool(matched), "cleared": len(matched)}
