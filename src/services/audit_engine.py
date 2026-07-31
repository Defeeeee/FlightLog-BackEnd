"""
Logbook audit rules (Fase 2).

The rules themselves are pure: they take the flights and the hangar as plain
dicts and return findings. Nothing here touches Supabase, so a rule can be
reasoned about — and tested — without a database.

Persistence lives in `sync_findings`, which reconciles the freshly computed set
against what is already stored. The one thing that must survive a recalculation
is the pilot's decision to suppress a finding ("those two really do overlap, it
was a ferry with a safety pilot"), which is why findings are a table and not a
view.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

# Hours are logged in ANAC tenths, so anything under half a tenth is float
# noise from summing eight columns, not a real discrepancy.
TOLERANCE_HOURS = 0.05

PIC_SIC_COLUMNS = (
    "pic_day_loc",
    "pic_day_tra",
    "pic_night_loc",
    "pic_night_tra",
    "sic_day_loc",
    "sic_day_tra",
    "sic_night_loc",
    "sic_night_tra",
)

RULE_OVERLAP = "overlap"
RULE_UNREGISTERED_AIRCRAFT = "unregistered_aircraft"
RULE_DUPLICATE = "duplicate"
RULE_INCONSISTENT_TOTAL = "inconsistent_total"

SEVERITY_CRITICAL = "critical"
SEVERITY_WARNING = "warning"


@dataclass(frozen=True)
class Finding:
    """A single rule hit. `flight_id` is None for account-level findings."""

    flight_id: Optional[str]
    rule_type: str
    severity: str
    message: str

    @property
    def key(self) -> Tuple[Optional[str], str]:
        return (self.flight_id, self.rule_type)


def _parse_ts(value: Any) -> Optional[datetime]:
    """Parses a Supabase timestamptz, tolerating the trailing 'Z' form."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _interval(flight: Dict[str, Any]) -> Optional[Tuple[datetime, datetime]]:
    """
    Takeoff/landing as a real interval.

    The frontend builds both timestamps from the same calendar date (see
    `logFlight` in the Next app), so a flight that lands after midnight comes
    back with landing *before* takeoff. Rolling it forward a day here is what
    keeps a 23:30 → 00:20 flight from looking like a 23-hour overlap with
    everything else that night.
    """
    takeoff = _parse_ts(flight.get("takeoff"))
    landing = _parse_ts(flight.get("landing"))
    if takeoff is None or landing is None:
        return None
    if landing <= takeoff:
        landing += timedelta(days=1)
    return takeoff, landing


def _normalise_route(route: Any) -> str:
    """Route without spacing or dashes: 'SADM SAEZ' and 'SADM-SAEZ' are one."""
    return re.sub(r"[\s\-]+", "", str(route or "")).upper()


def _pretty_date(flight: Dict[str, Any]) -> str:
    raw = str(flight.get("date") or "")[:10]
    parts = raw.split("-")
    return f"{parts[2]}/{parts[1]}/{parts[0]}" if len(parts) == 3 else raw or "sin fecha"


def _hhmm(moment: datetime) -> str:
    return moment.strftime("%H:%M")


def evaluate(flights: List[Dict[str, Any]], aircraft: List[Dict[str, Any]]) -> List[Finding]:
    """Runs every rule over one pilot's logbook and returns the findings."""
    duplicate_groups = _duplicate_groups(flights)

    # An exact duplicate necessarily overlaps its twin — same aircraft, same
    # times. Reporting both rules would show the pilot two critical findings for
    # one mistake and point at the vaguer of the two ("se superpone con...")
    # when the actionable one is "borrá la copia". The overlap rule is told to
    # ignore those pairs, so it still fires if the flight *also* collides with
    # some unrelated third flight.
    duplicate_pairs = {
        frozenset((str(a["id"]), str(b["id"])))
        for group in duplicate_groups
        for i, a in enumerate(group)
        for b in group[i + 1 :]
    }

    findings: List[Finding] = []
    findings.extend(_rule_overlap(flights, duplicate_pairs))
    findings.extend(_rule_unregistered_aircraft(flights, aircraft))
    findings.extend(_rule_duplicate(duplicate_groups))
    findings.extend(_rule_inconsistent_total(flights))
    return findings


