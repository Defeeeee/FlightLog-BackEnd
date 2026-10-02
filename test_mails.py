"""
El seguimiento de los mails: a quién le toca el de novedades, y las métricas del panel.

Offline, con diccionarios. `python test_mails.py`; sale con código 1 si algo falla.
"""

import sys
from datetime import datetime, timezone

from src.services.mails import BAJA_NOVEDADES, mails_del_panel, pendientes_de_novedades

resultados = []


def check(label, condition):
    print(f"{'✅' if condition else '❌'} {label}")
    resultados.append(bool(condition))


ok = "2026-09-01T12:00:00+00:00"
usuarios = [
    {"id": "a", "email": "a@x", "email_confirmed_at": ok, "app_metadata": {}},
    {"id": "b", "email": "b@x", "email_confirmed_at": ok, "app_metadata": {BAJA_NOVEDADES: True}},
    {"id": "c", "email": "c@x", "email_confirmed_at": None, "app_metadata": {}},
    {"id": "d", "email": "d@x", "email_confirmed_at": ok, "app_metadata": {}},
    # Se dio de baja del resumen del mes, que es otra baja: las novedades le llegan.
    {"id": "e", "email": "e@x", "email_confirmed_at": ok, "app_metadata": {"resumen_mensual_baja": True}},
]
ids = [x["user_id"] for x in pendientes_de_novedades(usuarios, ya_enviados={"d"})]
check("le toca al confirmado, sin baja y sin envío", "a" in ids)
check("dado de baja de novedades: no", "b" not in ids)
check("mail sin confirmar: no", "c" not in ids)
check("ya recibió esta tanda: no (correr dos veces no manda dos)", "d" not in ids)
check("la baja del resumen no es la de novedades", "e" in ids)

# --- las métricas ---
AHORA = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)
envios = [
    {"id": "e1", "user_id": "a", "tipo": "novedades", "clave": "2026-10", "enviado_at": "2026-10-02T13:00:00Z"},
    {"id": "e2", "user_id": "d", "tipo": "novedades", "clave": "2026-10", "enviado_at": "2026-10-02T13:00:00Z"},
    {"id": "e3", "user_id": "e", "tipo": "novedades", "clave": "2026-10", "enviado_at": "2026-10-02T13:00:00Z"},
    {"id": "e4", "user_id": "a", "tipo": "primer-vuelo", "clave": None, "enviado_at": "2026-09-30T13:00:00Z"},
    # De un administrador: no está en `ids`, no cuenta.
    {"id": "e5", "user_id": "admin", "tipo": "novedades", "clave": "2026-10", "enviado_at": "2026-10-02T13:00:00Z"},
]
eventos = [
    # e1: abierto dos veces (un mail abierto) y dos clics al mismo link más uno a otro.
    {"envio_id": "e1", "tipo": "apertura", "destino": None, "creado_at": "2026-10-02T13:30:00Z"},
    {"envio_id": "e1", "tipo": "apertura", "destino": None, "creado_at": "2026-10-02T20:00:00Z"},
    {"envio_id": "e1", "tipo": "clic", "destino": "/dashboard", "creado_at": "2026-10-02T13:31:00Z"},
    {"envio_id": "e1", "tipo": "clic", "destino": "/dashboard", "creado_at": "2026-10-02T13:32:00Z"},
    {"envio_id": "e1", "tipo": "clic", "destino": "/dashboard/log-flight", "creado_at": "2026-10-02T13:33:00Z"},
    # e2: abierto al día siguiente, sin clic.
    {"envio_id": "e2", "tipo": "apertura", "destino": None, "creado_at": "2026-10-03T14:00:00Z"},
    # e5: el del administrador.
    {"envio_id": "e5", "tipo": "apertura", "destino": None, "creado_at": "2026-10-02T13:05:00Z"},
    # Un evento de un envío que no existe: se ignora.
    {"envio_id": "fantasma", "tipo": "clic", "destino": "/x", "creado_at": "2026-10-02T13:05:00Z"},
]
m = mails_del_panel(envios, eventos, ids={"a", "d", "e"}, arroba_de={"a": "ana", "d": None}, ahora=AHORA)

t = m["totales"]
check("cuenta los envíos de las cuentas del panel, sin el del administrador", t["enviados"] == 4)
check("un mail abierto dos veces es un mail abierto", t["abiertos"] == 2)
check("tasa de apertura sobre los enviados", t["tasa_apertura"] == 50.0)
check("un mail con tres clics es un mail con clic", t["con_clic"] == 1 and t["tasa_clic"] == 25.0)
check("clic sobre los que abrieron", t["clic_sobre_abiertos"] == 50.0)
check("la mediana hasta abrir, en minutos (30 min y 25 h)", t["minutos_hasta_abrir"] == round((30 + 25 * 60) / 2))

nov = next(c for c in m["campanas"] if c["tipo"] == "novedades")
check("la campaña junta su tanda", nov["clave"] == "2026-10" and nov["enviados"] == 3 and nov["abiertos"] == 2)
check("los destinos se cuentan una vez por mail", nov["destinos"] == [{"destino": "/dashboard", "clics": 1}, {"destino": "/dashboard/log-flight", "clics": 1}])
check("la campaña más reciente va primero", m["campanas"][0]["tipo"] == "novedades")
pv = next(c for c in m["campanas"] if c["tipo"] == "primer-vuelo")
check("un mail sin abrir no inventa demora", pv["abiertos"] == 0 and pv["minutos_hasta_abrir"] is None)

p = m["pilotos"]
check("pilotos: con mails, abrieron, clic y nunca abrieron", p == {"con_mails": 3, "abrieron_alguno": 2, "hicieron_clic": 1, "nunca_abrieron": 1})

dia2 = next(d for d in m["por_dia"] if d["dia"] == "2026-10-02")
dia3 = next(d for d in m["por_dia"] if d["dia"] == "2026-10-03")
check("por día: enviados, primera apertura y primer clic", dia2 == {"dia": "2026-10-02", "enviados": 3, "abiertos": 1, "clics": 1} and dia3["abiertos"] == 1)
check("la serie tiene 30 días y termina hoy", len(m["por_dia"]) == 30 and m["por_dia"][-1]["dia"] == "2026-10-03")
check("por hora, en Argentina (13:30 UTC son las 10)", next(h for h in m["por_hora"] if h["hora"] == 10)["aperturas"] == 1 and len(m["por_hora"]) == 24)
check("cuánto tardan en abrir, por tramo", {x["tramo"]: x["mails"] for x in m["hasta_abrir"]} == {"menos de 1 h": 1, "1 a 6 h": 0, "6 a 24 h": 0, "más de 1 día": 1})

u = m["ultimos"]
check("los últimos envíos, sin mails ni ids, con el @", u[0]["tipo"] == "novedades" and "user_id" not in u[0] and any(x["arroba"] == "ana" for x in u))
e1 = next(x for x in u if x["arroba"] == "ana" and x["tipo"] == "novedades")
check("cada envío dice cuándo se abrió y qué links se tocaron", e1["aperturas"] == 2 and e1["clics"] == 3 and e1["destinos"] == ["/dashboard", "/dashboard/log-flight"])

vacio = mails_del_panel([], [], ids=set(), arroba_de={}, ahora=AHORA)
check("sin envíos no divide por cero", vacio["totales"]["tasa_apertura"] == 0.0 and vacio["campanas"] == [])

if not all(resultados):
    print(f"\n{resultados.count(False)} check(s) fallaron")
    sys.exit(1)
print(f"\n{len(resultados)} checks OK")
