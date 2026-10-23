"""
Las pegatinas con QR: los códigos, cuándo una cuenta vino de una pegatina y el panel.

Offline. `python test_qr.py`; sale con código 1 si algo falla.
"""

import sys

from src.services.qr import ALFABETO, LARGO, atribuible, generar, normalizar, panel

resultados = []


def check(label, condition):
    print(f"{'✅' if condition else '❌'} {label}")
    resultados.append(bool(condition))


# --- los códigos ---
nuevos = generar(200, existentes=["AAAA"])
check("genera la cantidad pedida", len(nuevos) == 200)
check("sin repetidos", len(set(nuevos)) == 200)
check("no repite uno que ya existe", "AAAA" not in nuevos)
check("del largo fijo y con el alfabeto sin ambiguos", all(len(c) == LARGO and set(c) <= set(ALFABETO) for c in nuevos))
check("el alfabeto no tiene 0/O, 1/I/L ni 5/S", not set("0O1IL5S") & set(ALFABETO))
check("normaliza la caja", normalizar(" k7p2 ") == "K7P2")
check("rechaza lo que no es un código", normalizar("../x") is None and normalizar("AB") is None and normalizar("") is None)

# --- la atribución ---
check("cuenta creada después de escanear: sí", atribuible("2026-10-23T15:00:00Z", "2026-10-23T14:00:00Z"))
check("con un minuto de margen por los relojes", atribuible("2026-10-23T13:59:30Z", "2026-10-23T14:00:00Z"))
check("cuenta de antes del escaneo: no (ya era piloto de Vector)", not atribuible("2026-09-01T00:00:00Z", "2026-10-23T14:00:00Z"))
check("más de 30 días después: no", not atribuible("2026-12-01T00:00:00Z", "2026-10-23T14:00:00Z"))
check("sin fechas: no", not atribuible(None, "2026-10-23T14:00:00Z") and not atribuible("x", "y"))

# --- el panel ---
filas = panel(
    [{"codigo": "AAAA", "etiqueta": None}, {"codigo": "BBBB", "etiqueta": "Cartelera SADF"}, {"codigo": "CCCC", "etiqueta": "Bar"}],
    [
        {"codigo": "BBBB", "con_sesion": False, "creado_at": "2026-10-23T10:00:00Z"},
        {"codigo": "BBBB", "con_sesion": True, "creado_at": "2026-10-23T12:00:00Z"},
        {"codigo": "CCCC", "con_sesion": False, "creado_at": "2026-10-22T12:00:00Z"},
        {"codigo": "ZZZZ", "con_sesion": False, "creado_at": "2026-10-22T12:00:00Z"},
    ],
    [{"origen_qr": "BBBB"}, {"origen_qr": "BBBB"}, {"origen_qr": None}],
)
b = next(f for f in filas if f["codigo"] == "BBBB")
check("cuenta los escaneos", b["escaneos"] == 2 and b["escaneos_sin_sesion"] == 1)
check("el último escaneo", b["ultimo_escaneo"] == "2026-10-23T12:00:00Z")
check("las cuentas que salieron de la pegatina", b["cuentas"] == 2)
check("primero las asignadas, por escaneos; las sin asignar al final", [f["codigo"] for f in filas] == ["BBBB", "CCCC", "AAAA"])
check("un escaneo de un código que no existe no suma", sum(f["escaneos"] for f in filas) == 3)

print(f"\n{sum(resultados)}/{len(resultados)}")
sys.exit(0 if all(resultados) else 1)
