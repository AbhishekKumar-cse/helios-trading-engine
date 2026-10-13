"""Generate an HTML report from one registered run's verified evidence."""

import argparse

from helios.common.db import get_engine
from helios.registry.results import get_result
from helios.sim.report import generate_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    args = parser.parse_args()
    with get_engine().connect() as connection:
        result = get_result(connection, args.run_id)
    print(generate_report(result))


if __name__ == "__main__":
    main()
