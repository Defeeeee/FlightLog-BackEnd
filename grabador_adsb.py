"""
El grabador ADS-B (migración 034, `services/adsb.py`): graba en vivo las posiciones de los
aviones que están en algún Hangar.

    venv/bin/python grabador_adsb.py

Corre en el VPS como su propio proceso de PM2 (`grabador-adsb`), al lado del backend; el
deploy lo reinicia (`.github/workflows/deploy.yml`).

- Cada 10 s pide a adsb.fi (y si falla, a adsb.lol) el tráfico alrededor de cada punto de `ADSB_PUNTOS` (por defecto,
  Buenos Aires con 250 millas), para descubrir aviones del Hangar; y los ya conocidos, por su
  código, en un solo pedido: así una navegación lejos de Buenos Aires se sigue grabando
  mientras alguna antena la escuche.
- Cada 10 min relee las matrículas de los Hangares y los códigos ya aprendidos.
- Una vez por hora borra lo que tiene más de 30 días.

Los datos son de adsb.fi (uso no comercial, con cita) o de adsb.lol (ODbL). Si no contestan, espera y sigue: no hay nada que
recuperar, lo que no se vio no se vio.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import httpx

from src.services.adsb import limite_de_retencion, matriculas_del_hangar, nuestros, posicion, vale_guardar
from src.supabase_client import SupabaseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("grabador-adsb")

#: Las fuentes, en orden: si la primera falla, la siguiente. adsb.fi (2026-10-23): adsb.lol
#: le contestaba 429 a la IP del VPS casi siempre, aun a un pedido cada 20 s. adsb.fi es
#: "para uso personal y no comercial", con cita y link: si Vector cobra, hay que escribirles
#: o tener un receptor propio. Las dos responden con el formato de la v2 de ADSBexchange.
#: Los aviones ya conocidos, por su código, sin importar dónde estén (adsb.fi).
POR_HEX = "https://opendata.adsb.fi/api/v2/hex/{lista}"
FUENTES = [
    ("adsb.fi", "https://opendata.adsb.fi/api/v3/lat/{lat}/lon/{lon}/dist/{radio}"),
    ("adsb.lol", "https://api.adsb.lol/v2/point/{lat}/{lon}/{radio}"),
]
CADA = 10
RELEER_CADA = 600
LIMPIAR_CADA = 3600
#: El latido: cuándo fue la última vuelta y cómo salió. Lo muestra `GET /health`, para saber
#: que el grabador sigue vivo sin entrar al VPS (`latido_del_grabador` en `services/adsb.py`).
LATIDO = os.getenv("ADSB_LATIDO", "/tmp/grabador-adsb.json")
UA = "Vector (vector.fdiaznem.com.ar; bitacora de vuelo; contacto fdiaznemeth@gmail.com)"


def puntos() -> List[Tuple[float, float, int]]:
    crudo = os.getenv("ADSB_PUNTOS", "-34.6,-58.6,250")
    salida = []
    for p in crudo.split(";"):
        lat, lon, radio = p.split(",")
        salida.append((float(lat), float(lon), min(int(radio), 250)))
    return salida


def releer(cliente) -> Tuple[set, Dict[str, str]]:
    aviones = cliente.table("aircraft").select("registration,is_simulator").execute().data or []
    conocidos = cliente.table("adsb_aviones").select("matricula,hex").execute().data or []
    return matriculas_del_hangar(aviones), {c["hex"]: c["matricula"] for c in conocidos}


def main() -> None:
    cliente = SupabaseManager.get_service_client()
    http = httpx.Client(timeout=8, headers={"User-Agent": UA})
    matriculas, hex_conocidos = releer(cliente)
    log.info("arranco: %d matrículas, %d códigos conocidos, puntos %s", len(matriculas), len(hex_conocidos), puntos())
    ultimas: Dict[str, dict] = {}
    releido = limpiado = 0.0
    # Para medir desde `/health` cuántas vueltas salen y por qué fallan las otras.
    cuenta = {"vueltas_ok": 0, "vueltas_fallidas": 0}
    ultimo_error: Dict[str, object] = {}

    while True:
        inicio = time.monotonic()
        latido: Dict[str, object] = {"vuelta": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ok": False}
        espera = 0.0
        try:
            if inicio - releido > RELEER_CADA:
                matriculas, hex_conocidos = releer(cliente)
                releido = inicio
            if inicio - limpiado > LIMPIAR_CADA:
                cliente.table("adsb_posiciones").delete().lt("visto_at", limite_de_retencion(datetime.now(timezone.utc))).execute()
                limpiado = inicio

            trafico: Dict[str, dict] = {}
            for lat, lon, radio in puntos():
                for i, (fuente, url) in enumerate(FUENTES):
                    r = http.get(url.format(lat=lat, lon=lon, radio=radio))
                    if r.status_code != 200 and i < len(FUENTES) - 1:
                        log.info("%s contestó %s: pruebo la siguiente", fuente, r.status_code)
                        continue
                    r.raise_for_status()
                    latido["fuente"] = fuente
                    break
                for a in r.json().get("ac") or []:
                    trafico[str(a.get("hex"))] = a
            # Y los ya conocidos, por su código, estén donde estén: el radio de arriba no llega
            # a una navegación a Córdoba. Un pedido para todos (adsb.fi acepta la lista).
            if hex_conocidos:
                r = http.get(POR_HEX.format(lista=",".join(sorted(hex_conocidos))[:3000]))
                if r.status_code == 200:
                    for a in r.json().get("ac") or []:
                        trafico[str(a.get("hex"))] = a
            ahora = datetime.now(timezone.utc)

            filas = []
            for matricula, h, a in nuestros(trafico.values(), matriculas, hex_conocidos):
                if hex_conocidos.get(h) != matricula:
                    cliente.table("adsb_aviones").upsert({"matricula": matricula, "hex": h, "visto_at": ahora.isoformat()}).execute()
                    hex_conocidos[h] = matricula
                    log.info("aprendí %s = %s", matricula, h)
                p = posicion(a, ahora)
                if p and vale_guardar(p, ultimas.get(h)):
                    filas.append({"matricula": matricula, "hex": h, **p})
                    ultimas[h] = p
            if filas:
                cliente.table("adsb_posiciones").insert(filas).execute()
            latido.update(ok=True, trafico=len(trafico), nuestros_en_el_aire=len(filas), matriculas=len(matriculas))
            cuenta["vueltas_ok"] += 1
        except httpx.HTTPStatusError as e:
            # adsb.lol limita los pedidos: si dice cuánto esperar, se espera eso.
            cuenta["vueltas_fallidas"] += 1
            r = e.response
            ultimo_error = {"cuando": latido["vuelta"], "http": r.status_code, "retry_after": r.headers.get("retry-after"), "cuerpo": r.text[:160]}
            log.warning("adsb.lol contestó %s: %s", r.status_code, r.text[:160])
            try:
                espera = float(r.headers.get("retry-after") or 0)
            except ValueError:
                espera = 0.0
            espera = min(max(espera, 20.0), 300.0)
        except Exception as e:  # una vuelta fallida no tira abajo el grabador
            cuenta["vueltas_fallidas"] += 1
            ultimo_error = {"cuando": latido["vuelta"], "tipo": type(e).__name__, "detalle": str(e)[:160]}
            log.warning("vuelta fallida: %r", e)
            espera = 20.0
        latido.update(cuenta)
        if ultimo_error:
            latido["ultimo_error"] = ultimo_error
        try:
            with open(LATIDO, "w") as f:
                json.dump(latido, f)
        except OSError:
            pass
        time.sleep(espera or max(0.0, CADA - (time.monotonic() - inicio)))


if __name__ == "__main__":
    main()
