from litestar import Controller, get, post, delete, Request
from litestar.exceptions import ValidationException, NotFoundException, PermissionDeniedException
from supabase import Client
from typing import Any, Dict, List, Tuple
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

    #: Descripción de la transacción que compensa un backfill. Es el marcador que
    #: permite reconocerla después: sin ella, un ajuste queda indistinguible de una
    #: carga de saldo hecha a mano.
    AJUSTE_DESC = "Ajuste por incorporación de cobros históricos"

    @get("/backfill")
    async def preview_backfill(self, request: Request, supabase_client: Client) -> Dict[str, Any]:
        """
        Cuántos vuelos quedaron sin cobro, y por cuánta plata.

        Sólo mira; no escribe nada. El botón necesita poder decir "faltan 39 vuelos,
        $X" **antes** de que el piloto acepte, porque lo que sigue toca su saldo.
        """
        user_id = str(request.state.user.id)
        faltantes, total = self._pendientes(supabase_client, user_id)
        return {
            "vuelos": len(faltantes),
            "total": round(total, 2),
            "aplicable": self._modo(supabase_client, user_id) == "balance",
        }

    @post("/backfill")
    async def aplicar_backfill(self, request: Request, supabase_client: Client) -> Dict[str, Any]:
        """
        Graba los cobros que faltan **sin mover el saldo**.

        El problema que resuelve: `_sync_flight_transaction` cobra al crear o editar
        un vuelo, así que los vuelos cargados antes de pasar a modo `balance` nunca
        generaron transacción. Sin ellas, la bitácora no puede decir cuánto salió
        cada vuelo — que es justamente lo que el piloto quiere ver.

        **El saldo no se toca, y ésa es la restricción que manda.** El saldo actual
        es correcto: refleja la plata que efectivamente entró y salió. Meter 39
        cobros retroactivos lo hundiría por una plata que ya estaba contabilizada de
        otra forma. Por eso, junto con los cobros va **una única transacción de
        ajuste por la suma exacta**, y el neto sobre el saldo es cero.

        Suena raro y no lo es: los cobros son un *registro histórico* del costo de
        cada vuelo, no un movimiento de dinero nuevo. El ajuste dice exactamente eso
        y queda visible en el listado con su descripción.

        Idempotente: sólo mira los vuelos que **no** tienen cobro, así que correrlo
        dos veces no duplica nada.
        """
        user_id = str(request.state.user.id)

        if self._modo(supabase_client, user_id) != "balance":
            raise ValidationException(
                "El backfill de cobros sólo aplica en modo saldo. En modo packs los "
                "vuelos consumen horas, no plata."
            )

        faltantes, total = self._pendientes(supabase_client, user_id)
        if not faltantes:
            return {"vuelos": 0, "total": 0.0, "ajuste": 0.0}

        supabase_client.table("transactions").insert(faltantes).execute()

        # El ajuste va **después** de los cobros: si algo falla en el insert de
        # arriba, no queda un depósito suelto inflando el saldo.
        supabase_client.table("transactions").insert({
            "user_id": user_id,
            "amount": round(total, 2),
            "type": "deposit",
            "description": f"{self.AJUSTE_DESC} ({len(faltantes)} vuelos)",
        }).execute()

        return {"vuelos": len(faltantes), "total": round(total, 2), "ajuste": round(total, 2)}

    @staticmethod
    def _modo(supabase_client: Client, user_id: str) -> str:
        resp = supabase_client.table("profiles").select("tracking_mode").eq("id", user_id).execute()
        return (resp.data[0].get("tracking_mode") or "packs") if resp.data else "packs"

    @staticmethod
    def _pendientes(supabase_client: Client, user_id: str) -> Tuple[List[Dict[str, Any]], float]:
        """
        Los cobros que habría que grabar, y su total.

        **Se saltean los vuelos cuya aeronave no tiene precio cargado.** Un cobro en
        cero no aporta nada —la bitácora lo trata como "no sé" igual, ver
        `src/lib/costos.ts`— y además ensuciaría el listado de transacciones con
        decenas de líneas en $0.

        El precio es el de hoy, y hay que decirlo: para estos vuelos viejos no existe
        el precio histórico, porque nunca se registró. Es una reconstrucción, no un
        dato.
        """
        vuelos = (
            supabase_client.table("flights")
            .select("id, duration, route, aircraft_id, discount_type, discount_amount")
            .eq("user_id", user_id).execute()
        ).data or []
        if not vuelos:
            return [], 0.0

        cobrados = {
            row["flight_id"]
            for row in (
                supabase_client.table("transactions")
                .select("flight_id").eq("user_id", user_id).eq("type", "charge").execute()
            ).data or []
            if row.get("flight_id")
        }

        precios = {
            a["id"]: float(a.get("cost_per_hour") or 0.0)
            for a in (
                supabase_client.table("aircraft").select("id, cost_per_hour")
                .eq("user_id", user_id).execute()
            ).data or []
        }

        filas: List[Dict[str, Any]] = []
        total = 0.0
        for v in vuelos:
            if v["id"] in cobrados:
                continue
            precio = precios.get(v.get("aircraft_id") or "", 0.0)
            duracion = float(v.get("duration") or 0.0)
            bruto = duracion * precio
            if bruto <= 0:
                continue

            # Mismo descuento que `_sync_flight_transaction`, para que un vuelo
            # reconstruido y uno cobrado en su momento den lo mismo.
            monto_desc = float(v.get("discount_amount") or 0.0)
            if v.get("discount_type") == "value":
                descuento = monto_desc
            elif v.get("discount_type") == "percent":
                descuento = bruto * (monto_desc / 100.0)
            else:
                descuento = 0.0

            neto = max(0.0, bruto - descuento)
            if neto <= 0:
                continue

            filas.append({
                "user_id": user_id,
                "flight_id": v["id"],
                "amount": -neto,
                "type": "charge",
                "description": f"Vuelo {v.get('route') or ''} ({duracion:.1f} hs)".strip(),
            })
            total += neto

        return filas, total

    @delete("/{transaction_id:uuid}")
    async def delete_transaction(self, request: Request, supabase_client: Client, transaction_id: UUID) -> None:
        """Delete a specific transaction."""
        user_id = str(request.state.user.id)
        # Check ownership
        tx_resp = supabase_client.table("transactions").select("user_id").eq("id", str(transaction_id)).execute()
        if not tx_resp.data:
            raise NotFoundException("Transacción no encontrada")
        if tx_resp.data[0]["user_id"] != user_id:
            raise PermissionDeniedException("No tienes permiso para eliminar esta transacción")

        supabase_client.table("transactions").delete().eq("id", str(transaction_id)).execute()
