"""
Los avisos push de la red: "Fulano aplaudió tu publicación", "Mengano te pidió seguirte".

- **Web push con VAPID** (`pywebpush`). Sin las dos claves configuradas
  (`VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`) no se manda nada, y todo lo demás anda igual.
- **Nunca demora ni rompe lo que el piloto hizo.** Se manda en un hilo aparte, después de
  que la acción ya se guardó, y cualquier error se registra y se olvida: un aviso que no
  llega es mucho mejor que un aplauso que falla.
- **Las suscripciones muertas se borran.** Si el servicio de push del navegador contesta
  404 o 410, esa suscripción ya no existe (se desinstaló la app, se revocó el permiso).
- **Lo que dice cada aviso sale de `armar_aviso`**, que es pura y está testeada: quién,
  qué, y a qué pantalla lleva tocarlo. Nunca datos de la bitácora.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable, Dict, List, Optional


log = logging.getLogger(__name__)

#: Cuánto guarda el servicio de push un aviso para un teléfono apagado: un día. Un
#: "te aplaudieron" de hace una semana no le sirve a nadie.
TTL_SEGUNDOS = 24 * 60 * 60

ACTIVIDAD = "/dashboard/pilotos/actividad"


def _settings():
    """
    La configuración, recién cuando hace falta. Importada arriba, cargar este módulo
    exigía el `.env` completo, y lo puro de acá (`armar_aviso`, `es_suscripcion_muerta`)
    no se podía testear sin él: el CI no tiene `.env`.
    """
    from src.config import settings

    return settings


def avisos_configurados() -> bool:
    s = _settings()
    return bool(s.vapid_public_key and s.vapid_private_key)


def _recortar(texto: Optional[str], largo: int) -> str:
    limpio = " ".join((texto or "").split())
    return limpio if len(limpio) <= largo else limpio[: largo - 1].rstrip() + "…"


def armar_aviso(
    tipo: str,
    quien: str,
    *,
    texto: Optional[str] = None,
    url: Optional[str] = None,
) -> Dict[str, str]:
    """
    El aviso para mostrar: `titulo`, `cuerpo`, `url` y `etiqueta`.

    La etiqueta agrupa por tipo: el teléfono reemplaza el aviso anterior de la misma
    etiqueta en vez de apilar diez "te aplaudieron".
    """
    nombre = _recortar(quien, 40) or "Un piloto"
    if tipo == "seguidor":
        aviso = {"titulo": f"{nombre} empezó a seguirte", "cuerpo": "Mirá quién es en tu Actividad.", "url": ACTIVIDAD}
    elif tipo == "solicitud":
        aviso = {"titulo": f"{nombre} te pidió seguirte", "cuerpo": "Aceptala o rechazala en tu Actividad.", "url": ACTIVIDAD}
    elif tipo == "aceptada":
        aviso = {
            "titulo": f"{nombre} aceptó tu solicitud",
            "cuerpo": "Ya ves sus horas y lo que publica.",
            "url": url or "/dashboard/pilotos",
        }
    elif tipo == "aplauso":
        aviso = {
            "titulo": f"{nombre} aplaudió tu publicación",
            "cuerpo": _recortar(texto, 80) or "Mirá tu Actividad.",
            "url": ACTIVIDAD,
        }
    elif tipo == "comentario":
        aviso = {"titulo": f"{nombre} comentó tu publicación", "cuerpo": _recortar(texto, 120), "url": ACTIVIDAD}
    elif tipo == "reporte":
        aviso = {"titulo": "Nuevo reporte en la red", "cuerpo": _recortar(texto, 120), "url": "/dashboard"}
    else:
        raise ValueError(f"Tipo de aviso desconocido: {tipo}")
    aviso["etiqueta"] = f"vector-{tipo}"
    return aviso


def es_suscripcion_muerta(codigo: Optional[int]) -> bool:
    """404/410 del servicio de push: la suscripción ya no existe y hay que borrarla."""
    return codigo in (404, 410)


def _suscripciones(user_id: str) -> List[Dict[str, Any]]:
    from src.supabase_client import SupabaseManager

    return (
        SupabaseManager.get_service_client().table("suscripciones_push")
        .select("id, endpoint, p256dh, auth").eq("user_id", user_id).execute().data
        or []
    )


def _borrar_suscripcion(suscripcion_id: str) -> None:
    from src.supabase_client import SupabaseManager

    SupabaseManager.get_service_client().table("suscripciones_push").delete().eq("id", suscripcion_id).execute()


def enviar_ahora(user_id: str, aviso: Dict[str, str]) -> None:
    """Manda el aviso a todos los navegadores de `user_id`, en este hilo."""
    if not avisos_configurados():
        return
    from pywebpush import WebPushException, webpush

    datos = json.dumps(aviso, ensure_ascii=False)
    for s in _suscripciones(user_id):
        try:
            webpush(
                subscription_info={"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}},
                data=datos,
                vapid_private_key=_settings().vapid_private_key,
                vapid_claims={"sub": _settings().vapid_subject},
                ttl=TTL_SEGUNDOS,
            )
        except WebPushException as exc:
            codigo = getattr(getattr(exc, "response", None), "status_code", None)
            if es_suscripcion_muerta(codigo):
                _borrar_suscripcion(s["id"])
            else:
                log.warning("[avisos] no se pudo mandar a %s: %s", s["endpoint"][:60], exc)


def en_segundo_plano(tarea: Callable[[], None]) -> None:
    """
    Corre `tarea` en un hilo aparte y se olvida. Para lo que acompaña a una acción ya
    guardada —buscar a quién avisar, mandar el aviso—: nada de eso puede demorar la
    respuesta ni tirarla abajo.
    """
    if not avisos_configurados():
        return

    def _correr() -> None:
        try:
            tarea()
        except Exception as exc:  # noqa: BLE001 — un aviso nunca tira abajo nada
            log.warning("[avisos] falló el envío: %r", exc)

    threading.Thread(target=_correr, name="aviso-push", daemon=True).start()


def enviar_aviso(user_id: Optional[str], aviso: Dict[str, str]) -> None:
    """Manda el aviso a todos los navegadores de `user_id`, en segundo plano."""
    if user_id:
        en_segundo_plano(lambda: enviar_ahora(user_id, aviso))


def admins() -> List[str]:
    return [a.strip() for a in (_settings().admins_red or "").split(",") if a.strip()]
