from litestar import Controller, get, post, delete, Request
from litestar.exceptions import ValidationException, NotFoundException, PermissionDeniedException
from supabase import Client
from typing import List, Dict, Any
from uuid import UUID
from src.models.transaction import Transaction, TransactionCreate
from src.auth.guards import auth_guard

class TransactionsController(Controller):
    path = "/transactions"
    guards = [auth_guard]

    @get()
    async def list_transactions(self, request: Request, supabase_client: Client) -> List[Transaction]:
        """Fetch all transactions for the current user."""
        user_id = str(request.state.user.id)
        response = supabase_client.table("transactions").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
        return [Transaction(**data) for data in response.data]

    @post("/deposit")
    async def create_deposit(self, request: Request, supabase_client: Client, data: TransactionCreate) -> Transaction:
        """Create a new deposit or withdrawal transaction."""
        user_id = str(request.state.user.id)
        if data.amount == 0:
            raise ValidationException("El monto de la transacción no puede ser cero.")

        tx_type = "deposit" if data.amount > 0 else "charge"
        default_desc = "Carga de saldo" if data.amount > 0 else "Retiro de saldo"

        insert_data = {
            "user_id": user_id,
            "amount": float(data.amount),
            "type": tx_type,
            "description": data.description or default_desc,
        }

        response = supabase_client.table("transactions").insert(insert_data).execute()
        return Transaction(**response.data[0])

    @delete("/{transaction_id:uuid}")
    async def delete_transaction(self, request: Request, supabase_client: Client, transaction_id: UUID) -> Dict[str, Any]:
        """Delete a specific transaction."""
        user_id = str(request.state.user.id)
        # Check ownership
        tx_resp = supabase_client.table("transactions").select("user_id").eq("id", str(transaction_id)).execute()
        if not tx_resp.data:
            raise NotFoundException("Transacción no encontrada")
        if tx_resp.data[0]["user_id"] != user_id:
            raise PermissionDeniedException("No tienes permiso para eliminar esta transacción")

        supabase_client.table("transactions").delete().eq("id", str(transaction_id)).execute()
        return {"success": True}
