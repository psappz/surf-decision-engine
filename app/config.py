from pydantic import BaseModel
import os
class Settings(BaseModel):
    app_name: str = os.getenv("APP_NAME", "WaveWatch")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./wavewatch.db")
    secret_key: str = os.getenv("SECRET_KEY", "local-dev-only")
    secure_cookies: bool = os.getenv("SECURE_COOKIES", "false").lower() == "true"
    enable_live_fetch: bool = os.getenv("ENABLE_LIVE_FETCH", "true").lower() == "true"
    timezone: str = "Europe/Lisbon"
settings=Settings()
