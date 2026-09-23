"""
Que ningún campo de ningún modelo quede tipado `NoneType`.

Corre offline, sin base ni servidor: `python test_models.py`.

## Por qué existe este archivo

Por un bug que estuvo vivo desde que se escribió `PlannedFlightUpdate` y que **no
falla al importar, no falla al arrancar y no aparece en ningún log**: el modelo
importaba `from datetime import date` y tenía un campo llamado `date`. En

    date: Optional[date] = None

Python asigna el default **antes** de evaluar la anotación, así que para cuando mira
`Optional[date]` el nombre ya vale `None` en el cuerpo de la clase. El campo queda
tipado `NoneType` y pydantic **rechaza cualquier valor que no sea nulo**.

El síntoma que ve el usuario es `Validation failed for PATCH /planned-flights/<id>`,
sin decir qué campo. Editar un vuelo programado y posponerlo estuvieron rotos todo
ese tiempo; lo encontró un piloto tratando de corregir un horario.

## Por qué el chequeo es genérico y no un test de este modelo

Porque la trampa es del lenguaje, no de este archivo: **cualquier modelo con un campo
que se llame igual que un tipo importado la pisa**, y son nombres normales —`date`,
`time`, `status`, `type`—. Un test de `PlannedFlightUpdate` habría tapado este caso y
dejado el próximo. Este recorre todos los modelos y no hay que acordarse de nada.

`NoneType` nunca es un tipo que alguien quiera escribir a mano: si aparece, es esto.
"""

import importlib
import inspect
import pkgutil
import sys

sys.path.insert(0, ".")

import src.models as paquete


def campos_nonetype():
    """Todos los campos tipados `NoneType`, como `modulo.Clase.campo`."""
    encontrados = []
    for modulo in pkgutil.iter_modules(paquete.__path__):
        mod = importlib.import_module(f"src.models.{modulo.name}")
        for nombre, cls in inspect.getmembers(mod, inspect.isclass):
            campos = getattr(cls, "model_fields", None)
            # Sólo las clases definidas acá: las importadas ya se revisan en su módulo.
            if not campos or cls.__module__ != mod.__name__:
                continue
            for campo, f in campos.items():
                if f.annotation is type(None):
                    encontrados.append(f"{modulo.name}.{nombre}.{campo}")
    return encontrados


def test_ningun_campo_quedo_en_nonetype():
    malos = campos_nonetype()
    assert not malos, (
        "Estos campos quedaron tipados NoneType y van a rechazar todo valor no nulo: "
        + ", ".join(malos)
        + ". Casi seguro es un campo que se llama igual que un tipo importado; "
        "importá el tipo calificado (`import datetime as dt` → `dt.date`)."
    )


def test_el_patch_de_un_vuelo_programado_acepta_lo_que_manda_el_formulario():
    """
    El payload exacto del calendario. Es el que fallaba.
    """
    from src.models.planned_flight import PlannedFlightUpdate

    p = PlannedFlightUpdate(
        date="2026-08-21",
        aircraft_id=None,
        route="SADF SAZM",
        notes=None,
        takeoff_time="12:30",
        landing_time="15:30",
    )
    assert p.date.isoformat() == "2026-08-21"
    assert p.takeoff_time.isoformat() == "12:30:00"
    assert p.landing_time.isoformat() == "15:30:00"


def test_posponer_acepta_una_fecha():
    """`posponerProgramado` manda sólo este campo, y también estaba roto."""
    from src.models.planned_flight import PlannedFlightUpdate

    p = PlannedFlightUpdate(postponed_until="2026-08-22")
    assert p.postponed_until.isoformat() == "2026-08-22"


def test_borrar_un_horario_sigue_siendo_mandar_null():
    """
    El PATCH usa `exclude_unset`: `null` explícito borra, ausente deja como está.
    Es la distinción que hace que el modelo no pueda tener defaults que no sean None.
    """
    from src.models.planned_flight import PlannedFlightUpdate

    borra = PlannedFlightUpdate(takeoff_time=None).model_dump(exclude_unset=True)
    assert borra == {"takeoff_time": None}

    deja = PlannedFlightUpdate(route="SADF SAZM").model_dump(exclude_unset=True)
    assert "takeoff_time" not in deja


def test_el_libro_acepta_los_renglones_de_la_hoja_y_rechaza_lo_absurdo():
    """Migración 020: el PDF corta la hoja donde la corta el libro de papel."""
    from pydantic import ValidationError

    from src.models.logbook import LogbookCreate, LogbookUpdate

    assert LogbookCreate(name="Libro", renglones_por_hoja=12).renglones_por_hoja == 12
    assert LogbookUpdate().renglones_por_hoja is None  # sin tocar, no se cambia
    for malo in (0, 4, 41):
        try:
            LogbookUpdate(renglones_por_hoja=malo)
        except ValidationError:
            continue
        raise AssertionError(f"aceptó {malo} renglones por hoja")


def test_cerrar_la_hoja_es_opcional_y_el_patch_no_lo_pisa():
    """Un vuelo nuevo no cierra la hoja; editar otro campo no toca la marca."""
    from datetime import datetime, timezone

    from src.models.flight import FlightCreate, FlightUpdate

    hora = datetime(2026, 9, 23, 13, 5, tzinfo=timezone.utc)
    nuevo = FlightCreate(date="2026-09-23", route="SADF SADF", landings=4, duration=1.2, takeoff=hora, landing=hora)
    assert nuevo.cierra_hoja is False
    assert "cierra_hoja" not in FlightUpdate(route="SADF SAAR").model_dump(exclude_unset=True)
    assert FlightUpdate(cierra_hoja=True).model_dump(exclude_unset=True) == {"cierra_hoja": True}



def test_marcar_cerrar_hoja_no_recalcula_el_cobro():
    """
    Un PATCH que sólo marca "cerrar hoja" no re-sincroniza el cobro: lo recalcularía
    con el precio por hora de hoy. Cualquier otro cambio, sí (vive en el controlador,
    pero es una función pura).
    """
    from src.controllers.flights import solo_marcas_del_libro

    assert solo_marcas_del_libro({"cierra_hoja": True})
    assert not solo_marcas_del_libro({"cierra_hoja": True, "duration": 1.2})
    assert not solo_marcas_del_libro({"route": "SADF SAAR"})
    assert not solo_marcas_del_libro({})


if __name__ == "__main__":
    fallos = 0
    for nombre, fn in sorted(globals().items()):
        if not nombre.startswith("test_"):
            continue
        try:
            fn()
            print(f"ok   {nombre}")
        except Exception as e:
            # `Exception` y no `AssertionError`: el bug que motivó este archivo se
            # manifiesta como un `ValidationError` al construir el modelo, y si el
            # runner no lo atrapa aborta la corrida entera en vez de reportarlo.
            fallos += 1
            primera = str(e).strip().splitlines()[0]
            print(f"FALLA {nombre}\n      {type(e).__name__}: {primera}")
    print(f"\n{fallos} fallo(s)")
    sys.exit(1 if fallos else 0)
