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
    
    # App Configuration
    app_name: str = "FlightLog API"
    debug: bool = True
    allowed_origins: list[str] = [
        "http://localhost:3000",
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
