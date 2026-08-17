"""
Vencimientos que se calculan solos, contados desde un vuelo.

Dos reglas, con anclas distintas:

- `'ultimo_vuelo'` cuenta desde el vuelo **más reciente**, así que la fecha se corre
  con cada vuelo nuevo. Es "60 días sin volar y necesitás adaptación".
- `'vuelo_ancla'` cuenta desde **un vuelo puntual** que el piloto eligió. La fecha no
  se mueve salvo que se corrija la de ese vuelo. Es "24 meses desde aquel repaso".

Este módulo es **el único escritor** de `documents.expiry_date` para esas filas, y
corre cada vez que los vuelos de un piloto cambian —alta, edición y baja— y cada vez
que se crea o edita un documento con regla derivada.

El porqué del modelo —columna cacheada en vez de derivar al leer— está en
`migrations/011_documents_expiry_rule.sql`; el porqué de la referencia blanda al
vuelo ancla, en la 013. Lo que importa acá:

- **Nunca voltea la escritura que lo disparó.** Misma política que `_refresh_audit`:
  el vuelo ya está guardado cuando esto corre, y perder una entrada del libro porque
  no se pudo refrescar una fecha derivada es un mal negocio. Los llamadores usan
  `recompute_for_user_safe`.
- **Sólo escribe lo que cambió.** El trigger `documents_reset_alerts` borra la marca
  de aviso cuando `expiry_date` cambia, así que un update de más resetea avisos que
  estaban bien puestos y el piloto recibe el mismo aviso dos veces.
- **Un ancla borrada congela el documento en `'fijo'`**, con la última fecha
  calculada, en vez de dejarlo sin vencimiento. Un documento que bloqueaba el vuelo
  no puede dejar de bloquear en silencio porque se borró un vuelo de hace dos años.
"""

import calendar
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:  # pragma: no cover
    # Sólo para los tipos. `derived_expiry` es aritmética pura y `test_audit_engine.py`
    # corre sin dependencias instaladas —es su gracia—, así que importar el SDK a
    # nivel de módulo dejaría toda la suite del backend sin poder arrancar.
    from supabase import Client

#: Las dos reglas cuya fecha escribe este módulo. `'fijo'` la escribe el piloto.
LAST_FLIGHT_RULE = "ultimo_vuelo"
ANCHOR_RULE = "vuelo_ancla"
DERIVED_RULES = (LAST_FLIGHT_RULE, ANCHOR_RULE)


