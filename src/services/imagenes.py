"""
Las fotos que suben los pilotos, antes de que toquen el storage.

**Toda foto se re-codifica acá, siempre.** El navegador ya la achica antes de subirla
(`src/lib/imagen-cliente.ts` del frontend), pero eso es comodidad, no seguridad: un
cliente cualquiera puede mandar el original. Re-codificar con Pillow es lo que garantiza
tres cosas:

- **Sin EXIF.** Una foto de teléfono trae la ubicación GPS exacta de donde se sacó, el
  modelo del teléfono y la hora. Guardar sin `exif=` las descarta todas. La orientación
  se aplica antes (`exif_transpose`), así que la foto no queda de costado al perderla.
- **Sin sorpresas de formato.** Sólo entran JPEG, PNG y WebP, reconocidos por sus
  primeros bytes y no por la extensión ni el `Content-Type`, que manda el cliente. Lo
  que sale es siempre WebP: nada de SVG con scripts ni archivos políglotas.
- **Tamaño acotado.** 1600 px de lado para publicaciones y 512 px de lado, recortada al
  cuadrado, para la foto de perfil. Y un tope de píxeles contra las bombas de
  descompresión: una imagen chica en bytes que se expande a gigas en memoria.
"""

import warnings
from io import BytesIO
from typing import Optional, Tuple

from PIL import Image, ImageOps, UnidentifiedImageError

#: Lo que se acepta crudo, antes de procesar. El navegador manda bastante menos.
BYTES_MAX = 12 * 1024 * 1024

#: ~40 megapíxeles: sobra para cualquier cámara de teléfono y corta las bombas.
PIXELES_MAX = 40_000_000
Image.MAX_IMAGE_PIXELS = PIXELES_MAX

LADO_PUBLICACION = 1600
LADO_AVATAR = 512
CALIDAD = 82


class ImagenInvalida(ValueError):
    """El mensaje es para el piloto: se muestra tal cual."""


def detectar_formato(datos: bytes) -> Optional[str]:
    """El formato por sus primeros bytes, o `None` si no es uno de los aceptados."""
    if datos[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if datos[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if datos[:4] == b"RIFF" and datos[8:12] == b"WEBP":
        return "webp"
    return None


def _abrir(datos: bytes) -> Image.Image:
    if not datos:
        raise ImagenInvalida("La foto llegó vacía.")
    if len(datos) > BYTES_MAX:
        raise ImagenInvalida("La foto pesa más de 12 MB.")
    if detectar_formato(datos) is None:
        raise ImagenInvalida("Formato no soportado: subí una foto JPG, PNG o WebP.")

    # Pillow avisa con un warning antes de llegar al error: acá los dos cortan.
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            imagen = Image.open(BytesIO(datos))
            imagen.load()
        except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError) as exc:
            raise ImagenInvalida("No pudimos leer esa foto. Probá con otra.") from exc

    # La orientación del EXIF, aplicada a los píxeles: sin esto, al descartar el EXIF la
    # foto de un teléfono en vertical quedaría acostada.
    imagen = ImageOps.exif_transpose(imagen)

    # Transparencia sobre blanco y no sobre negro, que es lo que haría `convert("RGB")`.
    if imagen.mode in ("RGBA", "LA", "P"):
        imagen = imagen.convert("RGBA")
        fondo = Image.new("RGB", imagen.size, (255, 255, 255))
        fondo.paste(imagen, mask=imagen.getchannel("A"))
        return fondo
    return imagen.convert("RGB")


def _webp(imagen: Image.Image) -> bytes:
    salida = BytesIO()
    # Sin `exif=` a propósito: es lo que deja afuera la ubicación y todo lo demás.
    imagen.save(salida, "WEBP", quality=CALIDAD, method=4)
    return salida.getvalue()


def procesar_foto(datos: bytes, lado_max: int = LADO_PUBLICACION) -> Tuple[bytes, int, int]:
    """La foto de una publicación: WebP de hasta `lado_max` px, sin EXIF. `(bytes, ancho, alto)`."""
    imagen = _abrir(datos)
    imagen.thumbnail((lado_max, lado_max), Image.Resampling.LANCZOS)
    return _webp(imagen), imagen.width, imagen.height


def procesar_avatar(datos: bytes, lado: int = LADO_AVATAR) -> bytes:
    """La foto de perfil: cuadrada, recortada al centro, WebP sin EXIF."""
    imagen = _abrir(datos)
    imagen = ImageOps.fit(imagen, (lado, lado), Image.Resampling.LANCZOS)
    return _webp(imagen)
