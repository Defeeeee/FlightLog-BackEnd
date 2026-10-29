"""
El CAD de ANAC desde el servidor, para el modo "Pasar al CAD desde Vector" (migración 036).

## Cómo entra

El CAD no tiene API pública. Su portal (`cad.anac.gob.ar/portalApp/`) entra por OpenID
Connect contra `login.anac.gob.ar` (IdentityServer): flujo implícito con el cliente público
`portalAplicaciones` y el scope `openid profile legacyCookie`. Con el token, pide
`PortalAplicaciones/api/CAD/cookiePorUsuario`, que deja la cookie con la que anda la API del
CAD (`foliadoweb/api/VueloTripulante/…`, la misma que usa el marcador). Acá se hacen esos
mismos pasos con el usuario y la contraseña que el piloto guardó (leído el 2026-10-28, ver la
bitácora del frontend).

El formulario de login es `Username`, `Password`, `ReturnUrl`, `Time`, `button=login` y el
token antifalsificación, sin captcha.

## Lo que no se hace nunca

- **Reintentar una contraseña rechazada.** ANAC tiene "Recupero y desbloqueo": varias
  equivocaciones probablemente bloquean la cuenta. Si el login vuelve con el formulario, la
  conexión queda 'rechazada' y no se prueba más hasta que el piloto la escriba de nuevo.
- **Tocar la DDJJ.** Sólo hay lectura de listas y vuelos, y "Crear" (`RUTAS_GET`,
  `crear_vuelo`): la declaración jurada la hace el piloto en el CAD.
- **Guardar la contraseña en claro.** Va cifrada con Fernet y la clave vive en el `.env`
  (`CAD_CLAVE_CIFRADO`). Sin la clave, el modo está apagado.
"""

from __future__ import annotations

import asyncio
import html
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken

from src.config import settings

LOGIN = "https://login.anac.gob.ar"
CAD = "https://cad.anac.gob.ar"
REDIRECCION = f"{CAD}/portalApp/"
API = f"{CAD}/foliadoweb/api/VueloTripulante/"
COOKIE_DEL_CAD = f"{CAD}/PortalAplicaciones/api/CAD/cookiePorUsuario"

# ------------------------------------------------- como el navegador del CAD ---
#
# Los encabezados son los de Chrome usando el CAD: navegación para las páginas del login,
# `fetch` del mismo sitio para la API (lo que hace la app del CAD, y el marcador desde su
# pestaña). Un User-Agent con "Vector" se distinguía de cualquier piloto.
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
_CHROME = {
    "User-Agent": _UA,
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
    "sec-ch-ua": '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}
_PAGINA = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
}
_APP_CAD = f"{CAD}/foliadoweb/"


def _api(referer: str = _APP_CAD, **extra: str) -> Dict[str, str]:
    """Un `fetch` de la app del CAD a su propia API."""
    return {
        "Accept": "application/json, text/plain, */*",
        "Referer": referer,
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        **extra,
    }


def _navegar(sitio: str, referer: Optional[str] = None, **extra: str) -> Dict[str, str]:
    h = {**_PAGINA, "Sec-Fetch-Site": sitio, **extra}
    if referer:
        h["Referer"] = referer
    return h

#: Lo único que se lee del CAD. Nada de la DDJJ.
RUTAS_GET = {
    "GetPagedList",
    "Get",
    "GetFinalidadListItem",
    "GetAutoridadesListItem",
    "GetLugarAterrizajeListItem",
    "GetSimuladoresListItem",
    "GetModelosPorSimuladorListItem",
}

#: Las listas son públicas e iguales para todos: se guardan un rato.
_LISTAS_PUBLICAS = {"GetFinalidadListItem", "GetAutoridadesListItem", "GetLugarAterrizajeListItem", "GetSimuladoresListItem", "GetModelosPorSimuladorListItem"}
_TTL_LISTAS = 7 * 24 * 3600
#: Cuánto se reusa una sesión abierta, como mucho. Antes vence la del CAD, y entonces `pedir`
#: entra de nuevo: cada login es lo que más se nota del lado de ANAC.
_TTL_SESION = 8 * 3600
#: La lista de vuelos de un piloto se reusa un rato: abrir "Pasar al CAD" varias veces no
#: vuelve a pedírsela a ANAC. "Crear" la borra.
_TTL_VUELOS = 30 * 60

