"""Alembic environment for HELIOS (step 056).

Alembic keeps the shape of the database (tables, columns, indexes) in numbered migration
files that live in git. Running `alembic upgrade head` brings any database up to the version
the code expects, so every teammate's database matches, and a change is reviewed like code
instead of being typed into a database by hand.

The connection is **never written here**: it comes from the POSTGRES_* variables or the
project `.env` file, through `helios.common.db` (step 025), so no password is ever committed.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from helios.common.db import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Tables are declared in the migrations themselves, so there is no model metadata to compare
# against. `--autogenerate` is therefore not used; migrations are written by hand and read in
# review.
target_metadata = None


def database_url() -> str:
    """The URL from the settings, with the password filled in for the connection only."""
    return get_settings().url().render_as_string(hide_password=False)


def run_migrations_offline() -> None:
    """Print the SQL instead of running it (`alembic upgrade head --sql`)."""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the database and run the migrations."""
    settings = config.get_section(config.config_ini_section, {})
    settings["sqlalchemy.url"] = database_url()

    connectable = engine_from_config(settings, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
