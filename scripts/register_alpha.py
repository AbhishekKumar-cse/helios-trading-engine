"""Validate alpha YAML, or register a new DRAFT through the insert-only registry.

    uv run python scripts/register_alpha.py \
        --file configs/alphas/examples/btc_hourly_momentum.yaml --check-only

Omit --check-only to persist the definition in PostgreSQL. No expression or model is executed.
"""

import argparse
import sys
from pathlib import Path

from helios.alpha.definition import load_alpha_definition, register_alpha_definition
from helios.common.config import ConfigError
from helios.common.db import get_engine
from helios.registry.api import RegistryError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument(
        "--check-only", action="store_true", help="validate without database access"
    )
    args = parser.parse_args(argv)
    try:
        definition = load_alpha_definition(args.file)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.check_only:
        print(
            f"valid definition: {definition.alpha_id}@{definition.version} (not registered); "
            f"free parameters: {definition.free_parameter_count} "
            f"({definition.parameter_count_convention or 'unknown model complexity'})"
        )
        return 0
    try:
        with get_engine().begin() as connection:
            stored = register_alpha_definition(connection, definition)
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # never expose connection URLs or secrets in driver messages
        print(f"error: database registration failed ({type(exc).__name__})", file=sys.stderr)
        return 2
    print(
        f"registered DRAFT: {stored.alpha_id}@{stored.version}; "
        f"free parameters: {definition.free_parameter_count} "
        f"({definition.parameter_count_convention or 'unknown model complexity'})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
