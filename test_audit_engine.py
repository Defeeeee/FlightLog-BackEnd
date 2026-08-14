"""
Rule checks for the logbook audit engine.

Runs offline — the rules in `src.services.audit_engine` take plain dicts and
return findings, so none of this needs a database or a running server. Execute
with `python test_audit_engine.py`.
"""

from datetime import date

from src.services import audit_engine as engine
from src.services import derived_expiries
from src.services import document_alerts


def flight(**overrides):
    """A valid, fully-allocated flight. Tests override only what they exercise."""
    base = {
        "id": "f1",
        "date": "2026-07-20",
        "route": "SADM SAEZ",
        "aircraft_id": "a1",
        "duration": 1.4,
        "takeoff": "2026-07-20T12:00:00+00:00",
        "landing": "2026-07-20T13:22:00+00:00",
        "pic_day_tra": 1.4,
    }
    base.update(overrides)
    return base


HANGAR = [{"id": "a1"}]


def rules_for(findings, flight_id=None):
    return {f.rule_type for f in findings if flight_id is None or f.flight_id == flight_id}


def check(label, condition):
    print(f"{'✅' if condition else '❌'} {label}")
    return condition


def main() -> bool:
    ok = True

    # A clean logbook produces nothing at all.
    ok &= check(
        "vuelo correcto no genera hallazgos",
        engine.evaluate([flight()], HANGAR) == [],
    )

    # Overlap: both flights get flagged, not just the later one.
    overlapping = [
        flight(id="f1", takeoff="2026-07-20T12:00:00+00:00", landing="2026-07-20T13:22:00+00:00"),
        flight(id="f2", takeoff="2026-07-20T13:00:00+00:00", landing="2026-07-20T14:00:00+00:00"),
    ]
    findings = engine.evaluate(overlapping, HANGAR)
    ok &= check(
        "superposición marca los dos vuelos",
        rules_for(findings, "f1") == rules_for(findings, "f2") == {engine.RULE_OVERLAP},
    )

    # Back-to-back flights touch but don't overlap: landing == next takeoff.
    consecutive = [
        flight(id="f1", takeoff="2026-07-20T12:00:00+00:00", landing="2026-07-20T13:00:00+00:00"),
        flight(id="f2", takeoff="2026-07-20T13:00:00+00:00", landing="2026-07-20T14:00:00+00:00"),
    ]
    ok &= check(
        "vuelos consecutivos no se consideran superpuestos",
        engine.evaluate(consecutive, HANGAR) == [],
    )

    # The frontend stamps both timestamps with the same calendar date, so a
    # flight landing after midnight arrives with landing < takeoff. It must not
    # read as a 23-hour block overlapping everything else that night.
    midnight = [
        flight(id="f1", takeoff="2026-07-20T23:30:00+00:00", landing="2026-07-20T00:20:00+00:00", duration=0.8, pic_day_tra=0.8),
        flight(id="f2", takeoff="2026-07-20T14:00:00+00:00", landing="2026-07-20T15:00:00+00:00", duration=1.0, pic_day_tra=1.0),
    ]
    ok &= check(
        "vuelo que cruza medianoche no falsea superposición",
        engine.evaluate(midnight, HANGAR) == [],
    )

    # Aircraft that is not in the hangar, and no aircraft at all.
    ok &= check(
        "aeronave desconocida se marca",
        rules_for(engine.evaluate([flight(aircraft_id="ghost")], HANGAR)) == {engine.RULE_UNREGISTERED_AIRCRAFT},
    )
    ok &= check(
        "vuelo sin aeronave se marca",
        rules_for(engine.evaluate([flight(aircraft_id=None)], HANGAR)) == {engine.RULE_UNREGISTERED_AIRCRAFT},
    )

    # Duplicates: identical date, route, aircraft and times.
    dupes = [flight(id="f1"), flight(id="f2")]
    findings = engine.evaluate(dupes, HANGAR)
    ok &= check(
        "duplicado exacto marca ambas copias",
        rules_for(findings, "f1") == rules_for(findings, "f2") == {engine.RULE_DUPLICATE},
    )

    # Route spelling shouldn't hide a duplicate.
    ok &= check(
        "duplicado se detecta con ruta escrita distinto",
        engine.RULE_DUPLICATE
        in rules_for(engine.evaluate([flight(id="f1", route="SADM SAEZ"), flight(id="f2", route="SADM-SAEZ")], HANGAR)),
    )

    # A duplicate pair overlaps itself by definition, so the overlap rule stays
    # quiet about it — but a genuine collision with an unrelated third flight
    # must still surface.
    dupes_plus_third = [
        flight(id="f1"),
        flight(id="f2"),
        flight(id="f3", route="SADM SADF", takeoff="2026-07-20T13:00:00+00:00", landing="2026-07-20T14:00:00+00:00", duration=1.0, pic_day_tra=1.0),
    ]
    findings = engine.evaluate(dupes_plus_third, HANGAR)
    ok &= check(
        "duplicado que además choca con un tercero conserva la superposición",
        rules_for(findings, "f1") == {engine.RULE_DUPLICATE, engine.RULE_OVERLAP}
        and rules_for(findings, "f3") == {engine.RULE_OVERLAP},
    )

    # Totals: over-allocated is critical, under-allocated and bare are warnings.
    over = engine.evaluate([flight(pic_day_tra=2.0)], HANGAR)
    ok &= check(
        "suma mayor al total es crítica",
        [f.severity for f in over if f.rule_type == engine.RULE_INCONSISTENT_TOTAL] == [engine.SEVERITY_CRITICAL],
    )

    under = engine.evaluate([flight(pic_day_tra=0.6)], HANGAR)
    ok &= check(
        "suma menor al total es advertencia",
        [f.severity for f in under if f.rule_type == engine.RULE_INCONSISTENT_TOTAL] == [engine.SEVERITY_WARNING],
    )

    bare = engine.evaluate([flight(pic_day_tra=None)], HANGAR)
    ok &= check(
        "vuelo sin desglose se marca como advertencia",
        [f.severity for f in bare if f.rule_type == engine.RULE_INCONSISTENT_TOTAL] == [engine.SEVERITY_WARNING],
    )

    # Splitting the total across two categories still adds up.
    split = engine.evaluate([flight(pic_day_tra=0.6, pic_night_tra=0.8)], HANGAR)
    ok &= check("desglose repartido en dos categorías cierra", split == [])

    # --- document alert scheduling -----------------------------------------
    today = date(2026, 7, 31)
    doc = {"expiry_date": "2026-09-20", "alert_days": [60, 30, 7], "last_alert_threshold": None}

    ok &= check("a 51 días entra en el bucket de 60", document_alerts.should_alert(doc, today) == 60)

    doc_sent_60 = {**doc, "last_alert_threshold": 60}
    ok &= check("no repite el aviso de 60", document_alerts.should_alert(doc_sent_60, today) is None)

    doc_closer = {**doc_sent_60, "expiry_date": "2026-08-20"}
    ok &= check("a 20 días pasa al bucket de 30", document_alerts.should_alert(doc_closer, today) == 30)

    doc_far = {**doc, "expiry_date": "2027-06-01"}
    ok &= check("un documento lejano no dispara nada", document_alerts.should_alert(doc_far, today) is None)

    doc_expired = {**doc, "expiry_date": "2026-07-01", "last_alert_threshold": 7}
    ok &= check(
        "documento vencido dispara el bucket de vencido",
        document_alerts.should_alert(doc_expired, today) == document_alerts.EXPIRED_BUCKET,
    )

    doc_expired_sent = {**doc_expired, "last_alert_threshold": document_alerts.EXPIRED_BUCKET}
    ok &= check("no repite el aviso de vencido", document_alerts.should_alert(doc_expired_sent, today) is None)

    # Entrega fallida: el webhook de `failed` deja las columnas de marca en NULL, y
    # de eso depende que el aviso se reintente. Es la invariante que sostiene todo
    # el arreglo del marcado, y es pura aritmética de fechas, así que se testea.
    #
    # Importa que vuelva a disparar el bucket que corresponde **hoy** y no el que se
    # había mandado: si el fallo se detecta cuando el documento ya bajó de 30 a 7,
    # reintentar el de 30 sería avisar de más días de los que quedan.
    doc_fallido = {**doc_sent_60, "last_alert_threshold": None}
    ok &= check(
        "un aviso desmarcado por entrega fallida se reintenta",
        document_alerts.should_alert(doc_fallido, today) == 60,
    )

    doc_fallido_mas_cerca = {**doc_fallido, "expiry_date": "2026-08-20"}
    ok &= check(
        "al reintentar avisa el bucket de hoy, no el que falló",
        document_alerts.should_alert(doc_fallido_mas_cerca, today) == 30,
    )

    # Vencimientos derivados (migración 011). La aritmética es lo único de
    # `derived_expiries` que no toca la base, y es lo que decide la fecha que
    # después bloquea el semáforo y dispara los avisos.
    ok &= check(
        "el vencimiento derivado suma los días al último vuelo",
        derived_expiries.derived_expiry(date(2026, 8, 1), 60) == date(2026, 9, 30),
    )

    # Sin vuelos no hay ancla: None significa "no vence" desde la migración 007,
    # que es lo correcto para una cuenta que todavía no empezó a correr.
    ok &= check(
        "sin vuelos, el vencimiento derivado queda en None",
        derived_expiries.derived_expiry(None, 60) is None,
    )

    ok &= check(
        "sin offset no se inventa una fecha",
        derived_expiries.derived_expiry(date(2026, 8, 1), None) is None,
    )

    # Cruzar el fin de mes y el año bisiesto: timedelta lo resuelve, pero es la
    # clase de cuenta que se rompe si alguien la reescribe a mano con meses.
    ok &= check(
        "el offset cruza el fin de año",
        derived_expiries.derived_expiry(date(2023, 12, 20), 90) == date(2024, 3, 19),
    )

    print("\n" + ("Todo OK" if ok else "Hay checks fallando"))
    return bool(ok)


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
