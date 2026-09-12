"""Database connection helpers (step 025).

Settings come from environment variables or the project `.env` file (never hard-coded):
POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_HOST, POSTGRES_PORT.
The password is kept as a SecretStr, so it is hidden when settings or URLs are printed.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL, Engine, create_engine

# research/helios/common/db.py -> parents[3] is the project root (where .env lives)
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class DatabaseSettings(BaseSettings):
    """PostgreSQL connection settings, read from POSTGRES_* variables."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_prefix="POSTGRES_",
        extra="ignore",
    )

    user: str
    password: SecretStr
    db: str
    host: str = "localhost"
    port: int = 5432

    def url(self) -> URL:
        """SQLAlchemy URL using the psycopg (v3) driver."""
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.user,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.db,
        )


@lru_cache(maxsize=1)
def get_settings() -> DatabaseSettings:
    """Load settings once. Raises pydantic.ValidationError if they are missing."""
    return DatabaseSettings()


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Shared SQLAlchemy engine; pool_pre_ping drops dead connections automatically."""
    return create_engine(get_settings().url(), pool_pre_ping=True)
