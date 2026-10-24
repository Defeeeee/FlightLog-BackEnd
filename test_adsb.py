"""
Los recorridos ADS-B: qué aviones del tráfico son de algún Hangar y qué posiciones se guardan.

Offline. `python test_adsb.py`; sale con código 1 si algo falla.
"""

import sys
from datetime import datetime, timezone

import json
import os
import tempfile

from datetime import timedelta

from src.services.adsb import aterrizajes, compactar, expandir, fuente_de, ventana_del_dia, latido_del_grabador, matriculas_del_hangar, normalizar_matricula, nuestros, posicion, resumen, tramo_del_vuelo, tramos, vale_guardar

resultados = []


def check(label, condition):
    print(f"{'✅' if condition else '❌'} {label}")
    resultados.append(bool(condition))


check("normaliza la matrícula como la transmite el avión", normalizar_matricula("LV-S114") == "LVS114" and normalizar_matricula("lvs114  ") == "LVS114")
check("sin matrícula, None", normalizar_matricula("") is None and normalizar_matricula(None) is None)
hangar = matriculas_del_hangar([
    {"registration": "LV-S114", "is_simulator": False},
    {"registration": "Lv-S100", "is_simulator": None},
    {"registration": "SIM-01", "is_simulator": True},
])
check("las del Hangar, sin simuladores y en cualquier caja", hangar == {"LVS114", "LVS100"})

trafico = [
    {"hex": "e120da", "flight": "LVS114  ", "lat": -34.4, "lon": -58.6, "alt_baro": 900, "gs": 85.2, "seen_pos": 2.5},
    {"hex": "e0aaaa", "flight": "ARG1226 ", "lat": -34.8, "lon": -58.5, "alt_baro": "ground", "seen_pos": 1},
    {"hex": "~e0bbbb", "flight": "", "lat": -34.5, "lon": -58.7, "alt_baro": 1500, "seen_pos": 1},
    {"hex": "e0cccc", "lat": -34.5, "lon": -58.7, "alt_baro": 1500, "seen_pos": 1},
]
encontrados = nuestros(trafico, hangar, hex_conocidos={"e0cccc": "LVS100"})
check("encuentra el avión por el indicativo", ("LVS114", "e120da") in [(m, h) for m, h, _ in encontrados])
check("y por el código aprendido aunque no mande indicativo", ("LVS100", "e0cccc") in [(m, h) for m, h, _ in encontrados])
check("un avión ajeno no entra", len(encontrados) == 2)
por_r = nuestros([{"hex": "e0dddd", "flight": "", "r": "LV-S114", "lat": 1, "lon": 1}], hangar, {})
check("y por la matrícula que trae la fuente (`r`)", [(m, h) for m, h, _ in por_r] == [("LVS114", "e0dddd")])

ahora = datetime(2026, 10, 23, 15, 0, 0, tzinfo=timezone.utc)
p = posicion(trafico[0], ahora)
check("la hora es la de la posición, no la del pedido", p["visto_at"] == "2026-10-23T14:59:57+00:00")
check("en el aire: altitud y velocidad", p["altitud"] == 900 and p["velocidad"] == 85.2 and not p["en_tierra"])
t = posicion({"lat": -34.45, "lon": -58.58, "alt_baro": "ground", "seen_pos": 1}, ahora)
check("en tierra: sin altitud y marcado", t["altitud"] is None and t["en_tierra"])
check("una posición vieja no se guarda", posicion({"lat": 1, "lon": 1, "alt_baro": 500, "seen_pos": 300}, ahora) is None)
check("sin posición, nada", posicion({"alt_baro": 500, "seen_pos": 1}, ahora) is None)

base = {"visto_at": "2026-10-23T15:00:00+00:00", "lat": -34.45, "lon": -58.58, "altitud": None}
check("la primera se guarda", vale_guardar(base, None))
check("la misma posición repetida, no", not vale_guardar(dict(base), base))
check("quieto y al rato, no", not vale_guardar({**base, "visto_at": "2026-10-23T15:00:30+00:00"}, base))
check("quieto pero pasaron dos minutos, sí", vale_guardar({**base, "visto_at": "2026-10-23T15:02:00+00:00"}, base))
check("se movió, sí", vale_guardar({**base, "visto_at": "2026-10-23T15:00:10+00:00", "lat": -34.46}, base))

