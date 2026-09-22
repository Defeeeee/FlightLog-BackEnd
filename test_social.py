"""
La red social: el @, quién ve las horas de quién, y cuáles son esas horas.

Corre offline —todo lo que se prueba acá toma diccionarios y devuelve valores, sin
base ni server—. Ejecutar con `python test_social.py`; sale con código 1 si algún
check falla.

El check que más importa es la matriz de `puede_ver_horas`: es la única línea entre
un perfil privado y cualquiera que tenga el link.
"""

from pydantic import ValidationError

from src.models.social import PerfilPublicoIn
from src.services import social


def check(label, condition):
    print(f"{'✅' if condition else '❌'} {label}")
    return condition


def rechaza(crudo):
    try:
        social.validar_handle(crudo)
    except social.HandleInvalido:
        return True
    return False


def vuelo(**campos):
    base = {"aircraft_id": "a1", "duration": 0}
    base.update(campos)
    return base


def main() -> bool:
    ok = True

    # ------------------------------------------------------------------ el @
    ok &= check("un @ común es válido", social.validar_handle("fede.dn") == "fede.dn")
    ok &= check("se normaliza: sin arroba, sin espacios, en minúsculas",
                social.validar_handle("  @Fede.DN ") == "fede.dn")
    ok &= check("acepta números y guion bajo", social.validar_handle("piloto_01") == "piloto_01")
    ok &= check("tres caracteres alcanzan", social.validar_handle("abc") == "abc")
    ok &= check("rechaza menos de tres", rechaza("ab"))
    ok &= check("rechaza más de veinte", rechaza("a" * 21))
    ok &= check("acepta exactamente veinte", social.validar_handle("a" * 20) == "a" * 20)
    ok &= check("rechaza acentos", rechaza("fedé"))
    ok &= check("rechaza espacios en el medio", rechaza("fe de"))
    ok &= check("rechaza el guion medio", rechaza("fe-de"))
    ok &= check("rechaza empezar con guion bajo", rechaza("_fede"))
    ok &= check("rechaza terminar con punto", rechaza("fede."))
    ok &= check("rechaza dos puntos seguidos", rechaza("fe..de"))
    ok &= check("rechaza los reservados", rechaza("vector") and rechaza("@ANAC") and rechaza("soporte"))
    ok &= check("rechaza vacío y None", rechaza("") and rechaza(None))

    # ---------------------------------------------------------- la relación
    ok &= check("sin sesión es anónimo", social.relacion_con(None, "p", None) == "anonimo")
    ok &= check("el dueño es propio", social.relacion_con("p", "p", None) == "propio")
    ok &= check("aceptado es siguiendo", social.relacion_con("v", "p", "aceptado") == "siguiendo")
    ok &= check("pendiente es pendiente", social.relacion_con("v", "p", "pendiente") == "pendiente")
    ok &= check("sin fila es ninguna", social.relacion_con("v", "p", None) == "ninguna")

    # ------------------------------------------------- quién ve las horas
    ver = social.puede_ver_horas
    ok &= check("público: lo ve un anónimo", ver("publico", "anonimo"))
    ok &= check("público: lo ve cualquiera con sesión", ver("publico", "ninguna"))
    ok &= check("privado: NO lo ve un anónimo", not ver("privado", "anonimo"))
    ok &= check("privado: NO lo ve alguien sin relación", not ver("privado", "ninguna"))
    ok &= check("privado: NO lo ve una solicitud pendiente", not ver("privado", "pendiente"))
    ok &= check("privado: lo ve un seguidor aceptado", ver("privado", "siguiendo"))
    ok &= check("privado: lo ve el dueño", ver("privado", "propio"))
    ok &= check("una visibilidad rara cuenta como privada",
                not ver("PUBLICO", "anonimo") and not ver("", "anonimo") and not ver(None, "anonimo"))

    # ------------------------------------------------------------ las horas
    aeronaves = [{"id": "a1", "is_simulator": False}, {"id": "sim", "is_simulator": True}]
    vuelos = [
        vuelo(duration=1.2, pic_day_loc=1.2),
        vuelo(duration=2.0, pic_day_tra=1.5, pic_night_tra=0.5, **{"IMC Pil": 0.4}),
        vuelo(duration=0.8, sic_night_loc=0.8, **{"IMC Cop": 0.3}),
        # Un simulador con horas cargadas por error en las columnas de vuelo: no
        # tiene que sumar nada.
        vuelo(aircraft_id="sim", duration=5, pic_day_loc=5, **{"IMC Pil": 5}),
        # Nulos, como llegan de la base cuando la columna no se cargó.
        vuelo(duration=None, pic_day_loc=None, **{"IMC Pil": None}),
    ]
    libros = [{
        "opening_pic_day_loc": 10, "opening_pic_day_tra": 5, "opening_pic_night_loc": 1,
        "opening_pic_night_tra": 0, "opening_sic_day_loc": 0, "opening_sic_day_tra": 2,
        "opening_sic_night_loc": 0, "opening_sic_night_tra": 0.5,
        "opening_imc_pil": 1.5, "opening_imc_cop": 0,
    }]
    h = social.estadisticas_publicas(vuelos, libros, aeronaves)
    ok &= check("el total suma duración y apertura de PIC y SIC, sin el simulador",
                h["total"] == 4.0 + 16.0 + 2.5)
    ok &= check("PIC suma las cuatro columnas y su apertura", h["pic"] == 3.2 + 16.0)
    ok &= check("travesía suma las de travesía de PIC y SIC", h["travesia"] == 2.0 + 7.5)
    ok &= check("noche suma las nocturnas de PIC y SIC", h["noche"] == 1.3 + 1.5)
    ok &= check("instrumentos lee las columnas con espacios", h["instrumentos"] == 0.7 + 1.5)
    ok &= check("sin nada cargado, todo es cero",
                social.estadisticas_publicas([], [], []) == {
                    "total": 0, "pic": 0, "travesia": 0, "noche": 0, "instrumentos": 0})
    ok &= check("redondea a un decimal",
                social.estadisticas_publicas([vuelo(duration=0.1), vuelo(duration=0.2)], [], [])["total"] == 0.3)
    ok &= check("pide las columnas con espacios entre comillas",
                '"IMC Pil"' in social.COLUMNAS_VUELO and "route" not in social.COLUMNAS_VUELO
                and "date" not in social.COLUMNAS_VUELO)

    # ------------------------------------------------------------ búsqueda
    ok &= check("la búsqueda saca lo que rompe el filtro de PostgREST",
                social.limpiar_busqueda("ana, (lopez)%*") == "ana lopez")
    ok &= check("la búsqueda ignora la arroba y las mayúsculas",
                social.limpiar_busqueda("@Fede") == "fede")
    ok &= check("la búsqueda se corta en 40", len(social.limpiar_busqueda("a" * 100)) == 40)

    # ------------------------------------------------------------- el modelo
    p = PerfilPublicoIn(handle="@Fede.DN", nombre_visible="  Fede  ", licencia="", bio="  ")
    ok &= check("el modelo normaliza el @ y limpia los opcionales vacíos",
                p.handle == "fede.dn" and p.nombre_visible == "Fede" and p.licencia is None and p.bio is None)
    ok &= check("el perfil arranca público", p.visibilidad == "publico")

    def invalido(**campos):
        base = {"handle": "fede", "nombre_visible": "Fede"}
        base.update(campos)
        try:
            PerfilPublicoIn(**base)
        except ValidationError:
            return True
        return False

    ok &= check("el modelo rechaza un @ inválido", invalido(handle="a"))
    ok &= check("el modelo rechaza un nombre vacío", invalido(nombre_visible="   "))
    ok &= check("el modelo rechaza una bio de más de 160", invalido(bio="x" * 161))
    ok &= check("el modelo rechaza una visibilidad inventada", invalido(visibilidad="amigos"))

    print("\n" + ("Todo OK" if ok else "Hay checks fallando"))
    return bool(ok)


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