# ------------------------------------------------------- cuidar a ANAC ---
#
# ANAC bloquea por horas la IP desde la que se entra varias veces (2026-10-28: primero el VPS,
# después la salida por amenaba, con 3 logins en media hora). Todos los pilotos salen por la
# misma IP, así que los dos frenos son de todo el servidor, no de cada piloto:
#
# - si ANAC no acepta la conexión, no se le vuelve a pedir nada por `_PAUSA_S`;
# - no más de `_LOGINS_POR_HORA` logins por hora, entre todos.

_PAUSA_S = 45 * 60
_LOGINS_POR_HORA = 4
_pausa_hasta = 0.0
_logins: list = []


def _pausar() -> None:
    global _pausa_hasta
    _pausa_hasta = time.monotonic() + _PAUSA_S


def _revisar_pausa() -> None:
    falta = _pausa_hasta - time.monotonic()
    if falta > 0:
        minutos = max(1, round(falta / 60))
        raise AnacNoContesta(
            f"ANAC no está aceptando conexiones de Vector. Volvemos a probar en {minutos} min; mientras tanto podés usar el marcador."
        )


def _anotar_login() -> None:
    ahora = time.monotonic()
    _logins[:] = [t for t in _logins if ahora - t < 3600]
    if len(_logins) >= _LOGINS_POR_HORA:
        raise AnacNoContesta("Vector ya entró varias veces a ANAC en la última hora. Probá en un rato o usá el marcador.")
    _logins.append(ahora)


class CadError(Exception):
    """Algo salió mal hablando con ANAC. `codigo`: 'rechazada', 'anac' o 'apagado'."""

    codigo = "anac"


class ClaveRechazada(CadError):
    codigo = "rechazada"


class AnacNoContesta(CadError):
    codigo = "anac"


class ModoApagado(CadError):
    codigo = "apagado"


# ---------------------------------------------------------------- el cifrado ---


def _fernet() -> Optional[Fernet]:
    clave = (settings.cad_clave_cifrado or "").strip()
    if not clave:
        return None
    try:
        return Fernet(clave.encode())
    except (ValueError, TypeError):
        return None


def disponible() -> bool:
    return bool(settings.cad_desde_vector) and _fernet() is not None


def _exigir_prendido() -> None:
    if not settings.cad_desde_vector:
        raise ModoApagado("Pasar al CAD desde Vector está pausado. Usá el marcador.")


def cifrar(texto: str) -> str:
    f = _fernet()
    if not f:
        raise ModoApagado("Falta CAD_CLAVE_CIFRADO.")
    return f.encrypt(texto.encode()).decode()


def descifrar(texto: str) -> str:
    f = _fernet()
    if not f:
        raise ModoApagado("Falta CAD_CLAVE_CIFRADO.")
    try:
        return f.decrypt(texto.encode()).decode()
    except InvalidToken as exc:
        raise ModoApagado("La clave de cifrado cambió: hay que volver a conectar.") from exc


# ----------------------------------------------------------------- el login ---