def _rule_overlap(
    flights: List[Dict[str, Any]], ignore_pairs: Optional[set] = None
) -> List[Finding]:
    """
    Two flights by the same pilot that share wall-clock time.

    Sorted sweep rather than an all-pairs comparison: once a later flight starts
    after the current one has landed, nothing further down the list can overlap
    it either, so the inner loop breaks immediately. That keeps this linear in
    practice on a logbook where flights rarely overlap at all.
    """
    ignore_pairs = ignore_pairs or set()
    dated = []
    for flight in flights:
        interval = _interval(flight)
        if interval:
            dated.append((interval[0], interval[1], flight))
    dated.sort(key=lambda item: item[0])

    # Collect per flight so two mutually overlapping flights each get told.
    partners: Dict[str, List[Dict[str, Any]]] = {}
    for i, (start_a, end_a, flight_a) in enumerate(dated):
        for start_b, end_b, flight_b in dated[i + 1 :]:
            if start_b >= end_a:
                break
            if frozenset((str(flight_a["id"]), str(flight_b["id"]))) in ignore_pairs:
                continue
            if start_a < end_b and start_b < end_a:
                partners.setdefault(str(flight_a["id"]), []).append(flight_b)
                partners.setdefault(str(flight_b["id"]), []).append(flight_a)

    findings: List[Finding] = []
    by_id = {str(f["id"]): f for f in flights}
    for flight_id, others in partners.items():
        flight = by_id[flight_id]
        interval = _interval(flight)
        window = f"{_hhmm(interval[0])}–{_hhmm(interval[1])}" if interval else "sin horarios"
        if len(others) == 1:
            other = others[0]
            other_interval = _interval(other)
            other_window = f"{_hhmm(other_interval[0])}–{_hhmm(other_interval[1])}" if other_interval else "sin horarios"
            message = (
                f"Se superpone con el vuelo {_normalise_route(other.get('route')) or 'sin ruta'} "
                f"del {_pretty_date(other)} ({other_window}). Este vuelo va de {window}."
            )
        else:
            message = f"Se superpone con otros {len(others)} vuelos. Este vuelo va de {window}."
        findings.append(
            Finding(
                flight_id=flight_id,
                rule_type=RULE_OVERLAP,
                severity=SEVERITY_CRITICAL,
                message=message,
            )
        )
    return findings


def _rule_unregistered_aircraft(
    flights: List[Dict[str, Any]], aircraft: List[Dict[str, Any]]
) -> List[Finding]:
    """Flights pointing at an aircraft that isn't in the pilot's hangar."""
    known = {str(a["id"]) for a in aircraft}
    findings: List[Finding] = []

    for flight in flights:
        aircraft_id = flight.get("aircraft_id")
        if aircraft_id is None:
            message = (
                f"El vuelo del {_pretty_date(flight)} no tiene aeronave asignada. "
                "Sin matrícula no computa para las habilitaciones por tipo."
            )
        elif str(aircraft_id) not in known:
            message = (
                f"El vuelo del {_pretty_date(flight)} referencia una aeronave que ya no está "
                "en el Hangar. Volvé a cargarla o reasigná el vuelo."
            )
        else:
            continue

        findings.append(
            Finding(
                flight_id=str(flight["id"]),
                rule_type=RULE_UNREGISTERED_AIRCRAFT,
                severity=SEVERITY_WARNING,
                message=message,
            )
        )
    return findings


