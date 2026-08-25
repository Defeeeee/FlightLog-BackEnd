from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional

class Settings(BaseSettings):
    """Application settings using Pydantic BaseSettings."""
    
    # Supabase Configuration
    # We map 'supabase_url' to 'SUPABASE_URL' and 'supabase_anon_key' to 'SUPABASE_PUBLISHABLE_KEY'
    supabase_url: str = Field(validation_alias="SUPABASE_URL")
    supabase_anon_key: str = Field(validation_alias="SUPABASE_PUBLISHABLE_KEY")
    supabase_service_role_key: Optional[str] = Field(default=None, validation_alias="SUPABASE_SERVICE_ROLE_KEY")
    
    # Shared secret for the document expiry sweep. Declared explicitly (rather
    # than read off the environment ad hoc) because the endpoint it guards runs
    # under the service role across every user, so it must fail closed when the
    # variable is missing instead of silently falling back to a default.
    documents_alert_secret: Optional[str] = Field(default=None, validation_alias="DOCUMENTS_ALERT_SECRET")
    whatsapp_webhook_secret: Optional[str] = Field(default=None, validation_alias="WHATSAPP_WEBHOOK_SECRET")

    # Dónde vive `Charts/Argentina` en el disco del servidor: cientos de PDF de
    # Jeppesen, fuera de git a propósito (ver ChartsController). Sin configurar,
    # el controller falla cerrado devolviendo vacío/404 en vez de reventar —mismo
    # criterio que `documents_alert_secret`.
    jeppesen_charts_dir: Optional[str] = Field(default=None, validation_alias="JEPPESEN_CHARTS_DIR")

    # Google OAuth Configuration
    google_client_id: Optional[str] = Field(default=None, validation_alias="GOOGLE_CLIENT_ID")
    google_client_secret: Optional[str] = Field(default=None, validation_alias="GOOGLE_CLIENT_SECRET")
    google_callback_url: Optional[str] = Field(default=None, validation_alias="GOOGLE_CALLBACK_URL")
    
    # App Configuration
    app_name: str = "FlightLog API"
    debug: bool = True
    allowed_origins: list[str] = [
        "http://localhost:3000",
        "http://localhost:8081",
        "http://localhost:8082",
        "https://vector.fdiaznem.com.ar",
        "https://flightlog.fdiaznem.com.ar",
        "https://api.flightlog.fdiaznem.com.ar",
        "https://auth.flightlog.fdiaznem.com.ar"
    ] # Change this to your frontend URL in production
    
    # Environment config
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
