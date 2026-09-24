"""
El resumen del mes por mail: a quién se le manda.

Offline, con diccionarios. `python test_resumen_mensual.py`; sale con código 1 si algo falla.
"""

import sys
from datetime import date

from src.services.resumen_mensual import BAJA, MARCA, mes_anterior, mes_valido, pendientes_de_resumen

resultados = []


def check(label, condition):
    print(f"{'✅' if condition else '❌'} {label}")
    resultados.append(bool(condition))


ok = "2026-09-01T12:00:00+00:00"
usuarios = [
    {"id": "a", "email": "a@x", "email_confirmed_at": ok, "app_metadata": {}},
    # Nunca cargó un vuelo: para eso está el mail del día siguiente.
    {"id": "b", "email": "b@x", "email_confirmed_at": ok, "app_metadata": {}},
    # Sin confirmar el mail.
    {"id": "c", "email": "c@x", "email_confirmed_at": None, "app_metadata": {}},
    # Se dio de baja.
    {"id": "d", "email": "d@x", "email_confirmed_at": ok, "app_metadata": {BAJA: True}},
    # Ya recibió el de septiembre.
    {"id": "e", "email": "e@x", "email_confirmed_at": ok, "app_metadata": {MARCA: "2026-09"}},
    # Recibió el de agosto: le toca el de septiembre.
    {"id": "f", "email": "f@x", "email_confirmed_at": ok, "app_metadata": {MARCA: "2026-08"}},
    # Sin mail.
    {"id": "g", "email": None, "email_confirmed_at": ok, "app_metadata": {}},
    # Se dio de baja y volvió a suscribirse.
    {"id": "h", "email": "h@x", "email_confirmed_at": ok, "app_metadata": {BAJA: False}},
]
con_vuelos = {"a", "c", "d", "e", "f", "g", "h"}

ids = [x["user_id"] for x in pendientes_de_resumen(usuarios, con_vuelos, "2026-09")]
check("con vuelos, confirmado y sin marca: le toca", "a" in ids)
check("sin vuelos nunca: no le toca", "b" not in ids)
check("mail sin confirmar: no", "c" not in ids)
check("dado de baja: no", "d" not in ids)
check("ya recibió el de ese mes: no (correr dos veces no manda dos)", "e" not in ids)
check("recibió el del mes anterior: sí", "f" in ids)
check("sin mail: no", "g" not in ids)
check("volvió a suscribirse: sí", "h" in ids)
check("devuelve id y mail, nada más", pendientes_de_resumen(usuarios, con_vuelos, "2026-09")[0] == {"user_id": "a", "email": "a@x"})

check("el 1 de octubre se resume septiembre", mes_anterior(date(2026, 10, 1)) == "2026-09")
check("el 1 de enero se resume diciembre del año anterior", mes_anterior(date(2027, 1, 1)) == "2026-12")
check("mes válido", mes_valido("2026-09") and mes_valido("2026-12"))
check("mes inválido", not mes_valido("2026-13") and not mes_valido("2026-9") and not mes_valido("") and not mes_valido("2026-09-01"))

print(f"\n{sum(resultados)}/{len(resultados)} checks")
sys.exit(0 if all(resultados) else 1)
