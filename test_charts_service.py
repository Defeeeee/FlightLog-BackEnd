"""
`src/services/charts.py`, sobre todo la parte que importa: que no se pueda
escapar de la carpeta configurada. Corre offline con `python test_charts_service.py`,
armando y borrando un árbol de PDF de prueba en un directorio temporal.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

from src.services import charts


def _armar_arbol(raiz: Path) -> None:
    """
    SADF con dos categorías y un intruso: un .txt que no debería listarse, y un
    archivo fuera del árbol de aeródromos para el intento de escape.
    """
    (raiz / "SADF" / "IACs").mkdir(parents=True)
    (raiz / "SADF" / "IACs" / "ILS RWY 05.pdf").write_bytes(b"%PDF-1.4 fake")
    (raiz / "SADF" / "IACs" / "notas.txt").write_text("no es una carta")
    (raiz / "SADF" / "Airport Diagrams 10-9").mkdir(parents=True)
    (raiz / "SADF" / "Airport Diagrams 10-9" / "10-9.pdf").write_bytes(b"%PDF-1.4 fake")
    (raiz / "secreto.pdf").write_bytes(b"no deberia poder llegar aca afuera")
    # Un "aerodromo" de tres letras: si la validacion de ICAO no corriera, esta
    # carta existe de verdad y resolver_carta la encontraria igual.
    (raiz / "SAD" / "IACs").mkdir(parents=True)
    (raiz / "SAD" / "IACs" / "sneaky.pdf").write_bytes(b"%PDF-1.4 fake")


def main() -> bool:
    ok = True

    def check(nombre: str, condicion: bool) -> bool:
        nonlocal ok
        estado = "ok  " if condicion else "FALLA"
        print(f"{estado} {nombre}")
        if not condicion:
            ok = False
        return condicion

    with tempfile.TemporaryDirectory() as tmp:
        raiz = Path(tmp)
        _armar_arbol(raiz)
        raiz_str = str(raiz)

        cartas = charts.listar_cartas(raiz_str, "SADF")
        check(
            "lista sólo los .pdf, no el .txt",
            len(cartas) == 2 and all(c["archivo"].endswith(".pdf") for c in cartas),
        )
        check(
            "un icao en minúsculas resuelve igual",
            charts.listar_cartas(raiz_str, "sadf") == cartas,
        )
        check(
            "un aeródromo sin carpeta da lista vacía, no error",
            charts.listar_cartas(raiz_str, "SAEZ") == [],
        )
        check(
            "un icao con forma rara da lista vacía",
            charts.listar_cartas(raiz_str, "SAD") == [] and charts.listar_cartas(raiz_str, "../..") == [],
        )
        check(
            "sin JEPPESEN_CHARTS_DIR configurado, lista vacía y no una excepción",
            charts.listar_cartas(None, "SADF") == [],
        )
        check(
            "una raíz que no existe en disco también da vacío",
            charts.listar_cartas(str(raiz / "no-existe"), "SADF") == [],
        )

        resuelto = charts.resolver_carta(raiz_str, "SADF", "IACs", "ILS RWY 05.pdf")
        check("resuelve la carta real", resuelto is not None and resuelto.is_file())

        check(
            # A propósito contra un archivo que SÍ existe en disco bajo "SAD": si
            # sólo se probara con un archivo inexistente, un regex de ICAO roto
            # pasaría igual —el 404 vendría por el archivo, no por el ICAO— y el
            # chequeo de la validación real quedaría sin probar.
            "un icao con forma rara no resuelve ni lo que sí existe en disco",
            charts.resolver_carta(raiz_str, "SAD", "IACs", "sneaky.pdf") is None,
        )

        check(
            "un archivo que no es PDF no se sirve aunque exista",
            charts.resolver_carta(raiz_str, "SADF", "IACs", "notas.txt") is None,
        )
        check(
            "un archivo que no existe da None",
            charts.resolver_carta(raiz_str, "SADF", "IACs", "no-existe.pdf") is None,
        )

        # El caso que de verdad importa: escaparse de la raíz con `..`, en
        # cualquiera de los dos segmentos que llegan de la URL.
        check(
            "`..` en el archivo no escapa de la raíz",
            charts.resolver_carta(raiz_str, "SADF", "IACs", "../../secreto.pdf") is None,
        )
        check(
            "`..` en la categoría tampoco",
            charts.resolver_carta(raiz_str, "SADF", "../..", "secreto.pdf") is None,
        )
        check(
            "una ruta absoluta como archivo no reemplaza la raíz",
            charts.resolver_carta(raiz_str, "SADF", "IACs", "/etc/passwd") is None,
        )

    print("\n" + ("Todo OK" if ok else "Hay checks fallando"))
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
