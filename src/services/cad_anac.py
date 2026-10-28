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
import re
import secrets
import time
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
_UA = "Mozilla/5.0 (Vector; +https://vector.fdiaznem.com.ar)"

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
_TTL_LISTAS = 6 * 3600
#: Cuánto se reusa una sesión abierta antes de abrir otra.
_TTL_SESION = 20 * 60


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
    return _fernet() is not None


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
        respuesta = await cliente.get(destino)
    raise AnacNoContesta("El login de ANAC dio demasiadas vueltas.")


async def iniciar_sesion(usuario: str, clave: str, transporte: Optional[httpx.AsyncBaseTransport] = None) -> httpx.AsyncClient:
    """
    Entra al CAD con la cuenta del piloto y devuelve un cliente con la cookie del CAD.
    `ClaveRechazada` si ANAC devolvió el formulario (no se reintenta); `AnacNoContesta` si
    algo no tiene la forma esperada.
    """
    cliente = httpx.AsyncClient(
        # 10 s para conectar: si ANAC no acepta la conexión, se avisa enseguida en vez de
        # esperar lo que el frontend ya no espera.
        timeout=httpx.Timeout(25, connect=10),
        follow_redirects=False,
        headers={"User-Agent": _UA, "Accept-Language": "es-AR,es;q=0.9"},
        transport=transporte,
        # El TLS va de punta a punta: el proxy sólo ve a qué host se conecta.
        proxy=None if transporte is not None else (settings.cad_proxy or None),
    )
    try:
        params = {
            "client_id": "portalAplicaciones",
            "redirect_uri": REDIRECCION,
            "response_type": "id_token token",
            "scope": "openid profile legacyCookie",
            "state": secrets.token_urlsafe(16),
            "nonce": secrets.token_urlsafe(16),
        }
        r, _ = await _seguir(cliente, await cliente.get(f"{LOGIN}/connect/authorize", params=params))
        form = leer_formulario(r.text) if r.status_code == 200 else None
        if not form:
            raise AnacNoContesta("No encontramos el formulario de login de ANAC.")
        r = await cliente.post(
            str(r.url),
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
        r = await cliente.get(COOKIE_DEL_CAD, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        if r.status_code >= 400:
            raise AnacNoContesta(f"El CAD no abrió la sesión ({r.status_code}).")
        # La prueba: una página de vuelos.
        r = await cliente.get(API + "GetPagedList", params=_PAGINA_DE_VUELOS | {"rowsPerPage": "1"}, headers={"Accept": "application/json"})
        if r.status_code != 200 or "dataSource" not in r.text:
            raise AnacNoContesta(f"El CAD no abrió la sesión ({r.status_code}).")
        return cliente
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        await cliente.aclose()
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

_sesiones: Dict[str, Tuple[httpx.AsyncClient, float]] = {}
_candados: Dict[str, asyncio.Lock] = {}
_listas: Dict[str, Tuple[Any, float]] = {}


def _candado(user_id: str) -> asyncio.Lock:
    return _candados.setdefault(user_id, asyncio.Lock())


async def olvidar_sesion(user_id: str) -> None:
    viejo = _sesiones.pop(user_id, None)
    if viejo:
        await viejo[0].aclose()


async def guardar_sesion(user_id: str, cliente: httpx.AsyncClient) -> None:
    await olvidar_sesion(user_id)
    _sesiones[user_id] = (cliente, time.monotonic())


async def sesion(user_id: str, credenciales) -> httpx.AsyncClient:
    """
    La sesión abierta de ese piloto, o una nueva. `credenciales` es una función que devuelve
    (usuario, clave) o lanza `CadError`: se llama sólo si hace falta entrar.
    """
    async with _candado(user_id):
        abierta = _sesiones.get(user_id)
        if abierta and time.monotonic() - abierta[1] < _TTL_SESION:
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
    for intento in range(2):
        cliente = await sesion(user_id, credenciales)
        try:
            r = await cliente.get(API + ruta, params=params or {}, headers={"Accept": "application/json"})
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
        return datos
    raise AnacNoContesta("El CAD cerró la sesión.")


async def vuelos(user_id: str, credenciales) -> list:
    datos = await pedir(user_id, credenciales, "GetPagedList", _PAGINA_DE_VUELOS)
    return (datos or {}).get("dataSource") or [] if isinstance(datos, dict) else []


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
    for intento in range(2):
        cliente = await sesion(user_id, credenciales)
        try:
            r = await cliente.post(API + "Create", json=vuelo, headers={"Accept": "application/json"})
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
