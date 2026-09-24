"""
El panel de administración: las cuentas que arma `services/estadisticas.py`.

Corre offline, con diccionarios. Ejecutar con `python test_estadisticas.py`; sale con
código 1 si algún check falla.

Los checks que más importan: que un alta a las 21 h de Argentina cuente para ese día y
no para el siguiente (UTC), que el admin no infle los números por defecto, y que de las
últimas altas no salga nada más que el @.
"""

import sys
from datetime import datetime, timezone

from src.services.estadisticas import Crudos, _momento, aerodromos_de, armar

resultados = []


def check(label, condition):
    print(f"{'✅' if condition else '❌'} {label}")
    resultados.append(bool(condition))


AHORA = datetime(2026, 9, 24, 0, 20, tzinfo=timezone.utc)  # 21:20 del 23/09 en Argentina
ADMIN = "admin-1"

crudos = Crudos(
    usuarios=[
        {"id": ADMIN, "created_at": "2025-11-01T12:00:00+00:00", "last_sign_in_at": "2026-09-23T23:00:00+00:00"},
        # 19:57 y 21:05 del 23 en Argentina, que en UTC ya son del 24.
        {"id": "u1", "created_at": "2026-09-23 22:57:00+00", "last_sign_in_at": "2026-09-23 22:58:00+00"},
        {"id": "u2", "created_at": "2026-09-24T00:05:39.682937Z", "last_sign_in_at": None},
        {"id": "u3", "created_at": datetime(2026, 9, 1, 15, 0, tzinfo=timezone.utc), "last_sign_in_at": "2026-09-10T15:00:00+00:00"},
    ],
    perfiles=[
        {"id": ADMIN, "license_type": "PPA", "whatsapp": True},
        {"id": "u1", "license_type": "PPA", "whatsapp": True},
        {"id": "u2", "license_type": "PCA", "whatsapp": False},
        {"id": "u3", "license_type": None, "whatsapp": False},
    ],
    aviones=[
        {"id": "a0", "user_id": ADMIN, "type": "c152", "is_simulator": False},
        {"id": "a1", "user_id": "u1", "type": "C152", "is_simulator": False},
        {"id": "s3", "user_id": "u3", "type": "SIM", "is_simulator": True},
    ],
    documentos=[{"user_id": "u1", "kind": "cma"}, {"user_id": "u3", "kind": "licencia"}],
    vuelos=[
        {"user_id": ADMIN, "date": "2026-09-20", "duration": 1.5, "route": "SADF SAAR", "aircraft_id": "a0"},
        {"user_id": "u1", "date": "2026-09-22", "duration": 1.2, "route": "SADF SADF", "aircraft_id": "a1"},
        {"user_id": "u1", "date": "2026-07-02", "duration": 0.8, "route": "ASG LOCAL", "aircraft_id": "a1"},
    ],
    arrobas=[{"user_id": "u1", "handle": "lu.vuela"}, {"user_id": ADMIN, "handle": "fede.dn"}],
    publicaciones=[{"autor": ADMIN}, {"autor": "u1"}],
    seguimientos=[{"seguidor": "u1", "estado": "aceptado"}, {"seguidor": "u2", "estado": "pendiente"}],
    push=[{"user_id": "u1"}],
    reportes=2,
    no_disponible=["metricas"],
)

r = armar(crudos, AHORA, excluir={ADMIN})
t = r["totales"]

print("— Días en Argentina")
check("'hoy' es el 23/09, aunque en UTC ya sea el 24", r["hoy"] == "2026-09-23")
check("las dos altas del 23 a la noche cuentan como altas de hoy", t["altas_hoy"] == 2)
check("el alta del 1/09 entra en los 30 días y no en los 7", t["altas_7d"] == 2 and t["altas_30d"] == 3)
ultimo = r["altas_por_dia"][-1]
check("la serie de altas termina en hoy, con 2 altas y 3 cuentas acumuladas", ultimo == {"fecha": "2026-09-23", "altas": 2, "acumulado": 3})
check("la serie tiene 60 días", len(r["altas_por_dia"]) == 60)

