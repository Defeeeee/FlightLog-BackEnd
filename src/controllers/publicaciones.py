"""
La red con contenido: foto de perfil, publicaciones, aplausos, comentarios, la Red y la
Actividad.

**El RLS decide qué se ve, no este archivo.** Toda lectura va con el cliente de quien
mira —el suyo si trae un Bearer válido, el anónimo si no— y la migración 019 filtra por
`puede_ver_autor()`. Lo que se consulta acá con service role es sólo el storage (subir,
firmar, borrar), y siempre **después** de que la fila correspondiente pasó por el RLS.

**Por eso estas rutas exigen Bearer y no aceptan `X-API-Key`.** Con una API key,
`provide_supabase_client` entrega un cliente de service role, que se saltea el RLS: en
esta parte del backend eso significaría ver lo que el piloto no puede ver.

Cada consulta que va en paralelo crea su propio cliente. `/dashboard` ya mostró que un
cliente de supabase-py compartido entre hilos pierde consultas en silencio.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Callable, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

from litestar import Controller, Request, delete, get, post
from litestar.datastructures import UploadFile
from litestar.enums import RequestEncodingType
from litestar.exceptions import HTTPException, NotAuthorizedException, NotFoundException
from litestar.params import Body
from postgrest.exceptions import APIError
from supabase import Client

from src.auth.guards import auth_guard
from src.auth.security import AuthHandler
from src.config import settings
from src.controllers.social import _handle_o_404, _perfil_de, _perfil_por_handle, _yo
from src.models.social import (
    Actividad,
    AutorOut,
    AvatarOut,
    ComentarioIn,
    ComentarioOut,
    EstadoAplauso,
    EventoActividad,
    FotoOut,
    PaginaPublicaciones,
    PublicacionOut,
    VueloChip,
)
from src.services.imagenes import ImagenInvalida, procesar_avatar, procesar_foto
from src.services.social import (
    COMENTARIOS_POR_DIA,
    FOTOS_MAX,
    PUBLICACIONES_POR_DIA,
    ordenar_actividad,
    resumen_de_vuelo,
    url_avatar,
    validar_comentario,
    validar_publicacion,
)
from src.supabase_client import SupabaseManager, verify_access_token

BUCKET_FOTOS = "publicaciones"
BUCKET_AVATARES = "avatares"
#: Lo que dura una URL firmada. Las páginas se piden sin cache, así que alcanza con que
#: sobreviva a una pestaña abierta un rato largo.
FIRMA_SEGUNDOS = 6 * 60 * 60
POR_PAGINA = 15

_AUTOR = "handle, nombre_visible, licencia, avatar_path"
_COLUMNAS_PUBLICACION = (
    "id, texto, vuelo, vuelo_id, created_at, autor, "
    f"perfil:perfiles_publicos!publicaciones_autor_fkey({_AUTOR}), "
    "fotos:publicacion_fotos(path, ancho, alto, orden), "
    "aplausos(count), comentarios(count)"
)
_SIN_HANDLE = "Creá tu @ para usar la red."


# ---------------------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------------------

def _token_o_401(request: Request) -> str:
    token = AuthHandler.extract_bearer_token(request)
    if not token:
        raise NotAuthorizedException("Esta acción necesita una sesión iniciada.")
    return token


async def _cliente_del_que_mira(request: Request) -> Tuple[Callable[[], Client], Optional[str]]:
    """
    Una fábrica de clientes con los permisos de quien mira, y quién es.

    Con un Bearer válido, clientes suyos; si no hay Bearer —o no valida—, anónimos. Es
    una fábrica y no un cliente porque cada consulta en paralelo necesita el propio.
    """
    token = AuthHandler.extract_bearer_token(request)
    viewer = await asyncio.to_thread(verify_access_token, token) if token else None
    if viewer and token:
        return (lambda: SupabaseManager.get_user_scoped_client(access_token=token)), viewer
    return SupabaseManager.get_base_client, None


def _fabrica(token: str) -> Callable[[], Client]:
    return lambda: SupabaseManager.get_user_scoped_client(access_token=token)


async def _en_paralelo(*tareas: Callable[[], Any]) -> List[Any]:
    return list(await asyncio.gather(*(asyncio.to_thread(t) for t in tareas)))


def _storage(bucket: str):
    return SupabaseManager.get_service_client().storage.from_(bucket)


def _borrar_archivos(bucket: str, paths: List[str]) -> None:
    """Best effort: un archivo huérfano lo barre `limpiar_storage.py`; un error acá no
    puede tirar abajo lo que el piloto pidió."""
    if not paths:
        return
    try:
        _storage(bucket).remove(paths)
    except Exception as exc:  # noqa: BLE001
        print(f"[storage] no se pudieron borrar {len(paths)} archivos de {bucket}: {exc!r}")


# ---------------------------------------------------------------------------
# Armar lo que sale
# ---------------------------------------------------------------------------

def _autor(perfil: Optional[Dict[str, Any]]) -> AutorOut:
    perfil = perfil or {}
    return AutorOut(
        handle=perfil.get("handle") or "",
        nombre_visible=perfil.get("nombre_visible") or "",
        licencia=perfil.get("licencia"),
        avatar_url=url_avatar(settings.supabase_url, perfil.get("avatar_path")),
    )


def _conteo(valor: Any) -> int:
    """`aplausos(count)` llega como `[{"count": 3}]`."""
    if isinstance(valor, list) and valor and isinstance(valor[0], dict):
        return int(valor[0].get("count") or 0)
    return 0


def _firmar(paths: List[str]) -> Dict[str, str]:
    if not paths:
        return {}
    firmadas = _storage(BUCKET_FOTOS).create_signed_urls(paths, FIRMA_SEGUNDOS)
    return {
        f["path"]: f.get("signedURL") or f.get("signedUrl")
        for f in firmadas
        if f.get("path") and not f.get("error") and (f.get("signedURL") or f.get("signedUrl"))
    }


def _armar(filas: List[Dict[str, Any]], viewer: Optional[str], cliente: Callable[[], Client]) -> List[PublicacionOut]:
    """Las filas que dejó pasar el RLS, con URLs firmadas y el aplauso de quien mira."""
    if not filas:
        return []
    ids = [f["id"] for f in filas]
    paths = [foto["path"] for f in filas for foto in (f.get("fotos") or [])]

    def _mis_aplausos() -> set:
        if not viewer:
            return set()
        r = cliente().table("aplausos").select("publicacion_id").eq("user_id", viewer).in_("publicacion_id", ids).execute()
        return {a["publicacion_id"] for a in (r.data or [])}

    # Las dos son independientes y cada una es un viaje a us-east-1. `_armar` ya corre
    # adentro de un hilo —no hay event loop acá—, así que van a un pool chico.
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_aplausos = pool.submit(_mis_aplausos)
        f_urls = pool.submit(_firmar, paths)
        aplaudidas, urls = f_aplausos.result(), f_urls.result()

    salida = []
    for f in filas:
        fotos = sorted(f.get("fotos") or [], key=lambda x: x.get("orden") or 0)
        es_mia = bool(viewer) and viewer == f.get("autor")
        salida.append(
            PublicacionOut(
                id=f["id"],
                autor=_autor(f.get("perfil")),
                texto=f.get("texto"),
                vuelo=VueloChip(**f["vuelo"]) if f.get("vuelo") else None,
                fotos=[
                    FotoOut(url=urls[x["path"]], ancho=x["ancho"], alto=x["alto"])
                    for x in fotos
                    if x.get("path") in urls
                ],
                aplausos=_conteo(f.get("aplausos")),
                aplaudida=f["id"] in aplaudidas,
                comentarios=_conteo(f.get("comentarios")),
                es_mia=es_mia,
                vuelo_id=f.get("vuelo_id") if es_mia else None,
                created_at=f["created_at"],
            )
        )
    return salida


def _pagina(filas: List[Dict[str, Any]], viewer: Optional[str], cliente: Callable[[], Client]) -> PaginaPublicaciones:
    siguiente = filas[-1]["created_at"] if len(filas) == POR_PAGINA else None
    return PaginaPublicaciones(publicaciones=_armar(filas, viewer, cliente), siguiente=siguiente)


def _cursor(antes: Optional[str]) -> Optional[str]:
    """Un `antes` que no es una fecha se ignora: vale más la primera página que un 400."""
    if not antes:
        return None
    try:
        return datetime.fromisoformat(antes.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


def _hace_un_dia() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


def _flag(valor: Any) -> bool:
    return str(valor).lower() in ("1", "true", "on", "si", "sí")


# ---------------------------------------------------------------------------
# La foto de perfil
# ---------------------------------------------------------------------------

class AvatarController(Controller):
    path = "/perfil-publico/avatar"
    guards = [auth_guard]

    @post(status_code=200)
    async def subir(
        self,
        request: Request,
        data: Annotated[Dict[str, Any], Body(media_type=RequestEncodingType.MULTI_PART)],
    ) -> AvatarOut:
        token = _token_o_401(request)
        yo = _yo(request)
        archivo = data.get("archivo")
        if not isinstance(archivo, UploadFile):
            raise HTTPException(status_code=400, detail="Elegí una foto.")
        crudo = await archivo.read()
        try:
            webp = await asyncio.to_thread(procesar_avatar, crudo)
        except ImagenInvalida as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        def _guardar() -> Optional[str]:
            cliente = _fabrica(token)()
            actual = _perfil_de(cliente, yo)
            if not actual:
                raise HTTPException(status_code=409, detail=_SIN_HANDLE)
            path = f"{uuid4().hex}.webp"
            _storage(BUCKET_AVATARES).upload(
                path, webp, {"content-type": "image/webp", "upsert": "false", "cache-control": "31536000"}
            )
            try:
                cliente.table("perfiles_publicos").update({"avatar_path": path}).eq("user_id", yo).execute()
            except Exception:
                _borrar_archivos(BUCKET_AVATARES, [path])
                raise
            _borrar_archivos(BUCKET_AVATARES, [actual["avatar_path"]] if actual.get("avatar_path") else [])
            return path

        path = await asyncio.to_thread(_guardar)
        return AvatarOut(avatar_url=url_avatar(settings.supabase_url, path))

    @delete(status_code=200)
    async def sacar(self, request: Request) -> AvatarOut:
        token = _token_o_401(request)
        yo = _yo(request)

        def _sacar() -> None:
            cliente = _fabrica(token)()
            actual = _perfil_de(cliente, yo)
            if not actual or not actual.get("avatar_path"):
                return
            cliente.table("perfiles_publicos").update({"avatar_path": None}).eq("user_id", yo).execute()
            _borrar_archivos(BUCKET_AVATARES, [actual["avatar_path"]])

        await asyncio.to_thread(_sacar)
        return AvatarOut(avatar_url=None)


# ---------------------------------------------------------------------------
# Publicar, aplaudir, comentar
# ---------------------------------------------------------------------------

class PublicacionesController(Controller):
    path = "/publicaciones"
    guards = [auth_guard]

    @post(status_code=201)
    async def publicar(
        self,
        request: Request,
        data: Annotated[Dict[str, Any], Body(media_type=RequestEncodingType.MULTI_PART)],
    ) -> PublicacionOut:
        """
        Texto, hasta cuatro fotos y, si el piloto quiere, un vuelo suyo con los datos que
        prendió (`mostrar_ruta`, `mostrar_duracion`, `mostrar_aeronave`, `mostrar_fecha`).

        Las fotos van en campos `foto_0`…`foto_3` y no en uno repetido: el parseo de un
        campo repetido en multipart depende de la versión, y un nombre por foto no.
        """
        token = _token_o_401(request)
        yo = _yo(request)
        texto = (str(data.get("texto") or "")).strip() or None
        vuelo_id = str(data.get("vuelo_id") or "").strip() or None
        archivos = [data[f"foto_{i}"] for i in range(FOTOS_MAX + 2) if isinstance(data.get(f"foto_{i}"), UploadFile)]
        interruptores = {k: _flag(data.get(f"mostrar_{k}")) for k in ("ruta", "duracion", "aeronave", "fecha")}

        motivo = validar_publicacion(texto, len(archivos), bool(vuelo_id))
        if motivo:
            raise HTTPException(status_code=400, detail=motivo)

        crudos = [await a.read() for a in archivos]
        try:
            fotos = await asyncio.to_thread(lambda: [procesar_foto(b) for b in crudos])
        except ImagenInvalida as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        def _crear() -> str:
            cliente = _fabrica(token)()
            if not _perfil_de(cliente, yo):
                raise HTTPException(status_code=409, detail=_SIN_HANDLE)
            recientes = (
                cliente.table("publicaciones").select("id", count="exact", head=True)
                .eq("autor", yo).gte("created_at", _hace_un_dia()).execute()
            )
            if (recientes.count or 0) >= PUBLICACIONES_POR_DIA:
                raise HTTPException(status_code=429, detail="Llegaste al máximo de publicaciones por hoy.")

            chip = None
            if vuelo_id:
                vuelo = (
                    cliente.table("flights").select("id, route, duration, date, aircraft_id")
                    .eq("id", vuelo_id).eq("user_id", yo).limit(1).execute().data
                )
                if not vuelo:
                    raise HTTPException(status_code=404, detail="No encontramos ese vuelo en tu bitácora.")
                avion = None
                if vuelo[0].get("aircraft_id"):
                    r = cliente.table("aircraft").select("type").eq("id", vuelo[0]["aircraft_id"]).limit(1).execute()
                    avion = r.data[0] if r.data else None
                chip = resumen_de_vuelo(vuelo[0], avion, **interruptores)

            if not texto and not fotos and not chip:
                raise HTTPException(status_code=400, detail="Prendé al menos un dato del vuelo, o sumá texto o una foto.")

            subidas: List[Tuple[str, int, int]] = []
            publicacion_id: Optional[str] = None
            try:
                for contenido, ancho, alto in fotos:
                    path = f"{uuid4().hex}.webp"
                    _storage(BUCKET_FOTOS).upload(
                        path, contenido, {"content-type": "image/webp", "upsert": "false", "cache-control": "31536000"}
                    )
                    subidas.append((path, ancho, alto))
                fila = (
                    cliente.table("publicaciones")
                    .insert({"autor": yo, "texto": texto, "vuelo": chip, "vuelo_id": vuelo_id if chip else None})
                    .execute().data[0]
                )
                publicacion_id = fila["id"]
                if subidas:
                    cliente.table("publicacion_fotos").insert([
                        {"publicacion_id": publicacion_id, "path": p, "ancho": w, "alto": h, "orden": i}
                        for i, (p, w, h) in enumerate(subidas)
                    ]).execute()
            except Exception:
                # Todo o nada: una publicación sin sus fotos, o fotos sin publicación,
                # son las dos cosas que el piloto no pidió.
                if publicacion_id:
                    try:
                        cliente.table("publicaciones").delete().eq("id", publicacion_id).execute()
                    except Exception:  # noqa: BLE001
                        pass
                _borrar_archivos(BUCKET_FOTOS, [p for p, _, _ in subidas])
                raise
            return publicacion_id

        publicacion_id = await asyncio.to_thread(_crear)
        return await asyncio.to_thread(_una, _fabrica(token), yo, publicacion_id)

    @delete("/{publicacion_id:uuid}", status_code=200)
    async def borrar(self, request: Request, publicacion_id: UUID) -> Dict[str, bool]:
        token = _token_o_401(request)
        yo = _yo(request)

        def _borrar() -> None:
            cliente = _fabrica(token)()
            fotos = cliente.table("publicacion_fotos").select("path").eq("publicacion_id", str(publicacion_id)).execute().data or []
            r = cliente.table("publicaciones").delete().eq("id", str(publicacion_id)).eq("autor", yo).execute()
            if not r.data:
                raise NotFoundException("Esa publicación ya no está.")
            _borrar_archivos(BUCKET_FOTOS, [f["path"] for f in fotos])

        await asyncio.to_thread(_borrar)
        return {"ok": True}

    @post("/{publicacion_id:uuid}/aplauso", status_code=200)
    async def aplaudir(self, request: Request, publicacion_id: UUID) -> EstadoAplauso:
        return await self._aplauso(request, publicacion_id, True)

    @delete("/{publicacion_id:uuid}/aplauso", status_code=200)
    async def desaplaudir(self, request: Request, publicacion_id: UUID) -> EstadoAplauso:
        return await self._aplauso(request, publicacion_id, False)

    async def _aplauso(self, request: Request, publicacion_id: UUID, poner: bool) -> EstadoAplauso:
        token = _token_o_401(request)
        yo = _yo(request)
        pid = str(publicacion_id)

        def _hacer() -> EstadoAplauso:
            cliente = _fabrica(token)()
            tabla = cliente.table("aplausos")
            if poner:
                try:
                    tabla.insert({"publicacion_id": pid, "user_id": yo}).execute()
                except APIError as exc:
                    if exc.code == "23505":
                        pass  # Ya estaba: doble toque.
                    elif exc.code == "23503":
                        raise HTTPException(status_code=409, detail=_SIN_HANDLE) from exc
                    elif exc.code == "42501":
                        raise NotFoundException("Esa publicación ya no está.") from exc
                    else:
                        raise
            else:
                tabla.delete().eq("publicacion_id", pid).eq("user_id", yo).execute()
            total = cliente.table("aplausos").select("user_id", count="exact", head=True).eq("publicacion_id", pid).execute()
            return EstadoAplauso(aplausos=total.count or 0, aplaudida=poner)

        return await asyncio.to_thread(_hacer)

    @post("/{publicacion_id:uuid}/comentarios", status_code=201)
    async def comentar(self, request: Request, publicacion_id: UUID, data: ComentarioIn) -> ComentarioOut:
        token = _token_o_401(request)
        yo = _yo(request)
        try:
            texto = validar_comentario(data.texto)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        def _comentar() -> ComentarioOut:
            cliente = _fabrica(token)()
            mio = _perfil_de(cliente, yo)
            if not mio:
                raise HTTPException(status_code=409, detail=_SIN_HANDLE)
            recientes = (
                cliente.table("comentarios").select("id", count="exact", head=True)
                .eq("autor", yo).gte("created_at", _hace_un_dia()).execute()
            )
            if (recientes.count or 0) >= COMENTARIOS_POR_DIA:
                raise HTTPException(status_code=429, detail="Llegaste al máximo de comentarios por hoy.")
            try:
                fila = (
                    cliente.table("comentarios")
                    .insert({"publicacion_id": str(publicacion_id), "autor": yo, "texto": texto})
                    .execute().data[0]
                )
            except APIError as exc:
                if exc.code in ("42501", "23503"):
                    raise NotFoundException("Esa publicación ya no está.") from exc
                raise
            return ComentarioOut(
                id=fila["id"], autor=_autor(mio), texto=fila["texto"], created_at=fila["created_at"], puede_borrar=True
            )

        return await asyncio.to_thread(_comentar)

    @delete("/comentarios/{comentario_id:uuid}", status_code=200)
    async def borrar_comentario(self, request: Request, comentario_id: UUID) -> Dict[str, bool]:
        """Lo borra su autor o el de la publicación: el RLS decide cuál de los dos es."""
        token = _token_o_401(request)

        def _borrar() -> None:
            r = _fabrica(token)().table("comentarios").delete().eq("id", str(comentario_id)).execute()
            if not r.data:
                raise NotFoundException("Ese comentario ya no está.")

        await asyncio.to_thread(_borrar)
        return {"ok": True}


def _una(fabrica: Callable[[], Client], viewer: Optional[str], publicacion_id: str) -> PublicacionOut:
    filas = fabrica().table("publicaciones").select(_COLUMNAS_PUBLICACION).eq("id", publicacion_id).limit(1).execute().data or []
    if not filas:
        raise NotFoundException("Esa publicación ya no está.")
    return _armar(filas, viewer, fabrica)[0]


# ---------------------------------------------------------------------------
# La Red y la Actividad
# ---------------------------------------------------------------------------

class RedController(Controller):
    path = "/red"
    guards = [auth_guard]

    @get("/feed")
    async def feed(self, request: Request, antes: Optional[str] = None) -> PaginaPublicaciones:
        """Lo tuyo y lo de quienes seguís con aceptación, lo más nuevo primero."""
        token = _token_o_401(request)
        yo = _yo(request)
        fabrica = _fabrica(token)
        cursor = _cursor(antes)

        def _leer() -> PaginaPublicaciones:
            cliente = fabrica()
            seguidos = (
                cliente.table("seguimientos").select("seguido").eq("seguidor", yo).eq("estado", "aceptado").execute().data
                or []
            )
            autores = [yo] + [s["seguido"] for s in seguidos]
            consulta = (
                cliente.table("publicaciones").select(_COLUMNAS_PUBLICACION)
                .in_("autor", autores).order("created_at", desc=True).limit(POR_PAGINA)
            )
            if cursor:
                consulta = consulta.lt("created_at", cursor)
            return _pagina(consulta.execute().data or [], yo, fabrica)

        return await asyncio.to_thread(_leer)

    @get("/mis-publicaciones")
    async def mis_publicaciones(self, request: Request) -> PaginaPublicaciones:
        """Todo lo propio, para la exportación de datos. Hasta 500, sin paginar."""
        token = _token_o_401(request)
        yo = _yo(request)
        fabrica = _fabrica(token)

        def _leer() -> PaginaPublicaciones:
            filas = (
                fabrica().table("publicaciones").select(_COLUMNAS_PUBLICACION)
                .eq("autor", yo).order("created_at", desc=True).limit(500).execute().data or []
            )
            return PaginaPublicaciones(publicaciones=_armar(filas, yo, fabrica), siguiente=None)

        return await asyncio.to_thread(_leer)

    @get("/actividad")
    async def actividad(self, request: Request) -> Actividad:
        """
        Nuevos seguidores, solicitudes, y aplausos y comentarios en lo tuyo, de los
        últimos 60 días. Se arma con las tablas que ya existen: no hay una tabla de
        notificaciones que se pueda desincronizar de lo que pasó.
        """
        token = _token_o_401(request)
        yo = _yo(request)
        fabrica = _fabrica(token)
        desde = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()

        def _vista() -> Optional[str]:
            r = fabrica().table("perfiles_publicos").select("actividad_vista_at").eq("user_id", yo).limit(1).execute()
            return r.data[0]["actividad_vista_at"] if r.data else None

        def _seguimientos() -> List[Dict[str, Any]]:
            return (
                fabrica().table("seguimientos").select("seguidor, estado, created_at, aceptado_at")
                .eq("seguido", yo).gte("created_at", desde).order("created_at", desc=True).limit(40).execute().data
                or []
            )

        def _mias() -> List[Dict[str, Any]]:
            return (
                fabrica().table("publicaciones").select("id, texto")
                .eq("autor", yo).order("created_at", desc=True).limit(100).execute().data or []
            )

        vista, seguimientos, mias = await _en_paralelo(_vista, _seguimientos, _mias)
        if vista is None:
            return Actividad(eventos=[])
        ids = [p["id"] for p in mias]
        textos = {p["id"]: (p.get("texto") or "") for p in mias}

        def _aplausos() -> List[Dict[str, Any]]:
            if not ids:
                return []
            return (
                fabrica().table("aplausos").select("user_id, publicacion_id, created_at")
                .in_("publicacion_id", ids).neq("user_id", yo).gte("created_at", desde)
                .order("created_at", desc=True).limit(40).execute().data or []
            )

        def _comentarios() -> List[Dict[str, Any]]:
            if not ids:
                return []
            return (
                fabrica().table("comentarios").select("autor, publicacion_id, texto, created_at")
                .in_("publicacion_id", ids).neq("autor", yo).gte("created_at", desde)
                .order("created_at", desc=True).limit(40).execute().data or []
            )

        aplausos, comentarios = await _en_paralelo(_aplausos, _comentarios)

        quienes = {s["seguidor"] for s in seguimientos} | {a["user_id"] for a in aplausos} | {c["autor"] for c in comentarios}

        def _perfiles() -> Dict[str, Dict[str, Any]]:
            if not quienes:
                return {}
            r = fabrica().table("perfiles_publicos").select(f"user_id, {_AUTOR}").in_("user_id", list(quienes)).execute()
            return {p["user_id"]: p for p in (r.data or [])}

        (perfiles,) = await _en_paralelo(_perfiles)

        eventos: List[Dict[str, Any]] = []
        for s in seguimientos:
            if s["seguidor"] in perfiles:
                aceptado = s["estado"] == "aceptado"
                eventos.append({
                    "tipo": "seguidor" if aceptado else "solicitud",
                    "quien": s["seguidor"],
                    "created_at": (s.get("aceptado_at") or s["created_at"]) if aceptado else s["created_at"],
                })
        for a in aplausos:
            if a["user_id"] in perfiles:
                eventos.append({"tipo": "aplauso", "quien": a["user_id"], "created_at": a["created_at"],
                                "texto": textos.get(a["publicacion_id"], "")[:80] or None})
        for c in comentarios:
            if c["autor"] in perfiles:
                eventos.append({"tipo": "comentario", "quien": c["autor"], "created_at": c["created_at"],
                                "texto": (c.get("texto") or "")[:140]})

        ordenados = ordenar_actividad(eventos, vista)[:60]
        return Actividad(eventos=[
            EventoActividad(
                tipo=e["tipo"], piloto=_autor(perfiles[e["quien"]]), created_at=e["created_at"],
                nuevo=e["nuevo"], texto=e.get("texto"),
            )
            for e in ordenados
        ])

    @post("/actividad/vista", status_code=200)
    async def marcar_vista(self, request: Request) -> Dict[str, bool]:
        """Abrir la Actividad apaga el punto rojo de lo que ya se vio."""
        token = _token_o_401(request)
        yo = _yo(request)
        await asyncio.to_thread(
            lambda: _fabrica(token)().table("perfiles_publicos")
            .update({"actividad_vista_at": datetime.now(timezone.utc).isoformat()})
            .eq("user_id", yo).execute()
        )
        return {"ok": True}


# ---------------------------------------------------------------------------
# Lo que se ve sin cuenta
# ---------------------------------------------------------------------------

class PublicacionesPublicasController(Controller):
    """
    Sin guard: las publicaciones de un perfil y los comentarios de una publicación se
    ven desde `/u/...` sin cuenta. Qué se ve lo decide el RLS con el cliente de quien
    mira: un anónimo, sólo lo de perfiles públicos.
    """

    path = "/publico"

    @get("/pilotos/{handle:str}/publicaciones")
    async def de_un_piloto(self, request: Request, handle: str, antes: Optional[str] = None) -> PaginaPublicaciones:
        h = _handle_o_404(handle)
        fabrica, viewer = await _cliente_del_que_mira(request)
        cursor = _cursor(antes)

        def _leer() -> PaginaPublicaciones:
            cliente = fabrica()
            perfil = _perfil_por_handle(cliente, h)
            if not perfil:
                raise NotFoundException("No existe ese piloto.")
            consulta = (
                cliente.table("publicaciones").select(_COLUMNAS_PUBLICACION)
                .eq("autor", perfil["user_id"]).order("created_at", desc=True).limit(POR_PAGINA)
            )
            if cursor:
                consulta = consulta.lt("created_at", cursor)
            return _pagina(consulta.execute().data or [], viewer, fabrica)

        return await asyncio.to_thread(_leer)

    @get("/publicaciones/{publicacion_id:uuid}/comentarios")
    async def comentarios(self, request: Request, publicacion_id: UUID) -> List[ComentarioOut]:
        fabrica, viewer = await _cliente_del_que_mira(request)

        def _leer() -> List[ComentarioOut]:
            filas = (
                fabrica().table("comentarios")
                .select(
                    "id, texto, created_at, autor, "
                    f"perfil:perfiles_publicos!comentarios_autor_fkey({_AUTOR}), "
                    "publicacion:publicaciones!inner(autor)"
                )
                .eq("publicacion_id", str(publicacion_id)).order("created_at").limit(200).execute().data or []
            )
            return [
                ComentarioOut(
                    id=f["id"],
                    autor=_autor(f.get("perfil")),
                    texto=f["texto"],
                    created_at=f["created_at"],
                    puede_borrar=bool(viewer) and viewer in (f.get("autor"), (f.get("publicacion") or {}).get("autor")),
                )
                for f in filas
            ]

        return await asyncio.to_thread(_leer)
