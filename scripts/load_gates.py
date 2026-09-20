"""Put the gate thresholds into the database (step 069).

    uv run python scripts/load_gates.py
    uv run python scripts/load_gates.py --file configs/gates_v2.yaml --author anuj

Running it twice is harmless. If the file has changed under the same version, it refuses and
says what to do: a changed gate is a new version, recorded in an ADR.
"""

import argparse
import sys
from pathlib import Path

from helios.common.db import get_engine
from helios.registry.api import RegistryError
from helios.registry.gates import DEFAULT_GATES_FILE, list_gate_configs, load_gate_config_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=DEFAULT_GATES_FILE)
    parser.add_argument("--author", default="abhishek")
    args = parser.parse_args(argv)

    try:
        with get_engine().begin() as connection:
            stored, is_new = load_gate_config_file(connection, args.file, author=args.author)
            everything = list_gate_configs(connection)
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"{'stored' if is_new else 'already stored'}: {stored.config_id}")
    print(f"  fingerprint      {stored.config_hash}")
    print(f"  G1 sharpe >      {stored.sharpe_min}")
    print(
        f"  G2 fitness >     {stored.fitness_min} (turnover floor {stored.fitness_turnover_floor})"
    )
    print(f"  G3 turnover      {stored.turnover_min} .. {stored.turnover_max}")
    print(f"  G4 out-of-sample {stored.require_out_of_sample}")
    print(f"  G5 stability >   {stored.stability_min_positive_fraction}")
    stress = f"{stored.cost_stress_multiplier}x"
    print(f"  G6 sharpe >      {stored.cost_stress_sharpe_min} at {stress} cost")
    print(f"  effective from   {stored.effective_from}")
    print(f"\ngate versions in the database: {', '.join(c.config_id for c in everything)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
