"""
Pasar al CAD desde Vector: el login de ANAC, el cifrado y lo que se le manda a "Crear".

Offline: ANAC es un servidor falso (`httpx.MockTransport`) con las mismas páginas y
redirecciones que el real (leídas el 2026-10-28). `python test_cad_anac.py`; sale con código 1
si algo falla.
"""

import asyncio
import os
import sys
import tempfile
from urllib.parse import parse_qs

import httpx
from cryptography.fernet import Fernet

os.environ["CAD_CACHE_DIR"] = tempfile.mkdtemp()

from src.config import settings
from src.services import cad_anac

resultados = []


def check(label, condition):
    print(f"{'✅' if condition else '❌'} {label}")
    resultados.append(bool(condition))


FORMULARIO = """<html><form action="" method="post">
<input type="hidden" id="ReturnUrl" name="ReturnUrl" value="/connect/authorize/callback?client_id=portalAplicaciones&amp;x=1" />
<input type="hidden" id="time" name="Time" value="" />
<input id="Username" name="Username" value=""><input type="password" id="Password" name="Password">
<button id="loginButton" name="button" value="login">Iniciar sesión</button>
<input name="__RequestVerificationToken" type="hidden" value="tok-123" /></form>{error}</html>"""
ERROR = '<div class="alert alert-danger"><div class="validation-summary-errors"><ul><li>Usuario o contraseña inválidos</li></ul></div></div>'


def anac_falso(clave_buena: str, pedidos: list):
    def responder(req: httpx.Request) -> httpx.Response:
        pedidos.append((req.method, req.url.host, req.url.path))
        if req.url.path == "/connect/authorize":
            return httpx.Response(302, headers={"location": "https://login.anac.gob.ar/account/login?returnUrl=%2Fconnect%2Fauthorize%2Fcallback"})
        if req.url.path == "/account/login" and req.method == "GET":
            return httpx.Response(200, text=FORMULARIO.format(error=""))
        if req.url.path == "/account/login" and req.method == "POST":
            datos = parse_qs(req.content.decode())
            ok = (
                datos.get("Password") == [clave_buena]
                and datos.get("__RequestVerificationToken") == ["tok-123"]
                and datos.get("button") == ["login"]
                and datos.get("ReturnUrl", [""])[0].startswith("/connect/authorize/callback")
                and datos.get("Time", [""])[0].isdigit()
            )
            if not ok:
                return httpx.Response(200, text=FORMULARIO.format(error=ERROR))
            return httpx.Response(302, headers={"location": "/connect/authorize/callback?client_id=portalAplicaciones", "set-cookie": "idsrv=abc; path=/"})
        if req.url.path == "/connect/authorize/callback":
            return httpx.Response(302, headers={"location": "https://cad.anac.gob.ar/portalApp/#id_token=x&access_token=AT-9&token_type=Bearer"})
        if req.url.path == "/PortalAplicaciones/api/CAD/cookiePorUsuario":
            if req.headers.get("authorization") != "Bearer AT-9":
                return httpx.Response(401)
            return httpx.Response(200, json=True, headers={"set-cookie": "CAD=sesion; path=/; domain=cad.anac.gob.ar"})
        if req.url.path.startswith("/foliadoweb/api/VueloTripulante/"):
            if "CAD=sesion" not in req.headers.get("cookie", ""):
                return httpx.Response(401)
            if req.url.path.endswith("/GetPagedList"):
                return httpx.Response(200, json={"dataSource": [{"vueloTripulanteID": 1}]})
            if req.url.path.endswith("/Create"):
                return httpx.Response(200, json={})
        return httpx.Response(404)

    return httpx.MockTransport(responder)


async def main():
    # --- el login, completo ---
    pedidos = []
    cliente = await cad_anac.iniciar_sesion("piloto", "buena", transporte=anac_falso("buena", pedidos))
    r = await cliente.get(cad_anac.API + "GetPagedList")
    check("entra y queda con la cookie del CAD", r.status_code == 200 and r.json()["dataSource"][0]["vueloTripulanteID"] == 1)
    check("no pide la página del portal con el token (lo leería el navegador)", ("GET", "cad.anac.gob.ar", "/portalApp/") not in pedidos)
    check("un solo POST de login", sum(1 for p in pedidos if p[0] == "POST") == 1)
    await cliente.aclose()

    # --- la contraseña mal: rechazada, con el cartel de ANAC, y un solo intento ---
    pedidos = []
    try:
        await cad_anac.iniciar_sesion("piloto", "mala", transporte=anac_falso("buena", pedidos))
        check("una contraseña mal no entra", False)
    except cad_anac.ClaveRechazada as exc:
        check("una contraseña mal es ClaveRechazada", True)
        check("con el cartel de ANAC", "inválidos" in str(exc))
    check("y no se reintenta", sum(1 for p in pedidos if p[0] == "POST") == 1)

    # --- ANAC cambió el formulario: no es una contraseña mal ---
    def sin_formulario(req):
        if req.url.path == "/connect/authorize":
            return httpx.Response(200, text="<html>mantenimiento</html>")
        return httpx.Response(404)

    try:
        await cad_anac.iniciar_sesion("p", "c", transporte=httpx.MockTransport(sin_formulario))
        check("sin formulario no entra", False)
    except cad_anac.AnacNoContesta:
        check("sin formulario es AnacNoContesta, no ClaveRechazada", True)


