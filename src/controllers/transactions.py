from litestar import Controller, get, post, Request
from litestar.exceptions import ValidationException
from supabase import Client
from typing import List
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
        """Create a new deposit transaction."""
        user_id = str(request.state.user.id)
        if data.amount <= 0:
            raise ValidationException("El monto del depósito debe ser mayor a cero.")

        insert_data = {
            "user_id": user_id,
            "amount": float(data.amount),
            "type": "deposit",
            "description": data.description or "Carga de saldo",
        }

        response = supabase_client.table("transactions").insert(insert_data).execute()
        return Transaction(**response.data[0])
