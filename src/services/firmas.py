"""
Las URLs firmadas de las fotos de publicaciones, reusadas mientras les quede vida.

**Por qué existe.** Supabase firma cada URL con un token que lleva adentro cuándo se
firmó: dos firmas del mismo archivo, con un segundo de diferencia, son dos URLs
distintas. Firmar en cada pedido —como hacía la primera versión de la red— anulaba el
cache del navegador: cada vez que se abría la Red, o la pantalla se volvía a dibujar
después de publicar o de seguir a alguien, el teléfono bajaba de nuevo **todas** las
fotos, aunque los archivos no cambian nunca (se guardan con nombre único y
`cache-control` de un año). Con esto, la misma foto sale con la misma URL durante
horas y el navegador la sirve de su cache.

**No cambia quién ve qué.** La URL se entrega recién después de que el RLS dejó pasar
la fila, igual que antes; y una URL firmada ya era un permiso al portador por seis
horas. Lo único que cambia es que una URL puede llegar con menos vida por delante: el
margen garantiza que nunca menos de `margen` segundos.

Vive en memoria del proceso. Si el backend se reinicia se pierde, y lo único que pasa
es que la próxima página firma de nuevo.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Dict, Iterable, List, Tuple


class CacheDeFirmas:
    """
    `urls(paths)` devuelve una URL firmada por cada path que se pudo firmar.

    - `firmar` recibe los paths que faltan y devuelve `{path: url}`. Un path que no
      vuelve (el archivo ya no está, o falló la firma) no se guarda: se reintenta en
      el próximo pedido en vez de quedar recordado como roto.
    - `duracion` es la vida con la que firma `firmar`, en segundos.
    - `margen`: una URL a la que le quede menos que esto se vuelve a firmar.
    - `maximo`: cuántos paths recordar. Al pasarlo se tiran los vencidos, y si no
      alcanza, todo: es un cache, no una fuente de verdad.
    """

    def __init__(
        self,
        firmar: Callable[[List[str]], Dict[str, str]],
        *,
        duracion: float,
        margen: float,
        maximo: int = 5000,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        if margen >= duracion:
            raise ValueError("El margen tiene que ser menor que la duración de la firma.")
        self._firmar = firmar
        self._duracion = duracion
        self._margen = margen
        self._maximo = maximo
        self._reloj = reloj
        self._cache: Dict[str, Tuple[str, float]] = {}
        self._lock = threading.Lock()

    def urls(self, paths: Iterable[str]) -> Dict[str, str]:
        unicos = list(dict.fromkeys(p for p in paths if p))
        if not unicos:
            return {}
        ahora = self._reloj()
        vigentes: Dict[str, str] = {}
        with self._lock:
            for p in unicos:
                guardada = self._cache.get(p)
                if guardada and guardada[1] - ahora > self._margen:
                    vigentes[p] = guardada[0]
        faltan = [p for p in unicos if p not in vigentes]
        if faltan:
            # Fuera del lock: es un viaje de red, y los demás hilos no tienen por qué
            # esperarlo. Dos hilos pueden firmar el mismo path a la vez; gana el último
            # y las dos URLs sirven.
            nuevas = {p: u for p, u in self._firmar(faltan).items() if p in faltan and u}
            # `ahora` es de antes del viaje: la vida que se anota es un poco menor que
            # la real, nunca mayor.
            vence = ahora + self._duracion
            with self._lock:
                if len(self._cache) + len(nuevas) > self._maximo:
                    self._purgar(ahora, entrantes=len(nuevas))
                for p, u in nuevas.items():
                    self._cache[p] = (u, vence)
            vigentes.update(nuevas)
        return vigentes

    def olvidar(self, paths: Iterable[str]) -> None:
        """Para los archivos que se borran: su URL ya no sirve y no hace falta recordarla."""
        with self._lock:
            for p in paths:
                self._cache.pop(p, None)

    def _purgar(self, ahora: float, *, entrantes: int) -> None:
        vencidas = [p for p, (_, vence) in self._cache.items() if vence - ahora <= self._margen]
        for p in vencidas:
            del self._cache[p]
        # Si sacando lo vencido no hay lugar para lo que entra, se empieza de cero: lo
        # peor que pasa es que la próxima página firme todo de nuevo.
        if len(self._cache) + entrantes > self._maximo:
            self._cache.clear()