_TOKEN_RE = re.compile(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"')
_RETURN_RE = re.compile(r'id="ReturnUrl"[^>]*value="([^"]*)"')


def leer_formulario(pagina: str) -> Optional[Dict[str, str]]:
    """El token y el ReturnUrl del formulario de login, o `None` si la página no lo tiene."""
    token = _TOKEN_RE.search(pagina)
    ret = _RETURN_RE.search(pagina)
    if not token or ret is None or 'name="Password"' not in pagina:
        return None
    return {"token": html.unescape(token.group(1)), "return_url": html.unescape(ret.group(1))}


def motivo_del_rechazo(pagina: str) -> str:
    """El cartel de error del login (IdentityServer lo pone en una lista o un alerta)."""
    for patron in (r'validation-summary-errors[^>]*>(.*?)</div>', r'class="alert alert-danger"[^>]*>(.*?)</div>', r'text-danger[^>]*>(.*?)</'):
        m = re.search(patron, pagina, re.S | re.I)
        if m:
            texto = re.sub(r"<[^>]+>", " ", m.group(1))
            texto = re.sub(r"\s+", " ", html.unescape(texto)).strip()
            if texto:
                return texto[:300]
    return "ANAC no aceptó el usuario o la contraseña."


def token_de_la_redireccion(url: str) -> Optional[str]:
    """`https://cad.anac.gob.ar/portalApp/#access_token=…&…` → el token, o `None`."""
    if not url.startswith(REDIRECCION):
        return None
    datos = parse_qs(urlparse(url).fragment)
    return (datos.get("access_token") or [None])[0]


async def _seguir(cliente: httpx.AsyncClient, respuesta: httpx.Response, saltos: int = 8) -> Tuple[httpx.Response, Optional[str]]:
    """
    Sigue las redirecciones a mano hasta una página, o hasta la vuelta al portal con el
    token en el fragmento (que no hay que pedir: es el navegador el que lo leería).
    """
    for _ in range(saltos):
        if respuesta.status_code not in (301, 302, 303, 307, 308):
            return respuesta, None
        destino = urljoin(str(respuesta.url), respuesta.headers.get("location", ""))
        token = token_de_la_redireccion(destino)
        if token or destino.startswith(REDIRECCION):
            return respuesta, token
        sitio = "same-origin" if urlparse(destino).netloc == respuesta.url.host else "same-site"
        respuesta = await cliente.get(destino, headers=_navegar(sitio, str(respuesta.request.headers.get("Referer") or "") or None))
    raise AnacNoContesta("El login de ANAC dio demasiadas vueltas.")


async def iniciar_sesion(usuario: str, clave: str, transporte: Optional[httpx.AsyncBaseTransport] = None) -> httpx.AsyncClient:
    """
    Entra al CAD con la cuenta del piloto y devuelve un cliente con la cookie del CAD.
    `ClaveRechazada` si ANAC devolvió el formulario (no se reintenta); `AnacNoContesta` si
    algo no tiene la forma esperada.
    """
    if transporte is None:
        _exigir_prendido()
        _revisar_pausa()
        _anotar_login()
    cliente = _cliente(transporte)
    try:
        params = {
            "client_id": "portalAplicaciones",
            "redirect_uri": REDIRECCION,
            "response_type": "id_token token",
            "scope": "openid profile legacyCookie",
            "state": secrets.token_urlsafe(16),
            "nonce": secrets.token_urlsafe(16),
        }
        # Como quien toca "Ingresar" en el portal del CAD.
        r, _ = await _seguir(cliente, await cliente.get(f"{LOGIN}/connect/authorize", params=params, headers=_navegar("same-site", REDIRECCION)))
        form = leer_formulario(r.text) if r.status_code == 200 else None
        if not form:
            raise AnacNoContesta("No encontramos el formulario de login de ANAC.")
        pagina_login = str(r.url)
        r = await cliente.post(
            pagina_login,
            headers=_navegar("same-origin", pagina_login, Origin=LOGIN, **{"Cache-Control": "max-age=0"}),
            data={
                "ReturnUrl": form["return_url"],
                "Time": str(int(time.time() * 1000)),
                "Username": usuario,
                "Password": clave,
                "button": "login",
                "__RequestVerificationToken": form["token"],
            },
        )
        if r.status_code == 200:
            # Volvió el formulario: usuario o contraseña mal, o la cuenta bloqueada.
            if leer_formulario(r.text):
                raise ClaveRechazada(motivo_del_rechazo(r.text))
            raise AnacNoContesta("ANAC contestó algo que no esperábamos al iniciar sesión.")
        r, token = await _seguir(cliente, r)
        if not token:
            raise AnacNoContesta("ANAC no devolvió la sesión del CAD.")
        r = await cliente.get(COOKIE_DEL_CAD, headers=_api(REDIRECCION, Authorization=f"Bearer {token}"))
        if r.status_code >= 400:
            raise AnacNoContesta(f"El CAD no abrió la sesión ({r.status_code}).")
        # Sin pedido de prueba: el primero de verdad dice si la sesión anda (y `pedir` entra de
        # nuevo una vez si no). Es un pedido menos por login.
        return cliente
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError, httpx.ProxyError) as exc:
        await cliente.aclose()
        if transporte is None:
            _pausar()
        raise AnacNoContesta("ANAC no está aceptando conexiones del servidor de Vector. No se guardó nada: probá en un rato o usá el marcador.") from exc
    except httpx.HTTPError as exc:
        await cliente.aclose()
        raise AnacNoContesta("ANAC no contesta. Probá en un rato.") from exc
    except CadError:
        await cliente.aclose()
        raise


