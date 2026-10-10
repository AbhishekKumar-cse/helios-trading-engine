"""Validate (--check-only) or atomically register the three fixed hourly baselines.

Registration inserts definitions only: initial DRAFT, without any result or
lifecycle transition. Existing versions are refused and roll back the whole batch.
"""

import argparse
import sys
from pathlib import Path

from helios.alpha.definition import load_alpha_definition, register_alpha_definition
from helios.alpha.safety import validate_expression
from helios.common.db import get_engine
from helios.features import basic  # noqa: F401 - populate the feature schema
from helios.features.registry import REGISTRY

BASELINE_DIR = Path(__file__).resolve().parents[1] / "configs/alphas/baselines"
BASELINE_FILES = ("b0_momentum.yaml", "b1_reversal.yaml", "b2_taker_flow.yaml")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=BASELINE_DIR)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        definitions = [load_alpha_definition(args.directory / name) for name in BASELINE_FILES]
        for definition in definitions:
            if definition.expression is None:
                raise ValueError("baselines require expressions")
            validate_expression(
                definition.expression,
                feature_names=REGISTRY.names(),
                params=definition.params,
                interval="1h",
            )
    except Exception as exc:
        print(f"error: baseline validation failed ({type(exc).__name__})", file=sys.stderr)
        return 2
    if not args.check_only:
        try:
            with get_engine().begin() as connection:
                for definition in definitions:
                    register_alpha_definition(connection, definition)
        except Exception as exc:
            print(f"error: registration rolled back ({type(exc).__name__})", file=sys.stderr)
            return 2
    for definition in definitions:
        action = "valid (not registered)" if args.check_only else "registered DRAFT"
        print(
            f"{action}: {definition.alpha_id}@{definition.version}; "
            f"free parameters: {definition.free_parameter_count}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
