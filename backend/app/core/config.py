from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "sqlite:///./vspl_smes.db"
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = "vspl-smes-enterprise-production-secret-key-2026"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    ENVIRONMENT: str = "development"

settings = Settings()