_PAGINA_DE_VUELOS = {
    "descripcion": "",
    "tipoTrip": "TM",
    "sortField": "fechaSalida",
    "sortDirection": "DESC",
    "rowsPerPage": "1000",
    "pageNumber": "1",
    "mostrarIngresados": "true",
    "solicitudFoliadoId": "null",
}

# ---------------------------------------------------------- las sesiones ---

def _cliente(transporte: Optional[httpx.AsyncBaseTransport] = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        # 10 s para conectar: si ANAC no acepta la conexión, se avisa enseguida en vez de
        # esperar lo que el frontend ya no espera.
        timeout=httpx.Timeout(25, connect=10),
        follow_redirects=False,
        headers=_CHROME,
        transport=transporte,
        # El TLS va de punta a punta: el proxy sólo ve a qué host se conecta.
        proxy=None if transporte is not None else (settings.cad_proxy or None),
    )


# Las sesiones y las listas se guardan también en disco, para que un deploy (que reinicia el
# backend) no obligue a entrar de nuevo a ANAC. Las cookies van cifradas con la misma clave
# que las contraseñas. `CAD_CACHE_DIR` lo cambia (vacío: sólo en memoria).
_DIR = os.environ.get("CAD_CACHE_DIR", str(Path.home() / ".cache" / "vector-cad"))

_sesiones: Dict[str, Tuple[httpx.AsyncClient, float]] = {}
_candados: Dict[str, asyncio.Lock] = {}
_listas: Dict[str, Tuple[Any, float]] = {}
_detalles: Dict[str, Any] = {}


def _archivo(nombre: str) -> Optional[Path]:
    if not _DIR:
        return None
    d = Path(_DIR)
    try:
        d.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        return None
    return d / nombre


def _leer_disco(nombre: str) -> Dict[str, Any]:
    f = _archivo(nombre)
    try:
        return json.loads(f.read_text()) if f and f.exists() else {}
    except (OSError, ValueError):
        return {}


def _escribir_disco(nombre: str, datos: Dict[str, Any]) -> None:
    f = _archivo(nombre)
    if not f:
        return
    try:
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(datos))
        os.chmod(tmp, 0o600)
        tmp.replace(f)
    except OSError:
        pass


def _cookies_de(cliente: httpx.AsyncClient) -> list:
    return [{"n": c.name, "v": c.value, "d": c.domain, "p": c.path} for c in cliente.cookies.jar]


def _persistir_sesion(user_id: str, cliente: Optional[httpx.AsyncClient], desde: float = 0.0) -> None:
    if not disponible():
        return
    todas = _leer_disco("sesiones.json")
    if cliente is None:
        todas.pop(user_id, None)
    else:
        todas[user_id] = {"t": desde, "c": cifrar(json.dumps(_cookies_de(cliente)))}
    _escribir_disco("sesiones.json", todas)


def _sesion_del_disco(user_id: str) -> Optional[Tuple[httpx.AsyncClient, float]]:
    """La sesión guardada antes de un reinicio, si no venció. `t` es hora de reloj."""
    guardada = _leer_disco("sesiones.json").get(user_id)
    if not guardada or time.time() - float(guardada.get("t") or 0) >= _TTL_SESION:
        return None
    try:
        cookies = json.loads(descifrar(guardada["c"]))
    except (CadError, ValueError, KeyError):
        return None
    cliente = _cliente()
    for c in cookies:
        cliente.cookies.set(c["n"], c["v"], domain=c["d"], path=c["p"])
    # En `_sesiones` el tiempo es monotónico: se traduce lo que ya pasó.
    return cliente, time.monotonic() - (time.time() - float(guardada["t"]))


