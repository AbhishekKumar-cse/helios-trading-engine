"""Run a preregistered simulated bar backtest and retain durable evidence (149)."""

import argparse
import json
from pathlib import Path

from helios.backtest.config import BacktestConfig
from helios.backtest.runner import preregister, run_backtest
from helios.common.config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--preregister", action="store_true")
    args = parser.parse_args()
    config = load_config(args.config, BacktestConfig)
    if args.preregister:
        config = preregister(config)
    path = run_backtest(config)
    print(
        json.dumps(
            dict(
                run_id=config.run_id,
                experiment_id=config.experiment_id,
                mode="BACKTEST",
                artifact=str(path),
            )
        )
    )


if __name__ == "__main__":
    main()