print("— El admin no infla los números")
check("sin el admin hay 3 cuentas", t["cuentas"] == 3 and r["admins_excluidos"] == 1)
check("los vuelos del admin no cuentan", t["vuelos"] == 2 and t["horas"] == 2.0)
check("las publicaciones del admin no cuentan", t["publicaciones"] == 1)
con_admin = armar(crudos, AHORA)
check("con el admin adentro vuelven a ser 4 cuentas y 3 vuelos", con_admin["totales"]["cuentas"] == 4 and con_admin["totales"]["vuelos"] == 3)

print("— Actividad y activación")
check("activos en 7 días: u1 (u2 nunca entró de nuevo, u3 hace 13 días)", t["activos_7d"] == 1)
tramos = {x["tramo"]: x["cuentas"] for x in r["ultimo_ingreso"]}
check("último ingreso: 1 hoy, 1 hace 8-30 días, 1 nunca", tramos["Hoy"] == 1 and tramos["8 a 30 días"] == 1 and tramos["Nunca"] == 1)
pasos = {x["paso"]: x for x in r["activacion"]}
check("un simulador no cuenta como 'Avión cargado'", pasos["Avión cargado"]["cuentas"] == 1)
check("licencia cargada: 2 de 3, 66,7 %", pasos["Licencia cargada"]["cuentas"] == 2 and pasos["Licencia cargada"]["pct"] == 66.7)
check("un seguimiento pendiente no suma a 'seguimientos'", t["seguimientos"] == 1)
check("una tabla que no se pudo leer se nombra", r["no_disponible"] == ["metricas"])

print("— Vuelos, aeródromos y aeronaves")
meses = {m["mes"]: m for m in r["vuelos_por_mes"]}
check("12 meses, terminando en septiembre de 2026", len(r["vuelos_por_mes"]) == 12 and r["vuelos_por_mes"][-1]["mes"] == "2026-09")
check("julio: 1 vuelo, 0,8 h, 1 piloto", meses["2026-07"] == {"mes": "2026-07", "vuelos": 1, "horas": 0.8, "pilotos": 1})
check("rutas: 'ASG LOCAL' es ASG, y un local cuenta el aeródromo una vez", aerodromos_de("ASG LOCAL") == ["ASG"] and {x["codigo"]: x["vuelos"] for x in r["top_aerodromos"]} == {"SADF": 1, "ASG": 1})
check("rutas con guion o flecha también", aerodromos_de("sadf-saak") == ["SADF", "SAAK"] and aerodromos_de("SADF → SAAR") == ["SADF", "SAAR"])
check("el tipo de aeronave se normaliza en mayúsculas", r["top_aeronaves"] == [{"tipo": "C152", "vuelos": 2}])

print("— Las últimas altas no exponen a nadie")
claves = set(r["ultimas_altas"][0])
check("sólo alta, ingreso, @, licencia y el avance", claves == {"alta", "ultimo_ingreso", "arroba", "licencia", "avion", "cma", "whatsapp", "vuelos"})
check("la más nueva va primero", r["ultimas_altas"][0]["arroba"] is None and r["ultimas_altas"][1]["arroba"] == "lu.vuela")

print("— Timestamps de Supabase")
check("'+00' a secas", _momento("2026-09-23 22:57:00+00") == datetime(2026, 9, 23, 22, 57, tzinfo=timezone.utc))
check("'Z' con microsegundos", _momento("2026-09-24T00:05:39.682937Z").microsecond == 682937)
check("sin zona se toma como UTC", _momento("2026-09-23T10:00:00") == datetime(2026, 9, 23, 10, tzinfo=timezone.utc))
check("basura es None", _momento("no es una fecha") is None and _momento(None) is None)

print("— Cohortes")
esta = r["cohortes"][-1]
check("la semana del 21/09: 2 altas, 1 con avión, 1 con vuelo", esta == {"semana": "2026-09-21", "altas": 2, "con_avion": 1, "con_vuelo": 1})

vacio = armar(Crudos(), AHORA)
check("sin cuentas no se divide por cero", vacio["totales"]["cuentas"] == 0 and all(p["pct"] == 0 for p in vacio["activacion"]))

if not all(resultados):
    print(f"\n{resultados.count(False)} check(s) fallaron")
    sys.exit(1)
print(f"\n{len(resultados)} checks OK")
