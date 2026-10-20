"""
Los planes de vuelo guardados (migración 024): lo que el backend decide por su cuenta.

El formulario lo valida el frontend; acá se prueban la copia para la lista, los topes de
tamaño y el máximo de tres demoras por vuelo (AIP ENR 1.10, 7.3).

    python test_planes_de_vuelo.py
"""
import sys

from pydantic import ValidationError

from src.models.aircraft import AircraftUpdate
from src.models.plan_vuelo import (
    MAX_FORMULARIO_BYTES,
    FirmaPlanVuelo,
    PlanVueloCreate,
    PlanVueloResumen,
    PlanVueloUpdate,
    resumen_para_lista,
)

resultados = []


def check(label, condition):
    print(f"{'✅' if condition else '❌'} {label}")
    resultados.append(bool(condition))


def falla(fn):
    try:
        fn()
    except (ValidationError, ValueError):
        return True
    return False


form = {
    "matricula": "lv-s114",
    "salida": {"codigo": "sadf", "nombre": "San Fernando"},
    "destino": {"codigo": "SAAK", "nombre": "Martín García"},
    "dofUtc": "2026-10-20",
    "eobtUtc": "1830",
}
r = resumen_para_lista(form)
check("la lista copia salida, destino y matrícula en mayúsculas", (r["salida"], r["destino"], r["matricula"]) == ("SADF", "SAAK", "LV-S114"))
check("y la fecha y hora de salida", r["dof"] == "2026-10-20" and r["eobt"] == "1830")

malo = resumen_para_lista({"salida": "SADF", "dofUtc": "20/10/2026", "eobtUtc": "18:30"})
check("lo que no tiene la forma esperada queda en NULL, no inventado", malo == {"salida": None, "destino": None, "matricula": None, "dof": None, "eobt": None})
check("una fecha imposible también", resumen_para_lista({"dofUtc": "2026-02-31"})["dof"] is None)

check("un formulario normal se acepta", not falla(lambda: PlanVueloCreate(formulario=form)))
grande = {"x": "A" * (MAX_FORMULARIO_BYTES + 10)}
check("un formulario gigante se rechaza", falla(lambda: PlanVueloCreate(formulario=grande)))
check("también al actualizar", falla(lambda: PlanVueloUpdate(formulario=grande)))

tres = [{"eobt": "1900", "dof": "2026-10-20"}] * 3
check("hasta tres demoras por vuelo", not falla(lambda: PlanVueloUpdate(demoras=tres)))
check("la cuarta no (AIP ENR 1.10, 7.3)", falla(lambda: PlanVueloUpdate(demoras=tres + [{"eobt": "2000", "dof": "2026-10-20"}])))
check("una hora de demora mal escrita se rechaza", falla(lambda: PlanVueloUpdate(demoras=[{"eobt": "19:00", "dof": "2026-10-20"}])))

check("un envío de prueba o a la oficina se acepta", not falla(lambda: PlanVueloUpdate(envio={"modo": "prueba", "a": "piloto@example.com"})))
check("un envío de otro modo no", falla(lambda: PlanVueloUpdate(envio={"modo": "spam", "a": "x@example.com"})))
check("un envío sin tipo es del plan", PlanVueloUpdate(envio={"modo": "aro", "a": "x@example.com"}).envio.tipo == "fpl")
check("una demora se anota como dla", PlanVueloUpdate(envio={"modo": "aro", "tipo": "dla", "a": "x@example.com"}).envio.tipo == "dla")
check("un tipo inventado no", falla(lambda: PlanVueloUpdate(envio={"modo": "aro", "tipo": "spam", "a": "x@example.com"})))
check("la cancelación se anota como cnl", PlanVueloUpdate(envio={"modo": "aro", "tipo": "cnl", "a": "x@example.com"}).envio.tipo == "cnl")
check("cancelar es sólo true", falla(lambda: PlanVueloUpdate(cancelado=False)))
check("descartar es sólo true", PlanVueloUpdate(descartado=True).descartado is True and falla(lambda: PlanVueloUpdate(descartado=False)))
check("el vuelo es un uuid", falla(lambda: PlanVueloUpdate(vuelo_id="no-es-uuid")))
check("la lista trae cómo terminó", {"vuelo_id", "cancelado_at", "descartado_at"} <= set(PlanVueloResumen.model_fields))
check("la firma tiene que ser un PNG", falla(lambda: FirmaPlanVuelo(png="data:image/jpeg;base64,AAAA")))
check("un PNG se acepta", not falla(lambda: FirmaPlanVuelo(png="data:image/png;base64,iVBORw0KGgo=")))

check("el perfil del avión para el plan se acepta", not falla(lambda: AircraftUpdate(plan_vuelo={"equipo": "SDGZ", "vigilancia": "EB2", "per": "A"})))
check("y se rechaza si es enorme", falla(lambda: AircraftUpdate(plan_vuelo={"x": "A" * 9000})))
check("no mandarlo deja el campo como está", "plan_vuelo" not in AircraftUpdate(icao="ECHO").model_dump(exclude_unset=True))

from src.services.recordatorio_plan import armar_pendientes  # noqa: E402

_planes = [{"id": "p1", "user_id": "u1", "formulario": {"eet": "0045"}, "demoras": []}, {"id": "p2", "user_id": "u2", "formulario": {}}]
_usuarios = {"u1": {"email": "a@x.com", "email_confirmed_at": "2026-10-01T00:00:00Z"}, "u2": {"email": "b@x.com", "email_confirmed_at": None}}
_pend = armar_pendientes(_planes, _usuarios, {"u1": {"first_name": "Lucía"}}, [{"user_id": "u1", "date": "2026-10-20", "route": "SADF SADM"}, {"user_id": "u9", "date": "2026-10-20", "route": "X"}])
check("el recordatorio no le escribe a un mail sin confirmar", [p["id"] for p in _pend] == ["p1"])
check("el recordatorio lleva el nombre y sólo los vuelos de ese piloto", _pend[0]["first_name"] == "Lucía" and _pend[0]["vuelos"] == [{"date": "2026-10-20", "route": "SADF SADM"}])

if not all(resultados):
    print(f"\n{resultados.count(False)} check(s) fallaron")
    sys.exit(1)
print(f"\n{len(resultados)} checks OK")
