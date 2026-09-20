"""Checks on the Alembic setup (step 056).

These do not need a database. They guard the rule that matters most: no connection string,
and therefore no password, may ever sit in a committed file.
"""

import configparser
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"
MIGRATIONS = PROJECT_ROOT / "research" / "migrations"


def config() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.read(ALEMBIC_INI, encoding="utf-8")
    return parser


def test_alembic_files_exist() -> None:
    assert ALEMBIC_INI.is_file()
    assert (MIGRATIONS / "env.py").is_file()
    assert (MIGRATIONS / "script.py.mako").is_file()
    assert (MIGRATIONS / "versions").is_dir()


def test_no_connection_string_is_committed() -> None:
    """The URL comes from .env at run time; a value here would end up in git."""
    assert not config().has_option("alembic", "sqlalchemy.url")


def test_no_password_like_text_in_the_config() -> None:
    text = ALEMBIC_INI.read_text(encoding="utf-8")
    for marker in ("postgresql://", "postgres://", "password="):
        assert marker not in text


def test_env_reads_settings_instead_of_hard_coding() -> None:
    text = (MIGRATIONS / "env.py").read_text(encoding="utf-8")
    assert "from helios.common.db import get_settings" in text
    assert "postgresql://" not in text


def test_migration_files_are_dated_and_readable() -> None:
    assert config().get("alembic", "file_template").startswith("%(year)d")
    assert config().get("alembic", "timezone") == "UTC"


@pytest.mark.parametrize("name", ["env.py", "script.py.mako"])
def test_scripts_are_not_empty(name: str) -> None:
    assert (MIGRATIONS / name).read_text(encoding="utf-8").strip()
