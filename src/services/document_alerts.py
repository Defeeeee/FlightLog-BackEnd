"""
Expiry alert scheduling for pilot documents (Fase 4).

Pure date arithmetic, kept out of the controller so the "should this fire today"
decision can be reasoned about on its own — it is the part that, if wrong,
either spams a pilot every morning for two months or stays silent until their
medical has already lapsed.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

#: Bucket used once a document is already past its expiry date.
EXPIRED_BUCKET = 0


def days_until(expiry: date, today: Optional[date] = None) -> int:
    return (expiry - (today or date.today())).days


def applicable_threshold(days_remaining: int, thresholds: List[int]) -> Optional[int]:
    """
    Which alert bucket a document currently sits in.

    Returns the *tightest* threshold already crossed, so a document 20 days out
    with 60/30/7 configured reports 30, not 60. Anything past its expiry reports
    `EXPIRED_BUCKET`, which is how the sweep gets to say "venció" exactly once
    rather than repeating the 7-day warning forever.

    None means no alert is due yet.
    """
    if days_remaining < 0:
        return EXPIRED_BUCKET

    crossed = [t for t in thresholds if days_remaining <= t]
    return min(crossed) if crossed else None


def should_alert(document: Dict[str, Any], today: Optional[date] = None) -> Optional[int]:
    """
    The threshold to notify for, or None if nothing is due.

    Fires only when the document has moved into a *tighter* bucket than the one
    already sent. `last_alert_threshold` is reset to NULL by a database trigger
    whenever the expiry date changes, so renewing a document re-arms the whole
    60/30/7 ladder without any bookkeeping here.
    """
    raw_expiry = document.get("expiry_date")
    if not raw_expiry:
        return None

    expiry = raw_expiry if isinstance(raw_expiry, date) else date.fromisoformat(str(raw_expiry)[:10])
    thresholds = sorted(document.get("alert_days") or [60, 30, 7], reverse=True)

    current = applicable_threshold(days_until(expiry, today), thresholds)
    if current is None:
        return None

    already = document.get("last_alert_threshold")
    if already is None or already > current:
        return current
    return None


def format_alert(document: Dict[str, Any], threshold: int, first_name: Optional[str] = None) -> str:
    """The WhatsApp body for one document. Plain text, WhatsApp-flavoured bold."""
    name = document.get("name") or "Documento"
    expiry = str(document.get("expiry_date"))[:10]
    parts = expiry.split("-")
    pretty = f"{parts[2]}/{parts[1]}/{parts[0]}" if len(parts) == 3 else expiry

    greeting = f"Hola {first_name}, " if first_name else ""

    if threshold == EXPIRED_BUCKET:
        headline = f"*{name}* está *vencido* desde el {pretty}."
        tail = "No podés volar amparado en ese documento hasta renovarlo."
    else:
        headline = f"*{name}* vence el {pretty} — faltan {threshold} días."
        tail = (
            "Conviene sacar turno ahora."
            if threshold >= 30
            else "Queda poco margen: gestionalo esta semana."
        )

    return f"{greeting}{headline}\n\n{tail}\n\n_Aviso automático de Vector._"
