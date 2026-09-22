"""
Borra del storage las fotos que ninguna fila de la base referencia.

Existe porque **borrar una cuenta no borra sus archivos**: el trigger de la migración
002 borra `profiles` y todo cae en cascada —perfil público, publicaciones, filas de
fotos—, pero un trigger no puede llamar a la API de storage. Los archivos quedan. Lo
mismo si una subida se corta entre el storage y la base.

Uso, desde la raíz del backend y con el `.env` de producción:

    python limpiar_storage.py           # en seco: lista qué borraría
    python limpiar_storage.py --borrar  # borra

Sólo toca archivos con más de un día: uno más nuevo puede ser una publicación que se
está creando en este momento, subida al storage y todavía sin su fila.
"""

import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Set

from src.supabase_client import SupabaseManager

BUCKETS = ("publicaciones", "avatares")
PAGINA = 1000


def archivos(storage, bucket: str) -> List[Dict]:
    todos, desde = [], 0
    while True:
        lote = storage.from_(bucket).list("", {"limit": PAGINA, "offset": desde})
        todos.extend(x for x in lote if x.get("id"))  # sin `id` es una carpeta
        if len(lote) < PAGINA:
            return todos
        desde += PAGINA


def referenciados(cliente) -> Dict[str, Set[str]]:
    fotos = cliente.table("publicacion_fotos").select("path").execute().data or []
    avatares = cliente.table("perfiles_publicos").select("avatar_path").not_.is_("avatar_path", "null").execute().data or []
    return {
        "publicaciones": {f["path"] for f in fotos},
        "avatares": {a["avatar_path"] for a in avatares},
    }


def main(borrar: bool) -> int:
    cliente = SupabaseManager.get_service_client()
    en_uso = referenciados(cliente)
    corte = datetime.now(timezone.utc) - timedelta(days=1)
    total = 0
    for bucket in BUCKETS:
        huerfanos = []
        for a in archivos(cliente.storage, bucket):
            creado = datetime.fromisoformat(str(a.get("created_at", "")).replace("Z", "+00:00") or "1970-01-01T00:00:00+00:00")
            if a["name"] not in en_uso[bucket] and creado < corte:
                huerfanos.append(a["name"])
        total += len(huerfanos)
        print(f"{bucket}: {len(huerfanos)} huérfanos")
        for nombre in huerfanos:
            print(f"  {nombre}")
        if borrar and huerfanos:
            for i in range(0, len(huerfanos), 100):
                cliente.storage.from_(bucket).remove(huerfanos[i:i + 100])
            print(f"  → borrados")
    if not borrar and total:
        print("\nEn seco. Para borrarlos: python limpiar_storage.py --borrar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(borrar="--borrar" in sys.argv))