# --- el latido ---
ruta = os.path.join(tempfile.mkdtemp(), "latido.json")
check("sin latido, no está vivo", latido_del_grabador(ruta, ahora) == {"vivo": False, "detalle": "sin latido"})
with open(ruta, "w") as f:
    json.dump({"vuelta": "2026-10-23T14:59:40+00:00", "ok": True, "trafico": 25, "nuestros_en_el_aire": 1}, f)
check("una vuelta hace 20 s: vivo", latido_del_grabador(ruta, ahora)["vivo"])
check("hace 5 minutos: no", not latido_del_grabador(ruta, datetime(2026, 10, 23, 15, 5, tzinfo=timezone.utc))["vivo"])
with open(ruta, "w") as f:
    f.write("{roto")
check("un latido roto no tira", latido_del_grabador(ruta, ahora)["vivo"] is False)

# --- etapa 2: los vuelos dentro de las posiciones ---
T0 = datetime(2026, 10, 24, 19, 27, 0, tzinfo=timezone.utc)


def vuelo(desde_min, alturas, cada_s=10, lat0=-34.45):
    return [
        {"visto_at": T0 + timedelta(minutes=desde_min, seconds=i * cada_s), "lat": lat0 - i * 0.002, "lon": -58.59 - i * 0.002, "altitud": a, "velocidad": 80.0}
        for i, a in enumerate(alturas)
    ]


# Un vuelo con dos tocar y despegar y el aterrizaje final, y otro 40 minutos después.
uno = vuelo(0, [100, 400, 900, 1000, 900, 200, 500, 900, 150, 600, 1000, 300, 100])
dos = vuelo(40, [150, 600, 1100, 800, 200])
ts = tramos(dos + uno)
check("dos vuelos separados por más de 5 minutos", len(ts) == 2 and ts[0][0] is uno[0])
check("un corte de dos minutos adentro del vuelo no lo parte", len(tramos(vuelo(0, [500] * 6, cada_s=130))) == 1)
check("dos posiciones sueltas no son un vuelo", tramos(vuelo(0, [900, 900])) == [])
check("aterrizajes: dos tocar y despegar más el final", aterrizajes(uno) == 3)
check("el despegue no cuenta como aterrizaje", aterrizajes(dos) == 1)
r = resumen(uno)
check("el resumen: horas de la primera y la última posición", r["despegue"] == "2026-10-24T19:27:00+00:00" and r["minutos"] == 2)
check("y altura y velocidad máximas", r["altitud_max"] == 1000 and r["velocidad_max"] == 80 and r["posiciones"] == 13)
c = compactar(uno)
check("compacto: segundos desde el primero", c["t0"] == int(T0.timestamp()) and c["p"][1][0] == 10 and len(c["p"]) == 13)

carga_d, carga_a = T0 + timedelta(minutes=-2), T0 + timedelta(minutes=4)
check("el tramo del vuelo cargado es el que se superpone", tramo_del_vuelo(uno + dos, carga_d, carga_a) is not None and tramo_del_vuelo(uno + dos, carga_d, carga_a)[0] is uno[0])
check("el vuelo de otro piloto, una hora después, no se devuelve", tramo_del_vuelo(uno + dos, T0 + timedelta(hours=2), T0 + timedelta(hours=3)) is None)
check("el segundo vuelo, con sus horarios, es el segundo", tramo_del_vuelo(uno + dos, T0 + timedelta(minutes=39), T0 + timedelta(minutes=42))[0] is dos[0])

d, h = ventana_del_dia("2026-10-24")
check("el día argentino en UTC: de las 03:00 a las 03:00", d.isoformat() == "2026-10-24T03:00:00+00:00" and (h - d).days == 1)
check("expandir deshace compactar", [round(p["lat"], 5) for p in expandir(compactar(uno))] == [round(p["lat"], 5) for p in uno])
check("la fuente por fecha: adsb.lol antes del cambio, adsb.fi después", fuente_de(uno) == "adsb.fi" and fuente_de(vuelo(-60 * 24, [500, 500, 500])) == "adsb.lol")

print(f"\n{sum(resultados)}/{len(resultados)}")
sys.exit(0 if all(resultados) else 1)
