"""
El contenido de la red: las fotos, el chip del vuelo, los límites y la Actividad.

Corre offline: las imágenes se fabrican en memoria con Pillow, y lo demás toma
diccionarios. Ejecutar con `python test_publicaciones.py`; sale con código 1 si algún
check falla.

El check que más importa es el primero: **una foto de teléfono trae la ubicación GPS
de donde se sacó**, y tiene que salir de acá sin ella.
"""

from io import BytesIO

from PIL import Image

from src.models.social import PilotoResumen, ReporteIn, SuscripcionPushIn
from src.services import avisos, firmas, imagenes, social


def check(label, condition):
    print(f"{'✅' if condition else '❌'} {label}")
    return condition


def jpeg_con_exif(ancho=300, alto=200, orientacion=None, gps=True):
    """Una foto como las del teléfono: marca, modelo, ubicación y orientación."""
    img = Image.new("RGB", (ancho, alto), (200, 30, 30))
    # Una franja distinta a la izquierda, para ver hacia dónde quedó rotada.
    for x in range(ancho // 4):
        for y in range(alto):
            img.putpixel((x, y), (30, 30, 200))
    exif = Image.Exif()
    exif[0x010F] = "Apple"  # Make
    exif[0x0110] = "iPhone 15"  # Model
    if orientacion:
        exif[0x0112] = orientacion
    if gps:
        gps_ifd = exif.get_ifd(0x8825)
        gps_ifd[1] = "S"
        gps_ifd[2] = (34.0, 27.0, 29.0)
        gps_ifd[3] = "W"
        gps_ifd[4] = (58.0, 35.0, 20.0)
    salida = BytesIO()
    img.save(salida, "JPEG", exif=exif.tobytes(), quality=90)
    return salida.getvalue()


def rechaza(datos):
    try:
        imagenes.procesar_foto(datos)
    except imagenes.ImagenInvalida:
        return True
    return False


def main() -> bool:
    ok = True

    # ---------------------------------------------------------------- fotos
    original = jpeg_con_exif()
    ok &= check("la foto de prueba de verdad trae GPS", Image.open(BytesIO(original)).getexif().get_ifd(0x8825) != {})

    webp, ancho, alto = imagenes.procesar_foto(original)
    salida = Image.open(BytesIO(webp))
    ok &= check("sale en WebP", salida.format == "WEBP")
    ok &= check("sale SIN EXIF: ni ubicación, ni marca, ni modelo", len(salida.getexif()) == 0 and "exif" not in salida.info)
    ok &= check("devuelve las medidas de lo que guardó", (ancho, alto) == salida.size == (300, 200))

    grande, a, b = imagenes.procesar_foto(jpeg_con_exif(ancho=4000, alto=3000, gps=False))
    ok &= check("achica a 1600 px de lado, manteniendo la proporción", (a, b) == (1600, 1200))

    # Orientación 6: el teléfono la sacó en vertical y guardó los píxeles acostados.
    rotada, a, b = imagenes.procesar_foto(jpeg_con_exif(ancho=300, alto=200, orientacion=6))
    ok &= check("aplica la orientación antes de tirar el EXIF", (a, b) == (200, 300))

    avatar = Image.open(BytesIO(imagenes.procesar_avatar(jpeg_con_exif(ancho=900, alto=400))))
    ok &= check("la foto de perfil sale cuadrada de 512", avatar.size == (512, 512))
    ok &= check("la foto de perfil tampoco lleva EXIF", len(avatar.getexif()) == 0)

    png = BytesIO()
    Image.new("RGBA", (50, 50), (0, 0, 0, 0)).save(png, "PNG")
    fondo = Image.open(BytesIO(imagenes.procesar_foto(png.getvalue())[0])).convert("RGB").getpixel((25, 25))
    ok &= check("lo transparente queda blanco y no negro", fondo[0] > 240 and fondo[1] > 240 and fondo[2] > 240)

    ok &= check("rechaza lo que no es imagen", rechaza(b"hola, esto no es una foto"))
    ok &= check("rechaza un SVG aunque diga ser imagen", rechaza(b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"))
    ok &= check("rechaza un GIF", rechaza(b"GIF89a" + b"\x00" * 20))
    ok &= check("rechaza vacío", rechaza(b""))
    ok &= check("rechaza un JPEG roto", rechaza(b"\xff\xd8\xff" + b"\x00" * 50))
    ok &= check("rechaza más de 12 MB", rechaza(b"\xff\xd8\xff" + b"\x00" * (imagenes.BYTES_MAX + 1)))
    ok &= check("reconoce los tres formatos por sus bytes",
                imagenes.detectar_formato(original) == "jpeg"
                and imagenes.detectar_formato(png.getvalue()) == "png"
                and imagenes.detectar_formato(webp) == "webp")

    # ------------------------------------------------------ el chip del vuelo
    vuelo = {"route": "SADF SADL SAAR", "duration": 1.46, "date": "2026-09-20", "aircraft_id": "a1"}
    avion = {"type": "Cessna 152", "registration": "LV-S001"}
    chip = social.resumen_de_vuelo(vuelo, avion, ruta=True, duracion=True, aeronave=True, fecha=True)
    ok &= check("el chip lleva lo prendido", chip == {"ruta": "SADF → SAAR", "duracion": 1.5, "aeronave": "Cessna 152", "fecha": "2026-09-20"})
    ok &= check("NUNCA la matrícula", "LV-S001" not in str(chip))
    ok &= check("los puntos intermedios de una travesía no salen", "SADL" not in str(chip))
    ok &= check("por defecto: ruta y duración, sin avión ni fecha",
                social.resumen_de_vuelo(vuelo, avion) == {"ruta": "SADF → SAAR", "duracion": 1.5})
    ok &= check("todo apagado no deja chip",
                social.resumen_de_vuelo(vuelo, avion, ruta=False, duracion=False) is None)
    ok &= check("un vuelo local se dice local", social.ruta_legible("SADF SADF") == "SADF · local")
    ok &= check("acepta guiones y flechas", social.ruta_legible("sadf-saar") == "SADF → SAAR")
    ok &= check("un simulador no tiene ruta", social.ruta_legible("LOCAL") is None)

    # ------------------------------------------------------------- límites
    ok &= check("no se publica nada vacío", social.validar_publicacion("   ", 0, False) is not None)
    ok &= check("alcanza con una foto", social.validar_publicacion(None, 1, False) is None)
    ok &= check("alcanza con un vuelo", social.validar_publicacion(None, 0, True) is None)
    ok &= check("más de cuatro fotos no", social.validar_publicacion("hola", 5, False) is not None)
    ok &= check("más de 1000 caracteres no", social.validar_publicacion("x" * 1001, 0, False) is not None)

    def comentario_invalido(texto):
        try:
            social.validar_comentario(texto)
        except ValueError:
            return True
        return False

    ok &= check("un comentario vacío no", comentario_invalido("   "))
    ok &= check("un comentario de más de 500 no", comentario_invalido("x" * 501))
    ok &= check("un comentario se limpia", social.validar_comentario("  ¡buen vuelo!  ") == "¡buen vuelo!")
    ok &= check("los nombres de las pantallas de la red están reservados",
                all(h in social.RESERVADOS for h in ("buscar", "actividad", "publicar")))

    # ------------------------------------------------------------ actividad
    eventos = [
        {"tipo": "aplauso", "created_at": "2026-09-20T10:00:00+00:00"},
        {"tipo": "seguidor", "created_at": "2026-09-22T09:30:00.123456+00:00"},
        {"tipo": "comentario", "created_at": "2026-09-21T12:00:00Z"},
    ]
    orden = social.ordenar_actividad(eventos, "2026-09-21T00:00:00+00:00")
    ok &= check("la actividad va de lo más nuevo a lo más viejo",
                [e["tipo"] for e in orden] == ["seguidor", "comentario", "aplauso"])
    ok &= check("es nuevo lo posterior a la última vez que la abrió",
                [e["nuevo"] for e in orden] == [True, True, False])
    ok &= check("sin fecha de vista, nada es nuevo",
                not any(e["nuevo"] for e in social.ordenar_actividad([dict(e) for e in eventos], None)))

    ok &= check("la URL del avatar es la pública del bucket",
                social.url_avatar("https://x.supabase.co/", "abc.webp")
                == "https://x.supabase.co/storage/v1/object/public/avatares/abc.webp")
    ok &= check("sin avatar, sin URL", social.url_avatar("https://x.supabase.co", None) is None)

    # ------------------------------------------------------------ firmas estables
    # La misma foto tiene que salir con la misma URL mientras le quede vida: si cambia
    # en cada pedido, el navegador la baja de nuevo cada vez que se dibuja la Red.
    reloj = {"t": 1000.0}
    pedidos = []

    def firmar(paths):
        pedidos.append(list(paths))
        return {p: f"https://x/{p}?t={reloj['t']}" for p in paths if p != "roto.webp"}

    cache = firmas.CacheDeFirmas(firmar, duracion=600, margen=200, maximo=4, reloj=lambda: reloj["t"])
    primera = cache.urls(["a.webp", "b.webp"])
    reloj["t"] += 300  # le quedan 300 s: más que el margen
    segunda = cache.urls(["b.webp", "a.webp"])
    ok &= check("una firma con vida se reusa: misma URL, sin pedir de nuevo",
                primera == segunda and len(pedidos) == 1)
    cache.urls(["a.webp", "c.webp"])
    ok &= check("sólo se firma lo que falta", pedidos[-1] == ["c.webp"])
    reloj["t"] += 150  # a `a` le quedan 150 s: menos que el margen
    tercera = cache.urls(["a.webp"])
    ok &= check("cerca de vencer, se firma de nuevo", tercera["a.webp"] != primera["a.webp"] and pedidos[-1] == ["a.webp"])
    cache.urls(["roto.webp"])
    cache.urls(["roto.webp"])
    ok &= check("lo que no se pudo firmar no queda recordado", pedidos[-2:] == [["roto.webp"], ["roto.webp"]])
    ok &= check("los paths repetidos o vacíos se piden una vez",
                list(cache.urls(["d.webp", "d.webp", ""])) == ["d.webp"] and pedidos[-1] == ["d.webp"])
    cache.olvidar(["d.webp"])
    cache.urls(["d.webp"])
    ok &= check("una foto borrada se olvida", pedidos[-1] == ["d.webp"])
    cache.urls(["e.webp", "f.webp", "g.webp"])
    ok &= check("pasado el máximo, el cache no crece sin límite", len(cache._cache) <= 4)
    try:
        firmas.CacheDeFirmas(firmar, duracion=100, margen=100)
        margen_invalido = False
    except ValueError:
        margen_invalido = True
    ok &= check("un margen igual a la duración se rechaza", margen_invalido)

    # ------------------------------------------------------------ bloqueos
    ok &= check("a quien bloqueé no le veo las horas, aunque sea público",
                social.puede_ver_horas("publico", "bloqueado") is False)
    ok &= check("sin bloqueo, lo público se sigue viendo", social.puede_ver_horas("publico", "ninguna") is True)
    ok &= check("'bloqueado' es una relación válida para la salida",
                PilotoResumen(handle="x.y", nombre_visible="X", visibilidad="publico", relacion="bloqueado").relacion
                == "bloqueado")

    # ------------------------------------------------------------ avisos push
    a = avisos.armar_aviso("aplauso", "Juan Alumno", texto="Mi primer solo, con viento cruzado en la final")
    ok &= check("el aviso de un aplauso dice quién y sobre qué",
                a["titulo"] == "Juan Alumno aplaudió tu publicación" and a["cuerpo"].startswith("Mi primer solo"))
    ok &= check("los avisos de un tipo se reemplazan entre sí (misma etiqueta)", a["etiqueta"] == "vector-aplauso")
    c = avisos.armar_aviso("comentario", "Ana", texto="x" * 300)
    ok &= check("un comentario largo se corta", len(c["cuerpo"]) <= 120 and c["cuerpo"].endswith("…"))
    ok &= check("una solicitud lleva a la Actividad",
                avisos.armar_aviso("solicitud", "Ana")["url"] == "/dashboard/pilotos/actividad")
    ok &= check("aceptar lleva al perfil del que aceptó",
                avisos.armar_aviso("aceptada", "Ana", url="/dashboard/pilotos/ana.p")["url"] == "/dashboard/pilotos/ana.p")
    ok &= check("sin nombre, 'Un piloto'", avisos.armar_aviso("seguidor", "  ")["titulo"] == "Un piloto empezó a seguirte")
    try:
        avisos.armar_aviso("otra-cosa", "Ana")
        tipo_raro = False
    except ValueError:
        tipo_raro = True
    ok &= check("un tipo de aviso desconocido es un error, no un aviso vacío", tipo_raro)
    ok &= check("404 y 410 son suscripciones muertas",
                avisos.es_suscripcion_muerta(404) and avisos.es_suscripcion_muerta(410)
                and not avisos.es_suscripcion_muerta(500) and not avisos.es_suscripcion_muerta(None))

    def invalido(modelo, **datos):
        try:
            modelo(**datos)
        except ValueError:
            return True
        return False

    ok &= check("un reporte sin motivo no", invalido(ReporteIn, tipo="perfil", objetivo="x.y", motivo="  "))
    ok &= check("un reporte de un tipo que no existe no", invalido(ReporteIn, tipo="vuelo", objetivo="x", motivo="spam"))
    ok &= check("un motivo de más de 500 no", invalido(ReporteIn, tipo="perfil", objetivo="x.y", motivo="m" * 501))
    ok &= check("un reporte bien armado se limpia",
                ReporteIn(tipo="comentario", objetivo=" abc ", motivo=" spam ").motivo == "spam")
    ok &= check("una suscripción que no es https no",
                invalido(SuscripcionPushIn, endpoint="http://x", keys={"p256dh": "a", "auth": "b"}))

    print("\n" + ("Todo OK" if ok else "Hay checks fallando"))
    return bool(ok)


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