def _duplicate_groups(flights: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Groups of flights identical on date, route, aircraft and times."""
    groups: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    for flight in flights:
        key = (
            str(flight.get("date") or "")[:10],
            _normalise_route(flight.get("route")),
            str(flight.get("aircraft_id") or ""),
            str(flight.get("takeoff") or ""),
            str(flight.get("landing") or ""),
        )
        groups.setdefault(key, []).append(flight)

    return [group for group in groups.values() if len(group) > 1]


def _rule_duplicate(groups: List[List[Dict[str, Any]]]) -> List[Finding]:
    """
    Same date, route, aircraft and times logged more than once.

    Typically the tail of a PDF import run twice, or a double submit. Every
    member of the group is flagged — the pilot decides which one to keep, and
    flagging only the later copy would hide the pair from whichever one they
    happen to open first.
    """
    findings: List[Finding] = []
    for group in groups:
        for flight in group:
            findings.append(
                Finding(
                    flight_id=str(flight["id"]),
                    rule_type=RULE_DUPLICATE,
                    severity=SEVERITY_CRITICAL,
                    message=(
                        f"Hay {len(group)} vuelos idénticos el {_pretty_date(flight)} "
                        f"({_normalise_route(flight.get('route')) or 'sin ruta'}, mismos horarios). "
                        "Conservá uno y borrá el resto."
                    ),
                )
            )
    return findings


def _rule_inconsistent_total(flights: List[Dict[str, Any]]) -> List[Finding]:
    """
    PIC/SIC breakdown that doesn't add up to the flight time.

    The form already blocks *over*-allocation when saving, so what this catches
    retroactively is the other half: flights imported or logged before the
    breakdown existed, where the categories sum to less than the total and the
    hours silently don't appear in any ANAC column.
    """
    findings: List[Finding] = []

    for flight in flights:
        total = float(flight.get("duration") or 0)
        if total <= 0:
            continue

        assigned = sum(float(flight.get(column) or 0) for column in PIC_SIC_COLUMNS)
        delta = assigned - total

        if delta > TOLERANCE_HOURS:
            severity = SEVERITY_CRITICAL
            message = (
                f"La suma de tiempos PIC/SIC ({assigned:.1f} h) supera el total del vuelo "
                f"({total:.1f} h) del {_pretty_date(flight)}."
            )
        elif assigned <= TOLERANCE_HOURS:
            severity = SEVERITY_WARNING
            message = (
                f"El vuelo del {_pretty_date(flight)} ({total:.1f} h) no tiene desglose PIC/SIC. "
                "Esas horas no computan en ninguna columna ANAC."
            )
        elif delta < -TOLERANCE_HOURS:
            severity = SEVERITY_WARNING
            message = (
                f"Quedan {abs(delta):.1f} h sin asignar en el vuelo del {_pretty_date(flight)}: "
                f"el desglose suma {assigned:.1f} h sobre un total de {total:.1f} h."
            )
        else:
            continue

        findings.append(
            Finding(
                flight_id=str(flight["id"]),
                rule_type=RULE_INCONSISTENT_TOTAL,
                severity=severity,
                message=message,
            )
        )
    return findings


def sync_findings(supabase_client, user_id: str, findings: List[Finding]) -> Dict[str, int]:
    """
    Reconciles the computed findings against what's stored.

    Deliberately an upsert plus a delete of what no longer applies, rather than
    a wipe-and-reinsert: `suppressed` and `suppressed_reason` are the pilot's
    input, not derived data, and a wipe would silently un-suppress everything on
    the next flight logged. The upsert payload leaves both columns out so the
    ON CONFLICT update can't touch them.
    """
    now = datetime.now().astimezone().isoformat()

    existing_resp = (
        supabase_client.table("audit_findings")
        .select("id, flight_id, rule_type")
        .eq("user_id", user_id)
        .execute()
    )
    existing = existing_resp.data or []

    current_keys = {finding.key for finding in findings}
    stale_ids = [
        row["id"]
        for row in existing
        if (str(row["flight_id"]) if row["flight_id"] else None, row["rule_type"]) not in current_keys
    ]

    if stale_ids:
        supabase_client.table("audit_findings").delete().in_("id", stale_ids).execute()

    if findings:
        payload = [
            {
                "user_id": user_id,
                "flight_id": finding.flight_id,
                "rule_type": finding.rule_type,
                "severity": finding.severity,
                "message": finding.message,
                "recalculated_at": now,
            }
            for finding in findings
        ]
        supabase_client.table("audit_findings").upsert(
            payload, on_conflict="user_id,flight_id,rule_type"
        ).execute()

    return {"findings": len(findings), "removed": len(stale_ids)}


def recalculate_for_user(supabase_client, user_id: str) -> Dict[str, int]:
    """
    Recomputes the whole logbook for one pilot.

    Full recalculation instead of the incremental "this flight and the ones it
    overlaps" the plan called for. Editing a flight can *clear* a finding on a
    different flight (fix an overlap and the counterpart's finding has to go
    too), so an incremental pass has to walk the neighbours anyway — and at
    logbook scale, tens to low thousands of flights, the whole sweep is one
    query and a sorted pass. Correctness is worth more here than the round trip
    it saves.
    """
    flights_resp = supabase_client.table("flights").select("*").eq("user_id", user_id).execute()
    aircraft_resp = supabase_client.table("aircraft").select("id").eq("user_id", user_id).execute()

    findings = evaluate(flights_resp.data or [], aircraft_resp.data or [])
    return sync_findings(supabase_client, user_id, findings)
