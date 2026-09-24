from litestar import Litestar, Router, Request, Response
from litestar.di import Provide
from litestar.config.cors import CORSConfig
from litestar.openapi import OpenAPIConfig
from litestar.status_codes import HTTP_500_INTERNAL_SERVER_ERROR
from litestar.exceptions import HTTPException

from src.controllers.health import HealthController
from src.controllers.profiles import ProfilesController
from src.controllers.aircraft import AircraftController
from src.controllers.flights import FlightsController
from src.controllers.auth import AuthController
from src.controllers.flight_helper import FlightHelperController
from src.controllers.flight_packs import FlightPacksController
from src.controllers.planned_flights import PlannedFlightsController
from src.controllers.logbooks import LogbooksController
from src.controllers.custom_stats import CustomStatsController
from src.controllers.dashboard import DashboardController
from src.controllers.transactions import TransactionsController
from src.controllers.whatsapp import WhatsAppController
from src.controllers.audit import AuditController
from src.controllers.documents import DocumentsController, DocumentAlertsController
from src.controllers.charts import ChartsController
from src.controllers.flight_briefings import FlightBriefingsController
from src.controllers.social import (
    PerfilPublicoController,
    PerfilesPublicosController,
    PilotosController,
    SocialController,
)
from src.controllers.cuidado import PushController, ReportesController
from src.controllers.admin import AdminController
from src.controllers.publicaciones import (
    AvatarController,
    PublicacionesController,
    PublicacionesPublicasController,
    RedController,
)
from src.auth.security import AuthHandler
from src.config import settings

# 1. Global Exception Handler for a cleaner production response
def internal_server_error_handler(request: Request, exc: Exception) -> Response:
    """Handles unexpected server errors gracefully."""
    print(f"!!! CRITICAL ERROR at {request.url.path}: {str(exc)}")
    import traceback
    traceback.print_exc()

    # If the exception is a standard Litestar HTTP error, we let it through
    if isinstance(exc, HTTPException):
        return Response(
            content={"detail": exc.detail, "extra": exc.extra},
            status_code=exc.status_code
        )
        
    return Response(
        content={
            "detail": "An unexpected server error occurred.",
            "error": str(exc) if settings.debug else None
        },
        status_code=HTTP_500_INTERNAL_SERVER_ERROR,
    )

# 2. CORS Configuration for cross-origin requests (Frontend apps)
cors_config = CORSConfig(allow_origins=settings.allowed_origins)

# 3. OpenAPI Documentation Configuration
openapi_config = OpenAPIConfig(
    title=settings.app_name,
    version="1.0.0",
    description="Professional Flight Log API with Supabase RLS integration.",
)

# 4. API Router with Shared Path and Dependencies
api_router = Router(
    path="/api",
    route_handlers=[
        AuthController, 
        HealthController, 
        ProfilesController, 
        AircraftController, 
        FlightsController,
        FlightHelperController,
        FlightPacksController, PlannedFlightsController,
        LogbooksController,
        CustomStatsController,
        DashboardController,
        TransactionsController,
        WhatsAppController,
        AuditController,
        DocumentsController,
        DocumentAlertsController,
        FlightBriefingsController,
        ChartsController,
        # La red social. `PerfilesPublicosController` va sin guard: es el perfil que
        # abre el link de /u/... sin cuenta. Ver `src/controllers/social.py`.
        PerfilPublicoController,
        PilotosController,
        SocialController,
        PerfilesPublicosController,
        # El contenido de la red: fotos, publicaciones, la Red y la Actividad. Ver
        # `src/controllers/publicaciones.py`.
        AvatarController,
        PublicacionesController,
        RedController,
        PublicacionesPublicasController,
        # Cuidar la red: avisos push y reportes. Ver `src/controllers/cuidado.py`.
        PushController,
        ReportesController,
        # El panel de administración: sólo para ADMINS_RED, y 404 para el resto.
        AdminController,
    ],
    dependencies={
        "supabase_client": Provide(AuthHandler.provide_supabase_client)
    }
)

def ampliar_pool_de_hilos() -> None:
    """
    Un pool de hilos a la medida de la espera, no de los cores.

    Todo lo que este backend hace contra Supabase es **sincrónico** —`supabase-py`
    no tiene versión async— así que cada consulta sale por `asyncio.to_thread`, que
    usa el executor por defecto del loop. Ese default es
    `min(32, os.cpu_count() + 4)`: en esta máquina de 4 cores, **8 hilos**.

    Ocho alcanzaría si los hilos estuvieran calculando. No lo están: están
    esperando a us-east-1, con el GIL suelto, ~155-180 ms por viaje medidos desde
    el VPS. Y `/dashboard` solo pide **ocho** para sus ocho consultas en paralelo,
    así que una sola carga de dashboard ya llena el pool: el guard de cualquier
    otro request que llegue al mismo tiempo se queda esperando un hilo libre, y esa
    espera cuesta un viaje entero al otro hemisferio.

    Se ve en la medición: seis requests concurrentes tardan 0,17 s de pared; doce
    tardan 0,47 s. El doble de trabajo, casi el triple de tiempo — la firma de un
    pool saturado, no de un CPU saturado (la máquina está al 0,7 de load).

    40 es holgado para el patrón real (cinco cargas de dashboard simultáneas a
    pleno paralelismo) y sigue siendo barato: un hilo bloqueado en red no consume
    CPU, y el proceso entero usa 157 MB en una máquina con 24 GB.

    **No es una licencia para hacer más consultas.** El viaje a us-east-1 lo paga
    igual cada una; esto sólo evita que se hagan cola entre ellas.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    asyncio.get_running_loop().set_default_executor(
        ThreadPoolExecutor(max_workers=40, thread_name_prefix="supabase")
    )


# 5. Main Application Configuration
app = Litestar(
    route_handlers=[api_router],
    cors_config=cors_config,
    openapi_config=openapi_config,
    exception_handlers={Exception: internal_server_error_handler},
    # 30 MB y no los 10 por defecto: una publicación trae hasta cuatro fotos, y aunque
    # el navegador las achica antes de subir, un cliente que mande los originales no
    # tiene que chocar contra el tope. Cada foto igual se corta en 12 MB
    # (`src/services/imagenes.py`).
    request_max_body_size=30_000_000,
    debug=settings.debug,
    on_startup=[ampliar_pool_de_hilos],
)
