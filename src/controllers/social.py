"""
La red social: el @ de cada piloto, seguir, solicitudes y el perfil público.

Cuatro controladores y no uno porque **los guards de Litestar se acumulan por capa** y
un handler no puede salirse del de su controlador: el perfil público
(`/publico/pilotos/{handle}`) se abre sin sesión, y todo lo demás exige una.

**Dónde se cumple la privacidad.** Las escrituras van con el cliente del piloto, así
que el RLS de la migración 018 las acota aunque este código se equivoque. El perfil
público lee con service role —tiene que contar seguidores y sumar horas de otro—, y
por eso ahí el orden importa: primero se decide con `puede_ver_horas`, después se
consulta, y lo único que sale son los cinco agregados de `estadisticas_publicas`.
Ninguna fila de `flights`, y ningún `user_id`, cruza esta API.
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from litestar import Controller, Request, delete, get, post, put
from litestar.exceptions import HTTPException, NotFoundException
from postgrest.exceptions import APIError
from supabase import Client

from src.auth.guards import auth_guard
from src.auth.security import AuthHandler
from src.config import settings
from src.models.social import (
    EstadoSeguimiento,
    HorasPublicas,
    MiPerfilPublico,
    PerfilPublicoIn,
    PerfilPublicoOut,
    PilotoPublico,
    PilotoResumen,
    ResumenSocial,
)
from src.services.social import (
    COLUMNAS_LIBRO,
    COLUMNAS_VUELO,
    HandleInvalido,
    estadisticas_publicas,
    limpiar_busqueda,
    puede_ver_horas,
    relacion_con,
    url_avatar,
    validar_handle,
)
from src.services.avisos import armar_aviso, enviar_aviso
from src.supabase_client import SupabaseManager, verify_access_token

_COLUMNAS_PERFIL = "user_id, handle, nombre_visible, licencia, bio, visibilidad, avatar_path, created_at"
_HANDLE_OCUPADO = "Ese @ ya lo tiene otro piloto."
_NO_EXISTE = "No existe ese piloto."


# ---------------------------------------------------------------------------
# Ayudas compartidas
# ---------------------------------------------------------------------------

def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _yo(request: Request) -> str:
    return str(request.state.user.id)


def _handle_o_404(crudo: str) -> str:
    """Un @ con formato inválido no puede existir: es un 404, no un 400."""
    try:
        return validar_handle(crudo)
    except HandleInvalido as exc:
        raise NotFoundException(_NO_EXISTE) from exc


def _perfil_por_handle(client: Client, handle: str) -> Optional[Dict[str, Any]]:
    r = client.table("perfiles_publicos").select(_COLUMNAS_PERFIL).eq("handle", handle).limit(1).execute()
    return r.data[0] if r.data else None


def _perfil_de(client: Client, user_id: str) -> Optional[Dict[str, Any]]:
    r = client.table("perfiles_publicos").select(_COLUMNAS_PERFIL).eq("user_id", user_id).limit(1).execute()
    return r.data[0] if r.data else None


def _perfiles_de(client: Client, user_ids: List[str]) -> List[Dict[str, Any]]:
    if not user_ids:
        return []
    r = client.table("perfiles_publicos").select(_COLUMNAS_PERFIL).in_("user_id", user_ids).order("handle").execute()
    return r.data or []


def _mis_estados(client: Client, yo: str, user_ids: List[str]) -> Dict[str, str]:
    """Cómo sigo yo a cada uno de estos pilotos: `{user_id: estado}`."""
    otros = [u for u in user_ids if u != yo]
    if not otros:
        return {}
    r = (
        client.table("seguimientos").select("seguido, estado")
        .eq("seguidor", yo).in_("seguido", otros).execute()
    )
    return {fila["seguido"]: fila["estado"] for fila in (r.data or [])}


def _bloqueos(yo: Optional[str]) -> Tuple[Set[str], Set[str]]:
    """
    A quiénes bloqueé y quiénes me bloquearon (migración 021).

    Con el service role: la segunda lista el RLS no me la deja leer —el bloqueado no puede
    averiguar quién lo bloqueó— y acá se usa sólo para no mostrarme a quien me bloqueó.
    """
    if not yo:
        return set(), set()
    filas = (
        SupabaseManager.get_service_client().table("bloqueos").select("bloqueador, bloqueado")
        .or_(f"bloqueador.eq.{yo},bloqueado.eq.{yo}").execute().data
        or []
    )
    bloquee = {f["bloqueado"] for f in filas if f["bloqueador"] == yo}
    me_bloquearon = {f["bloqueador"] for f in filas if f["bloqueado"] == yo}
    return bloquee, me_bloquearon


def _avatar(fila: Dict[str, Any]) -> Optional[str]:
    return url_avatar(settings.supabase_url, fila.get("avatar_path"))


def _salida(fila: Dict[str, Any]) -> PerfilPublicoOut:
    datos = {k: v for k, v in fila.items() if k not in ("user_id", "avatar_path", "actividad_vista_at")}
    return PerfilPublicoOut(**datos, avatar_url=_avatar(fila))


def _resumenes(client: Client, yo: str, filas: List[Dict[str, Any]]) -> List[PilotoResumen]:
    """
    Una fila por piloto, con mi relación con cada uno. **Quien me bloqueó no aparece**:
    para mí no existe. A quien bloqueé sí, como `bloqueado`, para poder desbloquearlo.
    """
    estados = _mis_estados(client, yo, [f["user_id"] for f in filas])
    bloquee, me_bloquearon = _bloqueos(yo)
    return [
        PilotoResumen(
            handle=f["handle"],
            nombre_visible=f["nombre_visible"],
            licencia=f.get("licencia"),
            visibilidad=f["visibilidad"],
            relacion="bloqueado" if f["user_id"] in bloquee else relacion_con(yo, f["user_id"], estados.get(f["user_id"])),
            avatar_url=_avatar(f),
        )
        for f in filas
        if f["user_id"] not in me_bloquearon
    ]


def _destino(client: Client, handle: str) -> Dict[str, Any]:
    perfil = _perfil_por_handle(client, handle)
    if not perfil:
        raise NotFoundException(_NO_EXISTE)
    return perfil


# ---------------------------------------------------------------------------
# El @ propio
# ---------------------------------------------------------------------------

class PerfilPublicoController(Controller):
    path = "/perfil-publico"
    guards = [auth_guard]

    @get()
    async def mi_perfil(self, request: Request, supabase_client: Client) -> MiPerfilPublico:
        fila = await asyncio.to_thread(_perfil_de, supabase_client, _yo(request))
        return MiPerfilPublico(perfil=_salida(fila) if fila else None)

    @put()
    async def guardar(self, request: Request, supabase_client: Client, data: PerfilPublicoIn) -> PerfilPublicoOut:
        """
        Crea o edita el @. **Crearlo es sumarse a la red**, y el formulario dice qué
        se publica antes de mandarlo: es el consentimiento.

        Pasar de privado a público acepta las solicitudes pendientes, como en
        cualquier red: la pregunta que hacían ("¿me dejás ver tus horas?") ya se
        contestó para todo el mundo.
        """
        yo = _yo(request)

        def _guardar() -> Dict[str, Any]:
            actual = _perfil_de(supabase_client, yo)
            dueno = _perfil_por_handle(supabase_client, data.handle)
            if dueno and dueno["user_id"] != yo:
                raise HTTPException(status_code=409, detail=_HANDLE_OCUPADO)

            fila = {
                "handle": data.handle,
                "nombre_visible": data.nombre_visible,
                "licencia": data.licencia,
                "bio": data.bio,
                "visibilidad": data.visibilidad,
            }
            tabla = supabase_client.table("perfiles_publicos")
            try:
                if actual:
                    r = tabla.update(fila).eq("user_id", yo).execute()
                else:
                    r = tabla.insert({"user_id": yo, **fila}).execute()
            except APIError as exc:
                # Dos pilotos pidiendo el mismo @ al mismo tiempo: el chequeo de
                # arriba pasa para los dos y el índice único decide.
                if exc.code == "23505":
                    raise HTTPException(status_code=409, detail=_HANDLE_OCUPADO) from exc
                raise

            if actual and actual["visibilidad"] == "privado" and data.visibilidad == "publico":
                (
                    supabase_client.table("seguimientos")
                    .update({"estado": "aceptado", "aceptado_at": _ahora()})
                    .eq("seguido", yo).eq("estado", "pendiente").execute()
                )
            return r.data[0]

        return _salida(await asyncio.to_thread(_guardar))

    @delete(status_code=200)
    async def salir(self, request: Request, supabase_client: Client) -> MiPerfilPublico:
        """
        Salir de la red: se borra el @ y, en cascada, seguimientos, publicaciones,
        aplausos y comentarios.

        **Los archivos no caen en cascada**: son del storage, no de la base. Se juntan
        antes de borrar —después ya no queda fila que diga cuáles eran— y se borran
        después, cuando la base ya no los referencia.
        """
        yo = _yo(request)

        def _salir() -> None:
            mio = _perfil_de(supabase_client, yo)
            mias = supabase_client.table("publicaciones").select("id").eq("autor", yo).execute().data or []
            fotos: List[str] = []
            if mias:
                r = (
                    supabase_client.table("publicacion_fotos").select("path")
                    .in_("publicacion_id", [m["id"] for m in mias]).execute()
                )
                fotos = [f["path"] for f in (r.data or [])]
            supabase_client.table("perfiles_publicos").delete().eq("user_id", yo).execute()
            storage = SupabaseManager.get_service_client().storage
            try:
                if fotos:
                    storage.from_("publicaciones").remove(fotos)
                if mio and mio.get("avatar_path"):
                    storage.from_("avatares").remove([mio["avatar_path"]])
            except Exception as exc:  # noqa: BLE001
                # Quedan huérfanos para `limpiar_storage.py`; el piloto ya salió de la red.
                print(f"[storage] no se pudieron borrar los archivos de {yo}: {exc!r}")

        await asyncio.to_thread(_salir)
        return MiPerfilPublico(perfil=None)


# ---------------------------------------------------------------------------
# Buscar y seguir
# ---------------------------------------------------------------------------

class PilotosController(Controller):
    path = "/pilotos"
    guards = [auth_guard]

    @get()
    async def buscar(self, request: Request, supabase_client: Client, q: Optional[str] = None) -> List[PilotoResumen]:
        """
        Por comienzo de @ o por cualquier parte del nombre, hasta 20.

        Pide sesión a propósito: sin ella, esto sería un directorio de pilotos
        recorrible por cualquiera. El perfil de a uno sí se abre sin cuenta.
        """
        yo = _yo(request)
        texto = limpiar_busqueda(q)
        if len(texto) < 2:
            return []

        def _buscar() -> List[PilotoResumen]:
            filtro = f'handle.ilike."{texto}%",nombre_visible.ilike."%{texto}%"'
            r = (
                supabase_client.table("perfiles_publicos").select(_COLUMNAS_PERFIL)
                .or_(filtro).order("handle").limit(20).execute()
            )
            return _resumenes(supabase_client, yo, r.data or [])

        return await asyncio.to_thread(_buscar)

    @get("/sugeridos")
    async def sugeridos(self, request: Request, supabase_client: Client) -> List[PilotoResumen]:
        """
        Pilotos públicos que todavía no seguís, los más nuevos primero. Es lo que llena
        una Red vacía: con pocos pilotos en la app, esperar a que alguien busque un
        nombre que no conoce es esperar para siempre.
        """
        yo = _yo(request)

        def _leer() -> List[PilotoResumen]:
            seguidos = [
                s["seguido"] for s in (
                    supabase_client.table("seguimientos").select("seguido").eq("seguidor", yo).execute().data or []
                )
            ]
            bloquee, me_bloquearon = _bloqueos(yo)
            fuera = [yo, *seguidos, *bloquee, *me_bloquearon]
            r = (
                supabase_client.table("perfiles_publicos").select(_COLUMNAS_PERFIL)
                .eq("visibilidad", "publico").not_.in_("user_id", fuera)
                .order("created_at", desc=True).limit(6).execute()
            )
            return _resumenes(supabase_client, yo, r.data or [])

        return await asyncio.to_thread(_leer)

    @post("/{handle:str}/seguir", status_code=200)
    async def seguir(self, request: Request, supabase_client: Client, handle: str) -> EstadoSeguimiento:
        """
        A un perfil público se lo sigue directo; a uno privado se le manda una
        solicitud. Seguir exige tener @ propio: el otro tiene que poder ver quién es.
        """
        yo = _yo(request)
        h = _handle_o_404(handle)

        def _seguir() -> str:
            mio = _perfil_de(supabase_client, yo)
            if not mio:
                raise HTTPException(
                    status_code=409,
                    detail="Creá tu @ en el Hangar para seguir a otros pilotos.",
                )
            destino = _destino(supabase_client, h)
            if destino["user_id"] == yo:
                raise HTTPException(status_code=400, detail="No podés seguirte a vos mismo.")
            bloquee, me_bloquearon = _bloqueos(yo)
            if destino["user_id"] in me_bloquearon:
                raise NotFoundException(_NO_EXISTE)
            if destino["user_id"] in bloquee:
                raise HTTPException(status_code=409, detail=f"Primero desbloqueá a @{destino['handle']}.")

            previo = _mis_estados(supabase_client, yo, [destino["user_id"]]).get(destino["user_id"])
            if previo:
                return previo

            estado = "aceptado" if destino["visibilidad"] == "publico" else "pendiente"
            fila = {"seguidor": yo, "seguido": destino["user_id"], "estado": estado}
            if estado == "aceptado":
                fila["aceptado_at"] = _ahora()
            try:
                supabase_client.table("seguimientos").insert(fila).execute()
            except APIError as exc:
                # Doble toque: la fila ya existe. Vale lo que haya quedado.
                if exc.code != "23505":
                    raise
                return _mis_estados(supabase_client, yo, [destino["user_id"]]).get(destino["user_id"], estado)
            # Sólo con la fila nueva: un doble toque no avisa dos veces.
            enviar_aviso(
                destino["user_id"],
                armar_aviso("seguidor" if estado == "aceptado" else "solicitud", mio["nombre_visible"]),
            )
            return estado

        estado = await asyncio.to_thread(_seguir)
        return EstadoSeguimiento(relacion="siguiendo" if estado == "aceptado" else "pendiente")

    @delete("/{handle:str}/seguir", status_code=200)
    async def dejar_de_seguir(self, request: Request, supabase_client: Client, handle: str) -> EstadoSeguimiento:
        """Dejar de seguir o cancelar una solicitud: es la misma fila."""
        yo = _yo(request)
        h = _handle_o_404(handle)

        def _borrar() -> None:
            destino = _destino(supabase_client, h)
            (
                supabase_client.table("seguimientos").delete()
                .eq("seguidor", yo).eq("seguido", destino["user_id"]).execute()
            )

        await asyncio.to_thread(_borrar)
        return EstadoSeguimiento(relacion="ninguna")

    @post("/{handle:str}/bloqueo", status_code=200)
    async def bloquear(self, request: Request, supabase_client: Client, handle: str) -> EstadoSeguimiento:
        """
        Bloquear: ninguno de los dos ve lo del otro, y se cortan los seguimientos en las
        dos direcciones. El otro no se entera: para él, este perfil deja de existir. Ver
        la migración 021.
        """
        yo = _yo(request)
        h = _handle_o_404(handle)

        def _bloquear() -> None:
            if not _perfil_de(supabase_client, yo):
                raise HTTPException(status_code=409, detail="Creá tu @ para usar la red.")
            destino = _destino(supabase_client, h)
            if destino["user_id"] == yo:
                raise HTTPException(status_code=400, detail="No podés bloquearte a vos mismo.")
            try:
                supabase_client.table("bloqueos").insert({"bloqueador": yo, "bloqueado": destino["user_id"]}).execute()
            except APIError as exc:
                if exc.code != "23505":  # ya estaba bloqueado: doble toque
                    raise
            tabla = supabase_client.table("seguimientos")
            tabla.delete().eq("seguidor", yo).eq("seguido", destino["user_id"]).execute()
            supabase_client.table("seguimientos").delete().eq("seguidor", destino["user_id"]).eq("seguido", yo).execute()

        await asyncio.to_thread(_bloquear)
        return EstadoSeguimiento(relacion="bloqueado")

    @delete("/{handle:str}/bloqueo", status_code=200)
    async def desbloquear(self, request: Request, supabase_client: Client, handle: str) -> EstadoSeguimiento:
        """Desbloquear no devuelve los seguimientos: si se quieren, se vuelven a pedir."""
        yo = _yo(request)
        h = _handle_o_404(handle)

        def _desbloquear() -> None:
            destino = _destino(supabase_client, h)
            supabase_client.table("bloqueos").delete().eq("bloqueador", yo).eq("bloqueado", destino["user_id"]).execute()

        await asyncio.to_thread(_desbloquear)
        return EstadoSeguimiento(relacion="ninguna")


# ---------------------------------------------------------------------------
# Lo mío: solicitudes, seguidores y a quién sigo
# ---------------------------------------------------------------------------

class SocialController(Controller):
    path = "/social"
    guards = [auth_guard]

    @get("/resumen")
    async def resumen(self, request: Request, supabase_client: Client) -> ResumenSocial:
        """Para el layout: el @ propio, su foto y el punto rojo de Pilotos."""

        def _resumen() -> ResumenSocial:
            # Un solo viaje: `resumen_social()` (migración 019) cuenta solicitudes y
            # actividad nueva adentro de la base. El layout lo pide en cada pantalla.
            filas = supabase_client.rpc("resumen_social").execute().data or []
            if not filas:
                return ResumenSocial()
            f = filas[0]
            return ResumenSocial(
                handle=f.get("handle"),
                avatar_url=_avatar(f),
                solicitudes_pendientes=f.get("solicitudes_pendientes") or 0,
                actividad_nueva=f.get("actividad_nueva") or 0,
            )

        return await asyncio.to_thread(_resumen)

    def _lista(self, supabase_client: Client, yo: str, columna_mia: str, columna_otro: str, estado: Optional[str]) -> List[PilotoResumen]:
        consulta = supabase_client.table("seguimientos").select(columna_otro).eq(columna_mia, yo)
        if estado:
            consulta = consulta.eq("estado", estado)
        ids = [fila[columna_otro] for fila in (consulta.execute().data or [])]
        return _resumenes(supabase_client, yo, _perfiles_de(supabase_client, ids))

    @get("/solicitudes")
    async def solicitudes(self, request: Request, supabase_client: Client) -> List[PilotoResumen]:
        """Quiénes pidieron seguirme y todavía no contesté."""
        yo = _yo(request)
        return await asyncio.to_thread(self._lista, supabase_client, yo, "seguido", "seguidor", "pendiente")

    @get("/seguidores")
    async def seguidores(self, request: Request, supabase_client: Client) -> List[PilotoResumen]:
        yo = _yo(request)
        return await asyncio.to_thread(self._lista, supabase_client, yo, "seguido", "seguidor", "aceptado")

    @get("/siguiendo")
    async def siguiendo(self, request: Request, supabase_client: Client) -> List[PilotoResumen]:
        """A quién sigo, incluidas las solicitudes que todavía no me aceptaron."""
        yo = _yo(request)
        return await asyncio.to_thread(self._lista, supabase_client, yo, "seguidor", "seguido", None)

    @get("/bloqueados")
    async def bloqueados(self, request: Request, supabase_client: Client) -> List[PilotoResumen]:
        """A quiénes bloqueé, para poder desbloquearlos desde el Hangar."""
        yo = _yo(request)

        def _leer() -> List[PilotoResumen]:
            ids = [
                f["bloqueado"]
                for f in (
                    supabase_client.table("bloqueos").select("bloqueado").eq("bloqueador", yo).execute().data or []
                )
            ]
            return _resumenes(supabase_client, yo, _perfiles_de(supabase_client, ids))

        return await asyncio.to_thread(_leer)

    @post("/solicitudes/{handle:str}/aceptar", status_code=200)
    async def aceptar(self, request: Request, supabase_client: Client, handle: str) -> Dict[str, bool]:
        yo = _yo(request)
        h = _handle_o_404(handle)

        def _aceptar() -> None:
            quien = _destino(supabase_client, h)
            r = (
                supabase_client.table("seguimientos")
                .update({"estado": "aceptado", "aceptado_at": _ahora()})
                .eq("seguidor", quien["user_id"]).eq("seguido", yo).eq("estado", "pendiente")
                .execute()
            )
            if not r.data:
                raise NotFoundException("Esa solicitud ya no está.")
            mio = _perfil_de(supabase_client, yo)
            if mio:
                enviar_aviso(
                    quien["user_id"],
                    armar_aviso("aceptada", mio["nombre_visible"], url=f"/dashboard/pilotos/{mio['handle']}"),
                )

        await asyncio.to_thread(_aceptar)
        return {"ok": True}

    @delete("/solicitudes/{handle:str}", status_code=200)
    async def rechazar(self, request: Request, supabase_client: Client, handle: str) -> Dict[str, bool]:
        """Rechazar borra la solicitud. El otro puede volver a pedir."""
        yo = _yo(request)
        h = _handle_o_404(handle)

        def _rechazar() -> None:
            quien = _destino(supabase_client, h)
            (
                supabase_client.table("seguimientos").delete()
                .eq("seguidor", quien["user_id"]).eq("seguido", yo).eq("estado", "pendiente")
                .execute()
            )

        await asyncio.to_thread(_rechazar)
        return {"ok": True}

    @delete("/seguidores/{handle:str}", status_code=200)
    async def sacar_seguidor(self, request: Request, supabase_client: Client, handle: str) -> Dict[str, bool]:
        """Sacar a alguien de mis seguidores. Si mi perfil es público, puede volver."""
        yo = _yo(request)
        h = _handle_o_404(handle)

        def _sacar() -> None:
            quien = _destino(supabase_client, h)
            (
                supabase_client.table("seguimientos").delete()
                .eq("seguidor", quien["user_id"]).eq("seguido", yo).execute()
            )

        await asyncio.to_thread(_sacar)
        return {"ok": True}


# ---------------------------------------------------------------------------
# El perfil público
# ---------------------------------------------------------------------------

class PerfilesPublicosController(Controller):
    """
    `GET /publico/pilotos/{handle}`, **sin guard**: es lo que abre el link de `/u/...`
    que un piloto comparte por WhatsApp, y el que lo recibe puede no tener cuenta.

    Con un Bearer válido, identifica al que mira para saber si lo sigue. Sin Bearer —o
    con uno inválido— es anónimo, y ve lo que vería cualquiera. No acepta `X-API-Key`:
    no hay nada acá que una integración necesite.

    Cada consulta crea su propio cliente de service role: `/dashboard` ya mostró que un
    cliente de supabase-py compartido entre hilos pierde consultas en silencio.
    """

    path = "/publico/pilotos"

    @get("/{handle:str}")
    async def perfil(self, request: Request, handle: str) -> PilotoPublico:
        h = _handle_o_404(handle)
        token = AuthHandler.extract_bearer_token(request)
        viewer = await asyncio.to_thread(verify_access_token, token) if token else None

        perfil = await asyncio.to_thread(
            lambda: _perfil_por_handle(SupabaseManager.get_service_client(), h)
        )
        if not perfil:
            raise NotFoundException(_NO_EXISTE)
        pid = perfil["user_id"]

        # Para quien fue bloqueado, este perfil no existe: el mismo 404 que un @ que no
        # está, así no se entera. Quien bloqueó lo ve, sin horas, para desbloquear.
        bloquee, me_bloquearon = await asyncio.to_thread(_bloqueos, viewer)
        if pid in me_bloquearon:
            raise NotFoundException(_NO_EXISTE)

        def _contar(columna: str) -> int:
            r = (
                SupabaseManager.get_service_client().table("seguimientos")
                .select("seguidor", count="exact", head=True)
                .eq(columna, pid).eq("estado", "aceptado").execute()
            )
            return r.count or 0

        def _estado_del_que_mira() -> Optional[str]:
            if not viewer or viewer == pid:
                return None
            r = (
                SupabaseManager.get_service_client().table("seguimientos").select("estado")
                .eq("seguidor", viewer).eq("seguido", pid).execute()
            )
            return r.data[0]["estado"] if r.data else None

        seguidores, siguiendo, estado = await asyncio.gather(
            asyncio.to_thread(_contar, "seguido"),
            asyncio.to_thread(_contar, "seguidor"),
            asyncio.to_thread(_estado_del_que_mira),
        )
        relacion = "bloqueado" if pid in bloquee else relacion_con(viewer, pid, estado)

        horas: Optional[HorasPublicas] = None
        # Primero se decide, después se consulta. Sin permiso, las horas de este
        # piloto no se leen: no hay nada que filtrar después porque no se trajo.
        if puede_ver_horas(perfil["visibilidad"], relacion):
            def _filas(tabla: str, columnas: str) -> List[Dict[str, Any]]:
                return (
                    SupabaseManager.get_service_client().table(tabla).select(columnas)
                    .eq("user_id", pid).execute().data or []
                )

            def _vuelos() -> List[Dict[str, Any]]:
                # Las horas de alumno no cuentan una vez rendida la PPA (migración 022).
                # Sin fecha —quien nunca fue alumno en Vector—, cuentan todas.
                cliente = SupabaseManager.get_service_client()
                ppa = (cliente.table("profiles").select("fecha_ppa").eq("id", pid).limit(1).execute().data or [{}])[0].get("fecha_ppa")
                q = cliente.table("flights").select(COLUMNAS_VUELO).eq("user_id", pid)
                if ppa:
                    q = q.gte("date", ppa)
                return q.execute().data or []

            flights, logbooks, aircraft = await asyncio.gather(
                asyncio.to_thread(_vuelos),
                asyncio.to_thread(_filas, "logbooks", COLUMNAS_LIBRO),
                asyncio.to_thread(_filas, "aircraft", "id, is_simulator"),
            )
            horas = HorasPublicas(**estadisticas_publicas(flights, logbooks, aircraft))

        return PilotoPublico(
            handle=perfil["handle"],
            nombre_visible=perfil["nombre_visible"],
            licencia=perfil.get("licencia"),
            bio=perfil.get("bio"),
            visibilidad=perfil["visibilidad"],
            seguidores=seguidores,
            siguiendo=siguiendo,
            relacion=relacion,
            horas=horas,
            avatar_url=_avatar(perfil),
        )
