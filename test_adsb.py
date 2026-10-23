"""
Los recorridos ADS-B: qué aviones del tráfico son de algún Hangar y qué posiciones se guardan.

Offline. `python test_adsb.py`; sale con código 1 si algo falla.
"""

import sys
from datetime import datetime, timezone

import json
import os
import tempfile

from src.services.adsb import latido_del_grabador, matriculas_del_hangar, normalizar_matricula, nuestros, posicion, vale_guardar

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

print(f"\n{sum(resultados)}/{len(resultados)}")
sys.exit(0 if all(resultados) else 1)
