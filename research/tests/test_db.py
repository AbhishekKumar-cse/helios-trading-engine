"""Database connection tests (step 025)."""

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from helios.common import db


def test_select_one() -> None:
    """Connects to PostgreSQL and runs SELECT 1. Skips when no DB settings exist (e.g. CI)."""
    try:
        db.get_settings()
    except ValidationError:
        pytest.skip("database settings not configured (no .env / POSTGRES_* variables)")
    with db.get_engine().connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar_one() == 1


def test_password_is_never_shown() -> None:
    """The password must not appear when settings or the URL are printed."""
    settings = db.DatabaseSettings(
        user="u",
        password="very-secret-test-value",
        db="d",
        _env_file=None,
    )
    assert "very-secret-test-value" not in repr(settings)
    assert "very-secret-test-value" not in str(settings.url())
    assert settings.url().drivername == "postgresql+psycopg"