def _cargar_listas() -> None:
    ahora_m, ahora = time.monotonic(), time.time()
    for clave, (datos, t) in _leer_disco("listas.json").items():
        if ahora - t < _TTL_LISTAS:
            _listas[clave] = (datos, ahora_m - (ahora - t))


def _guardar_listas() -> None:
    ahora_m, ahora = time.monotonic(), time.time()
    _escribir_disco("listas.json", {k: (d, ahora - (ahora_m - t)) for k, (d, t) in _listas.items()})


_cargar_listas()


def _candado(user_id: str) -> asyncio.Lock:
    return _candados.setdefault(user_id, asyncio.Lock())


async def olvidar_sesion(user_id: str) -> None:
    viejo = _sesiones.pop(user_id, None)
    if viejo:
        await viejo[0].aclose()
    _persistir_sesion(user_id, None)


async def guardar_sesion(user_id: str, cliente: httpx.AsyncClient) -> None:
    await olvidar_sesion(user_id)
    _sesiones[user_id] = (cliente, time.monotonic())
    _persistir_sesion(user_id, cliente, time.time())


async def sesion(user_id: str, credenciales) -> httpx.AsyncClient:
    """
    La sesión abierta de ese piloto, o una nueva. `credenciales` es una función que devuelve
    (usuario, clave) o lanza `CadError`: se llama sólo si hace falta entrar.
    """
    async with _candado(user_id):
        abierta = _sesiones.get(user_id) or _sesion_del_disco(user_id)
        if abierta and time.monotonic() - abierta[1] < _TTL_SESION:
            _sesiones[user_id] = abierta
            return abierta[0]
        usuario, clave = await credenciales()
        cliente = await iniciar_sesion(usuario, clave)
        await guardar_sesion(user_id, cliente)
        return cliente


async def pedir(user_id: str, credenciales, ruta: str, params: Optional[Dict[str, str]] = None) -> Any:
    """Un GET de la lista blanca, con la sesión del piloto. Si venció, se entra de nuevo una vez."""
    if ruta not in RUTAS_GET:
        raise ValueError(f"Ruta del CAD no permitida: {ruta}")
    clave_lista = f"{ruta}?{sorted((params or {}).items())}"
    if ruta in _LISTAS_PUBLICAS:
        guardada = _listas.get(clave_lista)
        if guardada and time.monotonic() - guardada[1] < _TTL_LISTAS:
            return guardada[0]
    # El detalle de un vuelo ("Traer a Vector" lee uno por vuelo) no cambia: se lee una vez.
    clave_detalle = f"{user_id}:{clave_lista}"
    if ruta == "Get" and clave_detalle in _detalles:
        return _detalles[clave_detalle]
    _exigir_prendido()
    _revisar_pausa()
    for intento in range(2):
        cliente = await sesion(user_id, credenciales)
        try:
            r = await cliente.get(API + ruta, params=params or {}, headers=_api())
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError, httpx.ProxyError) as exc:
            _pausar()
            raise AnacNoContesta("El CAD no contesta. Probá en un rato.") from exc
        except httpx.HTTPError as exc:
            raise AnacNoContesta("El CAD no contesta. Probá en un rato.") from exc
        if r.status_code in (401, 403) or (r.status_code == 302 and intento == 0):
            await olvidar_sesion(user_id)
            continue
        if r.status_code != 200:
            raise AnacNoContesta(f"El CAD contestó {r.status_code}.")
        try:
            datos = r.json()
        except ValueError as exc:
            # Sin sesión, el CAD a veces contesta la página de login con 200.
            if intento == 0:
                await olvidar_sesion(user_id)
                continue
            raise AnacNoContesta("El CAD no devolvió datos.") from exc
        if ruta in _LISTAS_PUBLICAS:
            _listas[clave_lista] = (datos, time.monotonic())
            _guardar_listas()
        if ruta == "Get":
            if len(_detalles) > 5000:
                _detalles.clear()
            _detalles[clave_detalle] = datos
        return datos
    raise AnacNoContesta("El CAD cerró la sesión.")