def sumar_offset(desde: date, cantidad: int, unidad: str) -> date:
    """
    `desde` más `cantidad` días o meses.

    **Los meses no son 30 días.** El repaso de 61.135 son 24 meses calendario, y
    resolverlo con 730 días se corre uno o dos según los bisiestos y los meses de 31.
    En un vencimiento regulatorio, uno o dos días es la diferencia entre poder volar
    y no.

    Sumar meses satura el día al último del mes destino —31 de enero + 1 mes es el 28
    o 29 de febrero—, que es la convención de `dateutil.relativedelta` y la que
    espera cualquiera. Va a mano porque `dateutil` no está en los requirements y no
    vale traer una dependencia por doce líneas.
    """
    if unidad != "meses":
        return desde + timedelta(days=cantidad)

    # Meses contados desde cero para que el módulo funcione con enero.
    total = (desde.year * 12 + (desde.month - 1)) + cantidad
    year, month = divmod(total, 12)
    month += 1
    # Sin esto, 31 de enero + 1 mes intentaría construir el 31 de febrero.
    day = min(desde.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def derived_expiry(
    anchor: Optional[date], offset: Optional[int], unidad: str = "dias"
) -> Optional[date]:
    """
    La fecha de vencimiento, o `None` si todavía no hay de dónde calcularla.

    Sin ancla el resultado es `None`, que desde la migración 007 significa "no
    vence": ni vencido ni avisos. Es lo correcto para `'ultimo_vuelo'` en una cuenta
    sin vuelos — una cuenta que arranca con el último vuelo, sin ningún vuelo, no
    arrancó. Para `'vuelo_ancla'` el ancla faltante significa otra cosa —el vuelo se
    borró— y ese caso lo resuelve `recompute_for_user` congelando el documento, sin
    llegar hasta acá.
    """
    if anchor is None or not offset:
        return None
    return sumar_offset(anchor, offset, unidad)


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


def _anchor_flight_dates(
    supabase_client: "Client", user_id: str, flight_ids: List[str]
) -> Dict[str, date]:
    """
    Las fechas de los vuelos ancla, por id. **Los que faltan es porque se borraron.**

    Una sola consulta con `in_` y no una por documento: un piloto puede tener varias
    reglas ancladas y esto corre en cada alta de vuelo.
    """
    if not flight_ids:
        return {}

    response = (
        supabase_client.table("flights")
        .select("id, date")
        .eq("user_id", user_id)
        .in_("id", flight_ids)
        .execute()
    )
    return {
        str(row["id"]): date.fromisoformat(str(row["date"])[:10])
        for row in (response.data or [])
        if row.get("date")
    }


def recompute_for_user(supabase_client: "Client", user_id: str) -> int:
    """
    Recalcula los vencimientos derivados del piloto. Devuelve cuántas filas cambió.

    Arranca por los documentos y no por los vuelos: la enorme mayoría de los pilotos
    no tiene ninguna regla cargada, y para esos esto cuesta una sola consulta que
    vuelve vacía. Recién si hay reglas se buscan las anclas, y sólo las que hagan
    falta —el vuelo más reciente para `'ultimo_vuelo'`, los vuelos señalados para
    `'vuelo_ancla'`—.
    """
    documents = (
        supabase_client.table("documents")
        .select(
            "id, expiry_rule, expiry_date, expiry_offset_days, expiry_offset_unit, "
            "expiry_anchor_flight_id"
        )
        .eq("user_id", user_id)
        .in_("expiry_rule", list(DERIVED_RULES))
        .execute()
    )
    rows: List[Dict[str, Any]] = documents.data or []
    if not rows:
        return 0

    last_flight: Optional[date] = None
    if any(row.get("expiry_rule") == LAST_FLIGHT_RULE for row in rows):
        last_flight = _last_flight_date(supabase_client, user_id)

    anclas = _anchor_flight_dates(
        supabase_client,
        user_id,
        [
            str(row["expiry_anchor_flight_id"])
            for row in rows
            if row.get("expiry_rule") == ANCHOR_RULE and row.get("expiry_anchor_flight_id")
        ],
    )

    changed = 0
    for row in rows:
        actual = str(row.get("expiry_date"))[:10] if row.get("expiry_date") else None
        unidad = row.get("expiry_offset_unit") or "dias"

        if row.get("expiry_rule") == ANCHOR_RULE:
            anchor_id = str(row.get("expiry_anchor_flight_id") or "")
            if anchor_id not in anclas:
                # El vuelo ancla ya no existe. **Congelar, no borrar.** El documento
                # se queda con la última fecha calculada y pasa a 'fijo': la
                # intención del piloto ("esto vence el tal día") sobrevive al borrado
                # del vuelo, y si quiere lo re-apunta. Dejarlo sin fecha haría que un
                # documento que bloqueaba el vuelo dejara de bloquear en silencio.
                # Ver el comentario de la migración 013 sobre por qué no hay FK.
                (
                    supabase_client.table("documents")
                    .update({
                        "expiry_rule": "fijo",
                        "expiry_offset_days": None,
                        "expiry_anchor_flight_id": None,
                    })
                    .eq("id", row["id"])
                    .eq("user_id", user_id)
                    .execute()
                )
                changed += 1
                continue
            anchor = anclas[anchor_id]
        else:
            anchor = last_flight

        nueva = derived_expiry(anchor, row.get("expiry_offset_days"), unidad)
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
