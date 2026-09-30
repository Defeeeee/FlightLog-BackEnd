"""
El recordatorio del día siguiente al alta: a quién se le manda.

Offline, con diccionarios. `python test_recordatorios.py`; sale con código 1 si algo falla.
"""

import sys
from datetime import date

from src.services.recordatorios import MARCA, pendientes_de_recordatorio

resultados = []


def check(label, condition):
    print(f"{'✅' if condition else '❌'} {label}")
    resultados.append(bool(condition))


AYER = date(2026, 9, 23)
confirmado = "2026-09-23T23:00:00+00:00"
usuarios = [
    # Se registró ayer a las 21:05 de Argentina (00:05 UTC del 24): es de ayer.
    {"id": "a", "email": "a@x", "created_at": "2026-09-24T00:05:00Z", "email_confirmed_at": confirmado, "app_metadata": {"provider": "email"}},
    # Ayer, pero ya cargó un vuelo.
    {"id": "b", "email": "b@x", "created_at": "2026-09-23T15:00:00Z", "email_confirmed_at": confirmado, "app_metadata": {}},
    # Ayer, sin confirmar el mail.
    {"id": "c", "email": "c@x", "created_at": "2026-09-23T15:00:00Z", "email_confirmed_at": None, "app_metadata": {}},
    # Ayer, pero ya se le mandó.
    {"id": "d", "email": "d@x", "created_at": "2026-09-23T15:00:00Z", "email_confirmed_at": confirmado, "app_metadata": {MARCA: "2026-09-24T13:00:00Z"}},
    # Anteayer: ya no es "el día siguiente".
    {"id": "e", "email": "e@x", "created_at": "2026-09-22T15:00:00Z", "email_confirmed_at": confirmado, "app_metadata": {}},
    # Hoy (00:30 ART del 24 = 03:30 UTC): mañana le toca.
    {"id": "f", "email": "f@x", "created_at": "2026-09-24T03:30:00Z", "email_confirmed_at": confirmado, "app_metadata": {}},
]
perfiles = {"a": {"first_name": "Lu", "whatsapp": True}}

r = pendientes_de_recordatorio(usuarios, perfiles, con_vuelos={"b"}, con_avion={"a"}, dia=AYER)
ids = [x["user_id"] for x in r]

check("sólo le toca a 'a'", ids == ["a"])
check("un alta a las 21 h de Argentina es de ese día, aunque en UTC sea el siguiente", "a" in ids)
check("el que ya cargó un vuelo no recibe nada", "b" not in ids)
check("a un mail sin confirmar no se le escribe", "c" not in ids)
check("uno o ninguno: el marcado no se repite", "d" not in ids)
check("anteayer ya no cuenta", "e" not in ids)
check("el de hoy espera a mañana", "f" not in ids)
check("lleva nombre, avión, WhatsApp y cuándo fue el alta para armar el mail", r[0] == {"user_id": "a", "email": "a@x", "first_name": "Lu", "tiene_avion": True, "tiene_whatsapp": True, "dias_desde_el_alta": 1})
check("sin perfil, el nombre es None y no rompe",
      pendientes_de_recordatorio([{**usuarios[0], "id": "z"}], {}, set(), set(), AYER)[0]["first_name"] is None)

# La ventana: el 25 y el 26/09 el barrido falló y las altas de esos días se perdieron.
# Con tres días, la corrida siguiente las alcanza, y la marca evita repetir.
r3 = pendientes_de_recordatorio(usuarios, perfiles, con_vuelos={"b"}, con_avion={"a"}, dia=AYER, ventana=3)
ids3 = sorted(x["user_id"] for x in r3)
check("con ventana de 3 días entra el de anteayer", "e" in ids3)
check("la ventana no saltea las otras reglas (vuelos, mail, marca)", not {"b", "c", "d"} & set(ids3))
check("la ventana no mete el alta de hoy", "f" not in ids3)
check("el de anteayer sabe que fue hace 2 días", next(x for x in r3 if x["user_id"] == "e")["dias_desde_el_alta"] == 2)
viejo = {**usuarios[4], "id": "g", "created_at": "2026-09-20T15:00:00Z"}
check("lo de hace más de 3 días queda afuera", not pendientes_de_recordatorio([viejo], {}, set(), set(), AYER, ventana=3))

# A mano, con un `dia` viejo: los días se cuentan desde hoy, no desde ese día.
tarde = pendientes_de_recordatorio(usuarios, perfiles, set(), set(), AYER, ventana=1, hoy=date(2026, 9, 30))
check("un alta del 23 mandada el 30 dice 7 días, no 'ayer'", tarde and tarde[0]["dias_desde_el_alta"] == 7)

if not all(resultados):
    print(f"\n{resultados.count(False)} check(s) fallaron")
    sys.exit(1)
print(f"\n{len(resultados)} checks OK")