asyncio.run(main())

# --- piezas ---
check("lee el token y el ReturnUrl del formulario", cad_anac.leer_formulario(FORMULARIO.format(error="")) == {
    "token": "tok-123",
    "return_url": "/connect/authorize/callback?client_id=portalAplicaciones&x=1",
})
check("una página sin contraseña no es el formulario", cad_anac.leer_formulario("<input name='x'>") is None)
check("el token del fragmento", cad_anac.token_de_la_redireccion("https://cad.anac.gob.ar/portalApp/#access_token=A1&x=2") == "A1")
check("otra redirección no trae token", cad_anac.token_de_la_redireccion("https://otro/#access_token=A1") is None)

# --- el cifrado ---
settings.cad_clave_cifrado = None
check("sin clave, el modo está apagado", not cad_anac.disponible())
settings.cad_clave_cifrado = Fernet.generate_key().decode()
cifrada = cad_anac.cifrar("mi clave")
check("cifra y descifra", cad_anac.descifrar(cifrada) == "mi clave" and "mi clave" not in cifrada)
settings.cad_clave_cifrado = Fernet.generate_key().decode()
try:
    cad_anac.descifrar(cifrada)
    check("con otra clave no descifra", False)
except cad_anac.ModoApagado:
    check("con otra clave no descifra", True)

# --- lo que se manda a Crear ---
VUELO = {
    "Discriminaciones": [], "discriminaciones": [], "tipoVueloID": "2",
    "fechaHoraSalida": "2026-10-17T18:00:00.000Z", "fechaHoraLlegada": "2026-10-17T19:00:00.000Z",
    "aterrizajes": 1, "autoridadCertificanteID": "1", "observaciones": "LJN-SADM", "finalidadID": "63",
    "potencia": 100, "clase": "MONT-T", "horasDia": 1, "horasNoche": 0, "cargoID": "1",
    "origenID": "2013", "destinoID": "MOR", "origenPersonalizado": "", "destinoPersonalizado": "", "matriculaAvion": "LV-S100",
}
check("un vuelo desde un LAD pasa", cad_anac.validar_vuelo(dict(VUELO)) is not None)
SIM = {k: v for k, v in VUELO.items() if k not in ("origenID", "destinoID", "origenPersonalizado", "destinoPersonalizado", "matriculaAvion")}
SIM.update({"tipoVueloID": "3", "simulador": {"simuladorID": "34", "nombre": "SANTIAGO I C-172 -- ASG TRAINING CENTER", "modeloID": "40", "modelo": "A320"}})
check("un simulador pasa", cad_anac.validar_vuelo(SIM) is not None)


def rechaza(datos, motivo):
    try:
        cad_anac.validar_vuelo(datos)
        check(motivo, False)
    except ValueError:
        check(motivo, True)


rechaza({**VUELO, "ddjj": True}, "rechaza un campo que el formulario no manda")
rechaza({**VUELO, "tipoVueloID": "4"}, "rechaza un planeador")
rechaza({**VUELO, "observaciones": " "}, "rechaza sin el nombre de la autoridad")
rechaza({**SIM, "simulador": {"simuladorID": "", "nombre": ""}}, "rechaza un simulador sin elegir")
rechaza({**VUELO, "fechaHoraSalida": "17/10/2026"}, "rechaza una fecha mal escrita")
check("la lista blanca no tiene nada de la DDJJ", not any("ddjj" in r.lower() or "declar" in r.lower() for r in cad_anac.RUTAS_GET))

