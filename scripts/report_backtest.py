"""Generate a report from immutable completed backtest evidence (150)."""

import argparse

from helios.backtest.report import generate_backtest_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    print(generate_backtest_report(args.run_id))


if __name__ == "__main__":
    main()
