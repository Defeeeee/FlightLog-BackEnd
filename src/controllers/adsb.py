"""
Los recorridos ADS-B, etapa 2 (migraciones 034 y 035, `services/adsb.py`).

- `GET /adsb/vuelos/{flight_id}`: el recorrido real de un vuelo del piloto. Si ya está
  guardado (`vuelo_recorridos`), ése; si no, lo busca en las posiciones de su avión entre su
  despegue y su aterrizaje cargados y, si el vuelo ya terminó, lo guarda con el vuelo.
- `GET /adsb/detectados?aircraft_id=…&fecha=AAAA-MM-DD`: los vuelos que hizo ese avión ese
  día (hora argentina), para sugerir los horarios al registrar uno.

El vuelo y el avión se leen con el cliente del piloto (el RLS dice que son suyos); las
posiciones y los recorridos, con el service role. **Nunca se devuelve un recorrido que no se
superponga con un vuelo cargado por el piloto**: los aviones de escuela los vuelan varios.
Los detectados sí son del día entero del avión, pero sólo horarios: lo mismo que ve cualquiera
en una web de ADS-B, sin mapa.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from litestar import Controller, Request, get
from litestar.exceptions import NotFoundException, ValidationException
from supabase import Client

from src.auth.guards import auth_guard
from src.controllers.social import _yo
from src.services.adsb import (
    MARGEN_DEL_VUELO,
    compactar,
    expandir,
    fuente_de,
    normalizar_matricula,
    resumen,
    tramo_del_vuelo,
    tramos,
    ventana_del_dia,
)
from src.supabase_client import SupabaseManager

_TOPE = 5000


def _fecha(v: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _posiciones(matricula: str, desde: datetime, hasta: datetime) -> list:
    return (
        SupabaseManager.get_service_client().table("adsb_posiciones")
        .select("visto_at,lat,lon,altitud,velocidad")
        .eq("matricula", matricula)
        .gte("visto_at", desde.isoformat())
        .lte("visto_at", hasta.isoformat())
        .order("visto_at")
        .limit(_TOPE)
        .execute().data or []
    )


def _matricula(supabase_client: Client, aircraft_id: Optional[str]) -> Optional[str]:
    if not aircraft_id:
        return None
    filas = supabase_client.table("aircraft").select("registration,is_simulator").eq("id", aircraft_id).limit(1).execute().data or []
    if not filas or filas[0].get("is_simulator"):
        return None
    return normalizar_matricula(filas[0].get("registration"))


class AdsbController(Controller):
    path = "/adsb"
    guards = [auth_guard]

    @get("/vuelos/{flight_id:uuid}")
    async def recorrido(self, request: Request, supabase_client: Client, flight_id: UUID) -> Dict[str, Any]:
        yo = _yo(request)

        def _armar() -> Dict[str, Any]:
            vuelos = (
                supabase_client.table("flights").select("id,takeoff,landing,aircraft_id")
                .eq("id", str(flight_id)).eq("user_id", yo).limit(1).execute().data or []
            )
            if not vuelos:
                raise NotFoundException()
            vuelo = vuelos[0]
            servicio = SupabaseManager.get_service_client()
            guardado = servicio.table("vuelo_recorridos").select("recorrido").eq("flight_id", str(flight_id)).limit(1).execute().data or []
            if guardado:
                comp = guardado[0]["recorrido"]
                return {"recorrido": comp, "resumen": resumen(expandir(comp))}

            despegue, aterrizaje = _fecha(vuelo.get("takeoff")), _fecha(vuelo.get("landing"))
            matricula = _matricula(supabase_client, vuelo.get("aircraft_id"))
            if not despegue or not aterrizaje or not matricula:
                return {"recorrido": None}
            if aterrizaje < despegue:  # un vuelo que cruza la medianoche UTC
                aterrizaje += timedelta(days=1)
            tramo = tramo_del_vuelo(
                _posiciones(matricula, despegue - MARGEN_DEL_VUELO, aterrizaje + MARGEN_DEL_VUELO), despegue, aterrizaje
            )
            if not tramo:
                return {"recorrido": None}
            comp = compactar(tramo, fuente_de(tramo))
            # Se guarda recién cuando el vuelo terminó: antes, el tramo puede seguir creciendo.
            if aterrizaje + MARGEN_DEL_VUELO < datetime.now(timezone.utc):
                servicio.table("vuelo_recorridos").upsert({"flight_id": str(flight_id), "user_id": yo, "recorrido": comp}).execute()
            return {"recorrido": comp, "resumen": resumen(tramo)}

        return await asyncio.to_thread(_armar)

    @get("/detectados")
    async def detectados(self, request: Request, supabase_client: Client, aircraft_id: UUID, fecha: str) -> Dict[str, Any]:
        try:
            desde, hasta = ventana_del_dia(fecha)
        except ValueError:
            raise ValidationException("Fecha inválida")

        def _buscar() -> Dict[str, Any]:
            matricula = _matricula(supabase_client, str(aircraft_id))
            if not matricula:
                return {"vuelos": []}
            return {"vuelos": [resumen(t) for t in tramos(_posiciones(matricula, desde, hasta))]}

        return await asyncio.to_thread(_buscar)