# --- sincronizar: Vector de acuerdo con el CAD ---
CAD_LISTA = [
    {"vueloTripulanteID": 843265, "fechaSalida": "2026-10-17T18:00:00", "matricula": "LV-S100", "estadoDesc": "PENDIENTE DE DDJJ"},
    {"vueloTripulanteID": 661363, "fechaSalida": "2026-08-22T11:00:00", "matricula": None, "estadoDesc": "DECLARADO"},
    {"vueloTripulanteID": 900001, "fechaSalida": "2026-10-20T13:00:00", "matricula": "LV-S114", "estadoDesc": "PENDIENTE DE DDJJ"},
]
VUELOS = [
    # marcado, sigue en el CAD: se le pone el estado
    {"id": "a", "takeoff": "2026-10-17T18:00:00+00:00", "matricula": "LVS100", "es_simulador": False, "cad_vuelo_id": 843265, "cad_estado": None},
    # marcado, ya no está en el CAD: se desmarca
    {"id": "b", "takeoff": "2026-10-17T15:55:00+00:00", "matricula": "LVS100", "es_simulador": False, "cad_vuelo_id": 831534, "cad_estado": "PENDIENTE DE DDJJ"},
    # sin marcar, cargado a mano en el CAD (sin guion en Vector): se marca
    {"id": "c", "takeoff": "2026-10-20T13:00:00+00:00", "matricula": "LVS114", "es_simulador": False, "cad_vuelo_id": None},
    # simulador sin marcar: en el CAD no tiene matrícula
    {"id": "d", "takeoff": "2026-08-22T11:00:00Z", "matricula": "LV-ASG", "es_simulador": True, "cad_vuelo_id": None},
    # omitido: no se toca
    {"id": "e", "takeoff": "2026-10-20T13:00:00+00:00", "matricula": "LVS114", "es_simulador": False, "cad_vuelo_id": None, "cad_omitido": "ignorado"},
]
cambios = dict(cad_anac.conciliar(VUELOS, CAD_LISTA, "2026-10-28T16:00:00+00:00"))
check("marcado y en el CAD: el estado", cambios.get("a") == {"cad_estado": "PENDIENTE DE DDJJ"})
check("marcado y borrado del CAD: se desmarca", cambios.get("b") == {"cad_vuelo_id": None, "cad_cargado_at": None, "cad_estado": None})
check("cargado a mano en el CAD: se marca con su id y su estado", cambios.get("c", {}).get("cad_vuelo_id") == 900001 and cambios["c"]["cad_estado"] == "PENDIENTE DE DDJJ")
check("un simulador se reconoce sin matrícula", cambios.get("d", {}).get("cad_vuelo_id") == 661363)
check("un omitido no se toca", "e" not in cambios)
check("con la lista vacía no se desmarca nada", cad_anac.conciliar(VUELOS, [], "x") == [])
dos = [dict(VUELOS[2], id="c1"), dict(VUELOS[2], id="c2")]
check("dos vuelos de Vector para uno del CAD: se marca uno solo", sum(1 for _, c in cad_anac.conciliar(dos, CAD_LISTA, "x") if c.get("cad_vuelo_id") == 900001) == 1)
sin_cambios = cad_anac.conciliar([dict(VUELOS[0], cad_estado="PENDIENTE DE DDJJ")], CAD_LISTA, "x")
check("sin cambios, no se escribe nada", sin_cambios == [])

# --- cuidar a ANAC: la pausa y el tope de logins son de todo el servidor ---
cad_anac._pausa_hasta = 0.0
cad_anac._logins.clear()
for _ in range(cad_anac._LOGINS_POR_HORA):
    cad_anac._anotar_login()
try:
    cad_anac._anotar_login()
    check("el tope de logins por hora frena", False)
except cad_anac.AnacNoContesta:
    check("el tope de logins por hora frena", True)
cad_anac._logins.clear()
cad_anac._pausar()
try:
    asyncio.run(cad_anac.pedir("u", None, "GetPagedList"))
    check("en pausa no se le pide nada a ANAC", False)
except cad_anac.AnacNoContesta as exc:
    check("en pausa no se le pide nada a ANAC", "min" in str(exc))
cad_anac._pausa_hasta = 0.0


def sin_conexion(req):
    raise httpx.ConnectTimeout("bloqueado", request=req)


async def _probar_bloqueo():
    # Con un transporte de prueba no se pausa (los tests no se pisan): se simula sin él.
    try:
        await cad_anac.iniciar_sesion("p", "c", transporte=httpx.MockTransport(sin_conexion))
    except cad_anac.AnacNoContesta:
        pass


asyncio.run(_probar_bloqueo())
check("con transporte de prueba no queda en pausa", cad_anac._pausa_hasta == 0.0)

# --- como el navegador del CAD, y la sesión que sobrevive a un reinicio ---
check("el User-Agent no dice Vector", "vector" not in cad_anac._UA.lower())
pedidos = []


async def _sesion_guardada():
    cliente = await cad_anac.iniciar_sesion("piloto", "buena", transporte=anac_falso("buena", pedidos))
    check("el login no hace un pedido de prueba a la API", not any("VueloTripulante" in p[2] for p in pedidos))
    await cad_anac.guardar_sesion("u1", cliente)
    cad_anac._sesiones.clear()  # el reinicio
    vuelta = cad_anac._sesion_del_disco("u1")
    check("la sesión vuelve del disco con su cookie", vuelta is not None and vuelta[0].cookies.get("CAD") == "sesion")
    texto = open(os.path.join(os.environ["CAD_CACHE_DIR"], "sesiones.json")).read()
    check("la cookie en disco va cifrada", "sesion" not in texto)
    await cad_anac.olvidar_sesion("u1")
    check("olvidar la borra del disco", cad_anac._sesion_del_disco("u1") is None)
    await vuelta[0].aclose()
    await cliente.aclose()


asyncio.run(_sesion_guardada())

print(f"\n{sum(resultados)}/{len(resultados)}")
sys.exit(0 if all(resultados) else 1)
