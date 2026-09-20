from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULT_SECRET_KEY = "vspl-smes-enterprise-production-secret-key-2026"

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "sqlite:///./vspl_smes.db"
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = _INSECURE_DEFAULT_SECRET_KEY
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    ENVIRONMENT: str = "development"
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

settings = Settings()

if settings.ENVIRONMENT.lower() == "production" and settings.SECRET_KEY == _INSECURE_DEFAULT_SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY must be set via environment variable to a unique secret before running with "
        "ENVIRONMENT=production. Refusing to start with the hardcoded development default."
    )
