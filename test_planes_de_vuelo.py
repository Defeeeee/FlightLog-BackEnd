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

check("la firma tiene que ser un PNG", falla(lambda: FirmaPlanVuelo(png="data:image/jpeg;base64,AAAA")))
check("un PNG se acepta", not falla(lambda: FirmaPlanVuelo(png="data:image/png;base64,iVBORw0KGgo=")))

check("el perfil del avión para el plan se acepta", not falla(lambda: AircraftUpdate(plan_vuelo={"equipo": "SDGZ", "vigilancia": "EB2", "per": "A"})))
check("y se rechaza si es enorme", falla(lambda: AircraftUpdate(plan_vuelo={"x": "A" * 9000})))
check("no mandarlo deja el campo como está", "plan_vuelo" not in AircraftUpdate(icao="ECHO").model_dump(exclude_unset=True))

if not all(resultados):
    print(f"\n{resultados.count(False)} check(s) fallaron")
    sys.exit(1)
print(f"\n{len(resultados)} checks OK")