_vuelos: Dict[str, Tuple[list, float]] = {}


async def vuelos(user_id: str, credenciales, fresca: bool = False) -> list:
    """Los vuelos del piloto en el CAD. `fresca` (sincronizar, "Actualizar") no usa la guardada."""
    guardada = _vuelos.get(user_id)
    if guardada and not fresca and time.monotonic() - guardada[1] < _TTL_VUELOS:
        return guardada[0]
    datos = await pedir(user_id, credenciales, "GetPagedList", _PAGINA_DE_VUELOS)
    lista = (datos or {}).get("dataSource") or [] if isinstance(datos, dict) else []
    _vuelos[user_id] = (lista, time.monotonic())
    return lista


def olvidar_vuelos(user_id: str) -> None:
    _vuelos.pop(user_id, None)


# ------------------------------------------------------------------ crear ---

_CLAVES_VUELO = {
    "Discriminaciones", "discriminaciones", "tipoVueloID", "fechaHoraSalida", "fechaHoraLlegada", "aterrizajes",
    "autoridadCertificanteID", "observaciones", "finalidadID", "potencia", "clase", "horasDia", "horasNoche",
    "cargoID", "origenID", "destinoID", "origenPersonalizado", "destinoPersonalizado", "matriculaAvion", "simulador",
}
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?Z?$")


def validar_vuelo(datos: Any) -> Dict[str, Any]:
    """Lo que se le manda a "Crear", revisado: la forma del formulario del CAD y nada más."""
    if not isinstance(datos, dict):
        raise ValueError("El vuelo no tiene la forma esperada.")
    extra = set(datos) - _CLAVES_VUELO
    if extra:
        raise ValueError(f"Campos que el CAD no pide: {', '.join(sorted(extra))}")
    if str(datos.get("tipoVueloID")) not in {"1", "2", "3"}:
        raise ValueError("Tipo de vuelo inválido.")
    for k in ("fechaHoraSalida", "fechaHoraLlegada"):
        if not isinstance(datos.get(k), str) or not _ISO.match(datos[k]):
            raise ValueError(f"{k} inválida.")
    if not str(datos.get("autoridadCertificanteID") or "").isdigit() or not str(datos.get("observaciones") or "").strip():
        raise ValueError("Falta la autoridad certificante.")
    if not str(datos.get("finalidadID") or "").isdigit():
        raise ValueError("Falta la finalidad.")
    discs = datos.get("Discriminaciones") or []
    if not isinstance(discs, list) or len(discs) > 12:
        raise ValueError("Discriminaciones inválidas.")
    if str(datos["tipoVueloID"]) == "3":
        s = datos.get("simulador")
        if not isinstance(s, dict) or not str(s.get("simuladorID") or "").isdigit() or not s.get("nombre"):
            raise ValueError("Falta el simulador.")
    elif not datos.get("origenID") or not datos.get("destinoID") or not datos.get("matriculaAvion"):
        raise ValueError("Faltan los aeródromos o la matrícula.")
    return datos


async def crear_vuelo(user_id: str, credenciales, datos: Dict[str, Any]) -> Dict[str, Any]:
    """
    "Crear" del CAD. El vuelo queda "Pendiente de DDJJ". No se reintenta un vuelo que el CAD
    rechazó (podría haberlo creado igual); sólo se entra de nuevo si la sesión había vencido.
    """
    vuelo = validar_vuelo(datos)
    _exigir_prendido()
    _revisar_pausa()
    olvidar_vuelos(user_id)
    for intento in range(2):
        cliente = await sesion(user_id, credenciales)
        try:
            r = await cliente.post(API + "Create", json=vuelo, headers=_api(**{"Origin": CAD, "Content-Type": "application/json"}))
        except httpx.HTTPError as exc:
            raise AnacNoContesta("El CAD no contestó: fijate en el CAD si el vuelo quedó antes de mandarlo de nuevo.") from exc
        if r.status_code in (401, 403) and intento == 0:
            await olvidar_sesion(user_id)
            continue
        if 200 <= r.status_code < 300:
            return {"ok": True, "mensaje": "Cargado en el CAD"}
        try:
            cuerpo = r.json()
        except ValueError:
            cuerpo = {}
        texto = (cuerpo.get("message") or cuerpo.get("exceptionMessage") or cuerpo.get("Message") or "") if isinstance(cuerpo, dict) else ""
        return {"ok": False, "mensaje": f"El CAD no lo aceptó: {texto or f'error {r.status_code}'}"}
    raise AnacNoContesta("El CAD cerró la sesión.")


