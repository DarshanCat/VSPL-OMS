import os
import re
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_INSECURE_DEFAULT_SECRET_KEY = "vspl-smes-enterprise-production-secret-key-2026"

# Anchor .env and any relative sqlite:/// path to this file's own directory (backend/),
# never to the process's current working directory. Previously env_file=".env" and
# SQLAlchemy's own relative-path resolution were both silently cwd-relative: running
# from the wrong directory (e.g. the repo root instead of backend/) found no .env file
# there, fell back to this module's hardcoded default -- which happens to be byte-identical
# to the real .env value -- and created/opened a second, different SQLite file next to
# that wrong cwd instead of raising any visible error.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
_DOTENV_PATH = _BACKEND_ROOT / ".env"
_DEFAULT_DATABASE_URL = "sqlite:///./vspl_smes.db"
_RELATIVE_SQLITE_PREFIX = "sqlite:///"  # exactly 3 slashes; sqlite:////... (4) is already absolute


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_DOTENV_PATH), extra="ignore")

    DATABASE_URL: str = _DEFAULT_DATABASE_URL
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = _INSECURE_DEFAULT_SECRET_KEY
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    ENVIRONMENT: str = "development"
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


def database_url_source(settings_obj: "Settings") -> str:
    """Where DATABASE_URL's value actually came from, in the same precedence order
    pydantic-settings itself applies: a real OS environment variable beats a value
    loaded from .env, which beats this module's hardcoded default. Both of the first
    two cases leave "DATABASE_URL" in `model_fields_set`, so distinguishing them requires
    checking os.environ directly rather than relying on model_fields_set alone."""
    if "DATABASE_URL" in os.environ:
        return "explicit_env_var"
    if "DATABASE_URL" in settings_obj.model_fields_set:
        return "dotenv_file"
    return "class_default"


def resolve_relative_sqlite_url(url: str, anchor: Path) -> str:
    """Rewrite a relative sqlite:///X URL to an absolute path anchored at `anchor`
    (backend/), instead of the process cwd. Any other URL -- a non-sqlite URL (e.g.
    Postgres), or an already-absolute sqlite:////X URL -- is returned unchanged: an
    operator who explicitly configured one of those is assumed to mean exactly what
    they wrote, and it must never be silently redirected."""
    if url.startswith(_RELATIVE_SQLITE_PREFIX) and not url[len(_RELATIVE_SQLITE_PREFIX):].startswith("/"):
        relative_path = url[len(_RELATIVE_SQLITE_PREFIX):]
        return _RELATIVE_SQLITE_PREFIX + str((anchor / relative_path).resolve())
    return url


def redact_database_url(url: str) -> str:
    """Strip userinfo (user:pass@) from a URL before it is ever logged."""
    return re.sub(r"://[^/@]+@", "://***:***@", url)


settings = Settings()
_database_url_source = database_url_source(settings)
settings.DATABASE_URL = resolve_relative_sqlite_url(settings.DATABASE_URL, _BACKEND_ROOT)

print(
    f"[config] DATABASE_URL resolved (source={_database_url_source}, "
    f"anchor={_BACKEND_ROOT}): {redact_database_url(settings.DATABASE_URL)}"
)

if settings.ENVIRONMENT.lower() == "production" and settings.SECRET_KEY == _INSECURE_DEFAULT_SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY must be set via environment variable to a unique secret before running with "
        "ENVIRONMENT=production. Refusing to start with the hardcoded development default."
    )
