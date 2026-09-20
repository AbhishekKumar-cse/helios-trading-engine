# Local services (PostgreSQL + Adminer)

Run every command **from the project root**, in Ubuntu, with Docker Desktop open.

The settings come from the project `.env` file, which is never committed. Copy
`.env.example` to `.env` once and put your own password in it.

## Start

```bash
docker compose --env-file .env -f infra/docker-compose.yml up -d
```

`--env-file .env` is needed because Compose otherwise looks for a `.env` next to the
compose file (`infra/.env`), which does not exist. Without it you get
`required variable POSTGRES_USER is missing a value`.

## Check, stop, remove

```bash
docker compose --env-file .env -f infra/docker-compose.yml ps
```

```bash
docker compose --env-file .env -f infra/docker-compose.yml stop
```

```bash
docker compose --env-file .env -f infra/docker-compose.yml down
```

`down` removes the containers but **keeps the data**, which lives in the named volume
`helios_pgdata`. Adding `-v` to `down` deletes that volume and every row in the database, so
only use it when you really want to start over.

## What runs

| Service | Address | Notes |
|---|---|---|
| PostgreSQL 16 | `127.0.0.1:5432` | Only reachable from this machine |
| Adminer 5 | <http://localhost:8080> | Web interface; system **PostgreSQL**, server `postgres`, user and database from `.env` |

## Database structure

Tables are created by Alembic migrations, never by hand:

```bash
uv run alembic upgrade head
```

```bash
uv run alembic current
```

## If Docker Desktop will not start

After an unclean shutdown it can fail with *"The file cannot be accessed by the system"*.
Quit Docker Desktop, delete the leftover socket files in
`%LOCALAPPDATA%\Docker\run` from Ubuntu, then start it again:

```bash
rm -f /mnt/c/Users/bit/AppData/Local/Docker/run/*
```

Quitting Docker from the tray before shutting down or sleeping avoids this.
