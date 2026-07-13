from pydantic import BaseModel
import os
class Settings(BaseModel):
    app_name: str = os.getenv("APP_NAME", "Surf Decision Engine")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./wavewatch.db")
    secret_key: str = os.getenv("SECRET_KEY", "local-dev-only")
    secure_cookies: bool = os.getenv("SECURE_COOKIES", "false").lower() == "true"
    enable_live_fetch: bool = os.getenv("ENABLE_LIVE_FETCH", "true").lower() == "true"
    provider_ledger_writes_enabled: bool = os.getenv("PROVIDER_LEDGER_WRITES_ENABLED", "false").lower() == "true"
    provider_raw_payload_root: str = os.getenv("PROVIDER_RAW_PAYLOAD_ROOT", "data/provider-raw")
    consensus_engine_enabled: bool = os.getenv("CONSENSUS_ENGINE_ENABLED", "false").lower() == "true"
    consensus_engine_version: str = os.getenv("CONSENSUS_ENGINE_VERSION", "consensus-v1")
    consensus_recalculation_debounce_seconds: int = int(os.getenv("CONSENSUS_RECALCULATION_DEBOUNCE_SECONDS", "120"))
    timezone: str = "Europe/Lisbon"
    media_root: str = os.getenv("MEDIA_ROOT", "media")
    max_upload_files: int = int(os.getenv("MAX_UPLOAD_FILES", "10"))
    max_upload_file_mb: int = int(os.getenv("MAX_UPLOAD_FILE_MB", "15"))
    max_upload_total_mb: int = int(os.getenv("MAX_UPLOAD_TOTAL_MB", "60"))
settings=Settings()
