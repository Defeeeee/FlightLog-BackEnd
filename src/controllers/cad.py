"""
Pasar al CAD desde Vector (migración 036, `services/cad_anac.py`): el backend entra al CAD
de ANAC con la cuenta que el piloto guardó.

- `GET /cad/conexion`: si el modo está disponible y si el piloto está conectado (nunca la
  contraseña).
- `POST /cad/conexion`: prueba el usuario y la contraseña contra ANAC y, sólo si entran, los
  guarda (la contraseña cifrada). Si ANAC los rechaza no se guarda nada.
- `DELETE /cad/conexion`: borra la cuenta guardada y cierra la sesión.
- `GET /cad/listas`, `GET /cad/vuelos`, `GET /cad/vuelos/{id}`, `GET /cad/modelos?simId=`:
  lecturas del CAD, de la lista blanca.
- `POST /cad/vuelos`: "Crear" del CAD. El vuelo queda "Pendiente de DDJJ".

**La DDJJ no está acá a propósito**: la declaración jurada la hace el piloto en el CAD.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from litestar import Controller, Request, delete, get, post
from litestar.exceptions import HTTPException, ValidationException
from pydantic import BaseModel, Field

from src.auth.guards import auth_guard
from src.controllers.social import _yo
from src.services import cad_anac
from src.supabase_client import SupabaseManager

_TABLA = "cad_conexiones"


class Conexion(BaseModel):
    usuario: str = Field(min_length=1, max_length=120)
    clave: str = Field(min_length=1, max_length=200)


def _fila(user_id: str) -> Optional[Dict[str, Any]]:
    filas = (
        SupabaseManager.get_service_client().table(_TABLA)
        .select("usuario,clave_cifrada,estado,error,conectado_at,usado_at")
        .eq("user_id", user_id).limit(1).execute().data
        or []
    )
    return filas[0] if filas else None


def _anotar(user_id: str, cambios: Dict[str, Any]) -> None:
    SupabaseManager.get_service_client().table(_TABLA).update(cambios).eq("user_id", user_id).execute()


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _credenciales(user_id: str):
    """Lo que `cad_anac.sesion` llama cuando tiene que entrar: la cuenta guardada, si está bien."""

    async def leer() -> Tuple[str, str]:
        fila = await asyncio.to_thread(_fila, user_id)
        if not fila:
            raise cad_anac.ModoApagado("No conectaste tu cuenta de ANAC.")
        if fila.get("estado") == "rechazada":
            raise cad_anac.ClaveRechazada(fila.get("error") or "ANAC rechazó la contraseña guardada.")
        return fila["usuario"], cad_anac.descifrar(fila["clave_cifrada"])

    return leer


async def _con_cad(user_id: str, accion):
    """Corre `accion` y traduce lo que salga mal. Una contraseña rechazada queda anotada."""
    try:
        resultado = await accion()
    except cad_anac.ClaveRechazada as exc:
        await asyncio.to_thread(_anotar, user_id, {"estado": "rechazada", "error": str(exc)[:300]})
        await cad_anac.olvidar_sesion(user_id)
        raise HTTPException(status_code=409, detail=f"{exc} Volvé a escribir tu contraseña de ANAC.") from exc
    except cad_anac.ModoApagado as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except cad_anac.AnacNoContesta as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise ValidationException(str(exc)) from exc
    await asyncio.to_thread(_anotar, user_id, {"usado_at": _ahora()})
    return resultado


class CadController(Controller):
    path = "/cad"
    guards = [auth_guard]

    @get("/conexion")
    async def estado(self, request: Request) -> Dict[str, Any]:
        fila = await asyncio.to_thread(_fila, _yo(request))
        return {
            "disponible": cad_anac.disponible(),
            "conectado": bool(fila),
            "usuario": fila.get("usuario") if fila else None,
            "estado": fila.get("estado") if fila else None,
            "error": fila.get("error") if fila else None,
            "conectado_at": fila.get("conectado_at") if fila else None,
            "usado_at": fila.get("usado_at") if fila else None,
        }

    @post("/conexion", status_code=200)
    async def conectar(self, request: Request, data: Conexion) -> Dict[str, Any]:
        """Entra una vez con lo que escribió el piloto; si entra, lo guarda."""
        if not cad_anac.disponible():
            raise HTTPException(status_code=409, detail="Pasar al CAD desde Vector no está disponible todavía.")
        yo = _yo(request)
        usuario = data.usuario.strip()
        try:
            cliente = await cad_anac.iniciar_sesion(usuario, data.clave)
        except cad_anac.ClaveRechazada as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except cad_anac.AnacNoContesta as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        await cad_anac.guardar_sesion(yo, cliente)
        fila = {
            "user_id": yo,
            "usuario": usuario,
            "clave_cifrada": cad_anac.cifrar(data.clave),
            "estado": "ok",
            "error": None,
            "conectado_at": _ahora(),
            "usado_at": _ahora(),
        }
        await asyncio.to_thread(lambda: SupabaseManager.get_service_client().table(_TABLA).upsert(fila).execute())
        return {"conectado": True, "usuario": usuario, "estado": "ok"}

    @delete("/conexion", status_code=200)
    async def desconectar(self, request: Request) -> Dict[str, bool]:
        yo = _yo(request)
        await cad_anac.olvidar_sesion(yo)
        await asyncio.to_thread(lambda: SupabaseManager.get_service_client().table(_TABLA).delete().eq("user_id", yo).execute())
        return {"conectado": False}

    @get("/listas")
    async def listas(self, request: Request) -> Dict[str, Any]:
        """Finalidades, autoridades, aeródromos (con los LAD adentro) y simuladores."""
        yo = _yo(request)
        cred = _credenciales(yo)

        async def leer():
            fin, aut, lug, sim = await asyncio.gather(
                cad_anac.pedir(yo, cred, "GetFinalidadListItem", {"tcp": "false"}),
                cad_anac.pedir(yo, cred, "GetAutoridadesListItem"),
                cad_anac.pedir(yo, cred, "GetLugarAterrizajeListItem", {"tipoLugar": "AER", "tipoVuelo": "2"}),
                cad_anac.pedir(yo, cred, "GetSimuladoresListItem"),
            )
            return {"finalidades": fin, "autoridades": aut, "lugares": lug, "simuladores": sim}

        return await _con_cad(yo, leer)

    @get("/vuelos")
    async def vuelos(self, request: Request) -> Dict[str, Any]:
        yo = _yo(request)
        return await _con_cad(yo, lambda: _envolver(cad_anac.vuelos(yo, _credenciales(yo))))

    @get("/vuelos/{vuelo_id:int}")
    async def vuelo(self, request: Request, vuelo_id: int) -> Dict[str, Any]:
        yo = _yo(request)
        return await _con_cad(yo, lambda: _detalle(cad_anac.pedir(yo, _credenciales(yo), "Get", {"id": str(vuelo_id)})))

    @get("/modelos")
    async def modelos(self, request: Request, simId: int) -> Dict[str, Any]:  # noqa: N803 (como lo llama el CAD)
        yo = _yo(request)
        return await _con_cad(
            yo, lambda: _envolver(cad_anac.pedir(yo, _credenciales(yo), "GetModelosPorSimuladorListItem", {"simId": str(simId)}))
        )

    @post("/vuelos", status_code=200)
    async def crear(self, request: Request, data: Dict[str, Any]) -> Dict[str, Any]:
        yo = _yo(request)
        return await _con_cad(yo, lambda: cad_anac.crear_vuelo(yo, _credenciales(yo), data))


async def _envolver(corrutina) -> Dict[str, Any]:
    datos = await corrutina
    return {"datos": datos if isinstance(datos, list) else []}


async def _detalle(corrutina) -> Dict[str, Any]:
    datos = await corrutina
    if isinstance(datos, dict) and isinstance(datos.get("data"), dict):
        datos = datos["data"]
    return datos if isinstance(datos, dict) else {}
