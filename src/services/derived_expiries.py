"""
Vencimientos que se calculan solos, a partir de la fecha del último vuelo.

Un documento con `expiry_rule = 'ultimo_vuelo'` no tiene fecha propia: tiene un
offset en días sobre el vuelo más reciente del piloto. Este módulo es **el único
escritor** de `documents.expiry_date` para esas filas, y corre cada vez que los
vuelos de un piloto cambian.

El porqué del modelo —columna cacheada en vez de derivar al leer— está escrito en
`migrations/011_documents_expiry_rule.sql`. Lo que importa acá:

- **Nunca voltea la escritura que lo disparó.** Misma política que `_refresh_audit`:
  el vuelo ya está guardado cuando esto corre, y perder una entrada del libro porque
  no se pudo refrescar una fecha derivada es un mal negocio. Los llamadores usan
  `recompute_for_user_safe`.
- **Sólo escribe lo que cambió.** El trigger `documents_reset_alerts` borra la marca
  de aviso cuando `expiry_date` cambia, así que un update de más resetea avisos que
  estaban bien puestos y el piloto recibe el mismo aviso dos veces.
"""

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:  # pragma: no cover
    # Sólo para los tipos. `derived_expiry` es aritmética pura y `test_audit_engine.py`
    # corre sin dependencias instaladas —es su gracia—, así que importar el SDK a
    # nivel de módulo dejaría toda la suite del backend sin poder arrancar.
    from supabase import Client

DERIVED_RULE = "ultimo_vuelo"


def derived_expiry(last_flight: Optional[date], offset_days: Optional[int]) -> Optional[date]:
    """
    La fecha de vencimiento, o `None` si todavía no hay de dónde calcularla.

    Sin vuelos no hay ancla y el resultado es `None`, que desde la migración 007
    significa "no vence": ni vencido ni avisos. Es lo correcto — una cuenta que
    arranca con el último vuelo, sin ningún vuelo, no arrancó.
    """
    if last_flight is None or not offset_days:
        return None
    return last_flight + timedelta(days=offset_days)


def _last_flight_date(supabase_client: "Client", user_id: str) -> Optional[date]:
    """
    La fecha del vuelo más reciente del piloto, o `None` si no tiene ninguno.

    `date` y no `takeoff`: es la columna que el resto del sistema trata como "el día
    del vuelo" —la recencia, el heatmap, la auditoría— y la única que existe para
    los vuelos importados sin hora.
    """
    response = (
        supabase_client.table("flights")
        .select("date")
        .eq("user_id", user_id)
        .order("date", desc=True)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    if not rows or not rows[0].get("date"):
        return None
    return date.fromisoformat(str(rows[0]["date"])[:10])


def recompute_for_user(supabase_client: "Client", user_id: str) -> int:
    """
    Recalcula los vencimientos derivados del piloto. Devuelve cuántos cambiaron.

    Arranca por los documentos y no por los vuelos: la enorme mayoría de los pilotos
    no tiene ninguna regla cargada, y para esos esto cuesta una sola consulta que
    vuelve vacía. Recién si hay reglas se busca el ancla.
    """
    documents = (
        supabase_client.table("documents")
        .select("id, expiry_date, expiry_offset_days")
        .eq("user_id", user_id)
        .eq("expiry_rule", DERIVED_RULE)
        .execute()
    )
    rows: List[Dict[str, Any]] = documents.data or []
    if not rows:
        return 0

    last_flight = _last_flight_date(supabase_client, user_id)

    changed = 0
    for row in rows:
        nueva = derived_expiry(last_flight, row.get("expiry_offset_days"))
        actual = str(row.get("expiry_date"))[:10] if row.get("expiry_date") else None
        objetivo = nueva.isoformat() if nueva else None

        # Sin esta guarda, cada vuelo reescribe la misma fecha y el trigger
        # `documents_reset_alerts` borra la marca del último aviso. El piloto
        # recibe de nuevo el aviso de los 30 días por haber cargado un vuelo.
        if actual == objetivo:
            continue

        (
            supabase_client.table("documents")
            .update({"expiry_date": objetivo})
            .eq("id", row["id"])
            .eq("user_id", user_id)
            .execute()
        )
        changed += 1

    return changed


def recompute_for_user_safe(supabase_client: "Client", user_id: str) -> None:
    """
    `recompute_for_user` que no puede voltear al que lo llamó.

    Una corrida fallida deja una fecha vieja hasta el próximo cambio de vuelos. Es
    un precio aceptable; perder el vuelo que el piloto acaba de cargar no lo es.
    """
    try:
        recompute_for_user(supabase_client, user_id)
    except Exception as exc:
        print(f"Derived expiry recompute failed for user {user_id}: {exc!r}")
