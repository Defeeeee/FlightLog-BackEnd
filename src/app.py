from litestar import Litestar, Router, Request, Response
from litestar.di import Provide
from litestar.config.cors import CORSConfig
from litestar.openapi import OpenAPIConfig
from litestar.status_codes import HTTP_500_INTERNAL_SERVER_ERROR

from src.controllers.health import HealthController
from src.controllers.profiles import ProfilesController
from src.controllers.aircraft import AircraftController
from src.controllers.flights import FlightsController
from src.controllers.auth import AuthController
from src.controllers.flight_helper import FlightHelperController
from src.controllers.flight_packs import FlightPacksController
from src.auth.security import AuthHandler
from src.config import settings

# 1. Global Exception Handler for a cleaner production response
def internal_server_error_handler(request: Request, exc: Exception) -> Response:
    """Handles unexpected server errors gracefully."""
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
        FlightPacksController
    ],
    dependencies={
        "supabase_client": Provide(AuthHandler.provide_supabase_client)
    }
)

# 5. Main Application Configuration
app = Litestar(
    route_handlers=[api_router],
    cors_config=cors_config,
    openapi_config=openapi_config,
    exception_handlers={Exception: internal_server_error_handler},
    debug=settings.debug
)
