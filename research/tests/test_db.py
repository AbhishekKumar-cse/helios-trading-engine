"""Database connection tests (step 025)."""

from sqlalchemy import Connection, text

from helios.common import db


def test_select_one(connection: Connection) -> None:
    """Connects to PostgreSQL and runs SELECT 1.

    It uses the shared `connection` fixture, so it skips for the same reasons every other
    database test does: no settings, or no database running. Before, it skipped on missing
    settings but *failed* when Docker was merely stopped, which made one red test sit among
    a hundred honest skips.
    """
    assert connection.execute(text("SELECT 1")).scalar_one() == 1


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