# ------------------------------------------------------------ sincronizar ---

#: Cada cuánto, como mucho, se sincroniza solo un piloto: cada vez es entrar a ANAC.
INTERVALO_SINCRONIZACION_H = 24
#: `GetPagedList` trae hasta 1000: con la lista llena puede estar cortada.
TOPE_LISTA = 1000


def matricula_cad(m: Optional[str]) -> str:
    """"LVS114" → "LV-S114", como la escribe ANAC (igual que `matriculaCad` del frontend)."""
    s = re.sub(r"\s+", "", (m or "").upper())
    if s.startswith("LV-") or not re.match(r"^LV[A-Z0-9]", s):
        return s
    return f"LV-{s[2:]}"


def _al_minuto(v: Any) -> str:
    """Una fecha de Vector (con zona) o del CAD (UTC sin zona) → "AAAA-MM-DDTHH:MM" en UTC."""
    from datetime import datetime, timezone

    texto = str(v or "")
    if not texto:
        return ""
    try:
        d = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if d.tzinfo:
        d = d.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M")


def conciliar(vuelos: list, cad: list, ahora: str) -> list:
    """
    Lo que hay que cambiar en Vector para que diga lo mismo que el CAD. `vuelos`: dicts con
    `id`, `takeoff`, `matricula`, `es_simulador`, `cad_vuelo_id`, `cad_estado`, `cad_omitido`.
    `cad`: la lista de `GetPagedList`. Devuelve `[(flight_id, cambios)]`.

    - Un vuelo marcado cuyo id sigue en el CAD: se le actualiza el estado ("PENDIENTE DE DDJJ"…).
    - Uno marcado que ya no está: se desmarca, **sólo con la lista entera** (ni vacía, que puede
      ser una lectura fallida, ni llena hasta el tope, que puede estar cortada).
    - Uno sin marcar (y no omitido) que coincide con uno del CAD sin dueño, misma salida al
      minuto y misma matrícula (un simulador no tiene matrícula en el CAD): se marca. Sólo si la
      coincidencia es única: marcar el vuelo equivocado lo sacaría de "Pasar al CAD".
    """
    completa = 0 < len(cad) < TOPE_LISTA
    por_id = {}
    for c in cad:
        try:
            por_id[int(c.get("vueloTripulanteID"))] = c
        except (TypeError, ValueError):
            continue
    ligados = {int(f["cad_vuelo_id"]) for f in vuelos if f.get("cad_vuelo_id")}
    libres: Dict[Tuple[str, str], list] = {}
    for cid, c in por_id.items():
        if cid not in ligados:
            libres.setdefault((_al_minuto(c.get("fechaSalida")), matricula_cad(c.get("matricula"))), []).append(cid)

    estado_de = lambda c: (str(c.get("estadoDesc") or "").strip()[:60] or None)  # noqa: E731
    cambios = []
    for f in vuelos:
        cid = f.get("cad_vuelo_id")
        if cid:
            c = por_id.get(int(cid))
            if c is not None:
                if estado_de(c) != f.get("cad_estado"):
                    cambios.append((f["id"], {"cad_estado": estado_de(c)}))
            elif completa:
                cambios.append((f["id"], {"cad_vuelo_id": None, "cad_cargado_at": None, "cad_estado": None}))
        elif not f.get("cad_omitido"):
            clave = (_al_minuto(f.get("takeoff")), "" if f.get("es_simulador") else matricula_cad(f.get("matricula")))
            candidatos = libres.get(clave) or []
            if clave[0] and len(candidatos) == 1:
                nuevo = candidatos.pop()
                cambios.append((f["id"], {"cad_vuelo_id": nuevo, "cad_cargado_at": ahora, "cad_estado": estado_de(por_id[nuevo])}))
    return cambios
